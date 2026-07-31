"""Document knowledge pipeline: LINE -> Google Drive -> advisor context.

- LINE webhook receives text/files the CEO sends to the bot
- content is uploaded to a Google Drive folder (service account); if Drive
  is not configured yet, files land in a local mirror so nothing is lost
- advisors pull a compact digest of all documents into their prompts,
  so the board learns the CEO's actual business from primary sources
"""
import base64
import hashlib
import hmac
import io
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import config

log = logging.getLogger("hub.docs")

LOCAL_DIR = config.ROOT / "docs_store"
LOCAL_DIR.mkdir(exist_ok=True)
_META = LOCAL_DIR / "_meta.json"

EXT = {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf",
       "text/plain": ".txt", "audio/m4a": ".m4a", "video/mp4": ".mp4"}


# ── credentials ──

def drive_ready() -> bool:
    return bool(config.GDRIVE_SA_JSON and Path(config.GDRIVE_SA_JSON).exists())


def line_ready() -> bool:
    return bool(config.LINE_CHANNEL_SECRET and config.LINE_ACCESS_TOKEN)


def _drive():
    """Build a Drive v3 client from the service-account JSON."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(
        config.GDRIVE_SA_JSON, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ── metadata ──

def _load_meta() -> list:
    return json.loads(_META.read_text(encoding="utf-8")) if _META.exists() else []


def _save_meta(meta: list) -> None:
    _META.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def _record(name: str, source: str, location: str, mime: str,
            drive_id: str | None = None, text: str | None = None,
            project: str | None = None) -> dict:
    meta = _load_meta()
    entry = {"id": len(meta) + 1, "name": name, "source": source, "location": location,
             "mime": mime, "drive_id": drive_id, "text": (text or "")[:3000] or None,
             "project": project,
             "at": datetime.now(timezone.utc).isoformat()}
    meta.append(entry)
    _save_meta(meta)
    return entry


# ── projects (Drive folders per business project, e.g. "YourFin") ──

def list_projects() -> list[str]:
    """Project names = subfolders of the Drive root folder + local subdirs."""
    names = {p.name for p in LOCAL_DIR.iterdir() if p.is_dir()}
    if drive_ready() and config.GDRIVE_FOLDER_ID:
        try:
            q = (f"'{config.GDRIVE_FOLDER_ID}' in parents and trashed=false "
                 "and mimeType='application/vnd.google-apps.folder'")
            for f in _drive().files().list(q=q, fields="files(name)", pageSize=100).execute()["files"]:
                names.add(f["name"])
        except Exception as e:  # noqa: BLE001
            log.warning("list drive projects failed: %s", e)
    return sorted(names)


def create_project(name: str) -> dict:
    """Create the project folder locally and (when connected) in Drive."""
    (LOCAL_DIR / name).mkdir(exist_ok=True)
    drive_id = None
    if drive_ready():
        try:
            drive_id = _project_folder_id(name)
        except Exception as e:  # noqa: BLE001
            log.warning("create drive project failed: %s", e)
    return {"name": name, "drive_id": drive_id, "projects": list_projects()}


def _project_folder_id(name: str) -> str:
    """Find-or-create the Drive subfolder for a project."""
    svc = _drive()
    q = (f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
         + (f" and '{config.GDRIVE_FOLDER_ID}' in parents" if config.GDRIVE_FOLDER_ID else ""))
    found = svc.files().list(q=q, fields="files(id)", pageSize=1).execute()["files"]
    if found:
        return found[0]["id"]
    body: dict = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if config.GDRIVE_FOLDER_ID:
        body["parents"] = [config.GDRIVE_FOLDER_ID]
    return svc.files().create(body=body, fields="id").execute()["id"]


# ── the librarian: scan -> classify -> file into the right project ──

def describe_image(content: bytes, mime: str) -> str | None:
    """OCR/describe an image via Gemini multimodal so it can be classified."""
    if not config.GOOGLE_API_KEY:
        return None
    try:
        model = config.PROVIDERS["gemini"]["model"]
        r = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": config.GOOGLE_API_KEY},
            json={"contents": [{"parts": [
                {"text": "อ่านเอกสาร/รูปนี้แล้วสรุปเป็นภาษาไทย: เป็นเอกสารอะไร มีข้อมูลสำคัญอะไร (ตัวเลข ชื่อ วันที่) ตอบไม่เกิน 6 บรรทัด"},
                {"inline_data": {"mime_type": mime, "data": base64.b64encode(content).decode()}},
            ]}]},
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:  # noqa: BLE001
        log.warning("image describe failed: %s", e)
        return None


def classify_project(name: str, text: str | None) -> str | None:
    """Ask the LLM which project folder this document belongs to."""
    from . import llm
    projects = list_projects()
    if not projects or not (text or name):
        return None
    provider = next((p for p in ("gemini", "anthropic", "manus") if llm.provider_ready(p)), None)
    if provider is None:
        return None
    out = llm.chat(
        provider,
        ("คุณคือบรรณารักษ์เอกสารธุรกิจ จัดเอกสารเข้าโปรเจคที่ถูกต้อง\n"
         f"รายชื่อโปรเจคที่มี: {', '.join(projects)}\n"
         "ตอบชื่อโปรเจคเพียงคำเดียวจากรายชื่อข้างต้นเท่านั้น ห้ามอธิบาย "
         "ถ้าไม่แน่ใจจริงๆ ให้ตอบ UNKNOWN"),
        f"ชื่อไฟล์: {name}\nเนื้อหา:\n{(text or '')[:1500]}",
    )
    if not out["ok"]:
        return None
    answer = out["text"].strip().splitlines()[0].strip()
    return answer if answer in projects else None


def _file_into_project(entry_name: str, drive_id: str | None, project: str) -> None:
    """Move the stored file into its project folder (local mirror + Drive)."""
    src = LOCAL_DIR / entry_name
    if src.exists():
        dest = LOCAL_DIR / project
        dest.mkdir(exist_ok=True)
        src.rename(dest / entry_name)
    if drive_id and drive_ready():
        try:
            svc = _drive()
            folder = _project_folder_id(project)
            prev = ",".join(svc.files().get(fileId=drive_id, fields="parents").execute().get("parents", []))
            svc.files().update(fileId=drive_id, addParents=folder,
                               removeParents=prev, fields="id").execute()
        except Exception as e:  # noqa: BLE001
            log.warning("drive move failed: %s", e)


# ── ingest ──

def save_document(name: str, content: bytes, mime: str, source: str,
                  text: str | None = None, project: str | None = None) -> dict:
    """Librarian pipeline: store -> scan -> classify -> file into project.

    An explicit `project` (the CEO picked one while uploading) wins over the
    librarian's guess.
    """
    (LOCAL_DIR / name).write_bytes(content)
    drive_id = None
    location = "local"
    if drive_ready():
        try:
            from googleapiclient.http import MediaIoBaseUpload
            media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime)
            body: dict = {"name": name}
            if config.GDRIVE_FOLDER_ID:
                body["parents"] = [config.GDRIVE_FOLDER_ID]
            f = _drive().files().create(body=body, media_body=media, fields="id").execute()
            drive_id, location = f["id"], "drive"
        except Exception as e:  # noqa: BLE001 — Drive down must not lose the doc
            log.warning("drive upload failed, kept local: %s", e)

    # scan: images get OCR'd/described so they carry classifiable text
    if text is None and mime.startswith("image/"):
        text = describe_image(content, mime)

    # classify + file into the right project folder (e.g. ตารางผ่อนมือถือ -> YourFin)
    if not project:
        project = classify_project(name, text)
    if project:
        _file_into_project(name, drive_id, project)
    return _record(name, source, location, mime, drive_id, text, project)


def sync_from_drive() -> dict:
    """Pull docs that were added to the Drive folder directly (not via LINE)."""
    if not drive_ready():
        return {"synced": 0, "error": "Google Drive ยังไม่เชื่อมต่อ (ตั้ง GDRIVE_SERVICE_ACCOUNT_JSON)"}
    known = {m["drive_id"] for m in _load_meta() if m.get("drive_id")}
    q = f"'{config.GDRIVE_FOLDER_ID}' in parents and trashed=false" if config.GDRIVE_FOLDER_ID else "trashed=false"
    svc = _drive()
    files = svc.files().list(q=q, fields="files(id,name,mimeType)", pageSize=100).execute()["files"]
    synced = 0
    for f in files:
        if f["id"] in known:
            continue
        text = None
        try:
            if f["mimeType"].startswith("text/") or f["mimeType"] == "application/vnd.google-apps.document":
                if f["mimeType"].startswith("application/vnd.google-apps"):
                    text = svc.files().export(fileId=f["id"], mimeType="text/plain").execute().decode()
                else:
                    text = svc.files().get_media(fileId=f["id"]).execute().decode()
        except Exception:  # noqa: BLE001
            pass
        _record(f["name"], "drive", "drive", f["mimeType"], f["id"], text)
        synced += 1
    return {"synced": synced, "total": len(_load_meta())}


def list_documents(limit: int = 50) -> list:
    return _load_meta()[-limit:][::-1]


def delete_document(doc_id: int) -> dict | None:
    """Drop a document the CEO says is stale or superseded.

    The board reads this library on every consult, so a document left behind
    after the facts changed keeps steering advice with numbers nobody believes
    any more. Removal is best-effort per layer: the metadata entry always goes,
    and a Drive or local file that resists deletion is reported rather than
    silently leaving a ghost in the list.
    """
    meta = _load_meta()
    entry = next((m for m in meta if m["id"] == doc_id), None)
    if entry is None:
        return None

    removed = {"local": False, "drive": False, "errors": []}
    for path in (LOCAL_DIR / entry["name"],
                 LOCAL_DIR / (entry.get("project") or "") / entry["name"]):
        try:
            if path.is_file():
                path.unlink()
                removed["local"] = True
        except OSError as e:
            removed["errors"].append(f"ลบไฟล์ในเครื่องไม่สำเร็จ: {e}")

    if entry.get("drive_id") and drive_ready():
        try:
            _drive().files().update(fileId=entry["drive_id"],
                                    body={"trashed": True}).execute()
            removed["drive"] = True
        except Exception as e:  # noqa: BLE001 — Drive down must not block the removal
            log.warning("drive trash failed for %s: %s", entry["name"], e)
            removed["errors"].append(f"ย้ายไฟล์ใน Google Drive ลงถังขยะไม่สำเร็จ: {str(e)[:120]}")

    _save_meta([m for m in meta if m["id"] != doc_id])
    return {"deleted": doc_id, "name": entry["name"], **removed}


def reclassify_all() -> dict:
    """Re-run the librarian over unfiled documents (after creating new projects)."""
    meta = _load_meta()
    filed = 0
    for m in meta:
        if m.get("project"):
            continue
        project = classify_project(m["name"], m.get("text"))
        if project:
            _file_into_project(m["name"], m.get("drive_id"), project)
            m["project"] = project
            filed += 1
    _save_meta(meta)
    return {"filed": filed, "unfiled": sum(1 for m in meta if not m.get("project"))}


def knowledge_context(max_chars: int = 3500, project: str | None = None) -> str:
    """Digest of the CEO's documents for advisor prompts.

    `project` scopes the board to one business project so a consult about
    YourFin is not muddied by FlowerVending paperwork; None feeds everything.
    """
    by_project: dict[str, list] = {}
    for m in reversed(_load_meta()):
        name = m.get("project") or "ทั่วไป"
        if project and name != project:
            continue
        by_project.setdefault(name, []).append(m)
    parts = []
    for project, ms in sorted(by_project.items()):
        parts.append(f"### โปรเจค: {project}")
        for m in ms:
            head = f"[เอกสาร: {m['name']} ({m['at'][:10]})]"
            parts.append(f"{head}\n{m['text']}" if m.get("text") else head)
    if not parts:
        return ""
    return "\n\n".join(parts)[:max_chars]


# ── LINE webhook ──

def verify_line_signature(body: bytes, signature: str) -> bool:
    mac = hmac.new(config.LINE_CHANNEL_SECRET.encode(), body, hashlib.sha256)
    return hmac.compare_digest(base64.b64encode(mac.digest()).decode(), signature or "")


def _line_content(message_id: str) -> bytes:
    r = httpx.get(f"https://api-data.line.me/v2/bot/message/{message_id}/content",
                  headers={"Authorization": f"Bearer {config.LINE_ACCESS_TOKEN}"}, timeout=60)
    r.raise_for_status()
    return r.content


def _line_reply(token: str, text: str) -> None:
    try:
        httpx.post("https://api.line.me/v2/bot/message/reply",
                   headers={"Authorization": f"Bearer {config.LINE_ACCESS_TOKEN}"},
                   json={"replyToken": token, "messages": [{"type": "text", "text": text}]},
                   timeout=15)
    except Exception as e:  # noqa: BLE001
        log.warning("line reply failed: %s", e)


def handle_line_events(payload: dict) -> list:
    """Process LINE message events: text -> note; media/file -> Drive."""
    saved = []
    for ev in payload.get("events", []):
        if ev.get("type") != "message":
            continue
        msg = ev["message"]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        try:
            if msg["type"] == "text":
                name = f"line_note_{stamp}.txt"
                content = msg["text"].encode()
                entry = save_document(name, content, "text/plain", "line", msg["text"])
            elif msg["type"] in ("image", "video", "audio", "file"):
                blob = _line_content(msg["id"])
                fname = msg.get("fileName") or f"line_{msg['type']}_{stamp}{EXT.get(msg.get('contentProvider', {}).get('type', ''), '') or {'image': '.jpg', 'video': '.mp4', 'audio': '.m4a'}.get(msg['type'], '.bin')}"
                mime = {"image": "image/jpeg", "video": "video/mp4",
                        "audio": "audio/m4a"}.get(msg["type"], "application/octet-stream")
                entry = save_document(fname, blob, mime, "line")
            else:
                continue
            saved.append(entry)
            where = "Google Drive ✅" if entry["location"] == "drive" else "คลังในเครื่อง (Drive ยังไม่เชื่อมต่อ) ⚠️"
            filed = (f"\n🗂 จัดเข้าโปรเจค: {entry['project']}" if entry.get("project")
                     else "\n🗂 ยังไม่รู้ว่าโปรเจคไหน — สร้างโปรเจคในหน้าเอกสารแล้วกด reclassify ได้")
            if ev.get("replyToken"):
                _line_reply(ev["replyToken"],
                            f"📁 รับเอกสาร \"{entry['name']}\" แล้ว → {where}{filed}\nบอร์ดที่ปรึกษาจะใช้ศึกษางานของคุณทันที")
        except Exception as e:  # noqa: BLE001 — one bad event must not kill the webhook
            log.exception("line event failed")
            if ev.get("replyToken"):
                _line_reply(ev["replyToken"], f"⚠️ บันทึกเอกสารไม่สำเร็จ: {str(e)[:100]}")
    return saved
