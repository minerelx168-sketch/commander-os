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
            drive_id: str | None = None, text: str | None = None) -> dict:
    meta = _load_meta()
    entry = {"id": len(meta) + 1, "name": name, "source": source, "location": location,
             "mime": mime, "drive_id": drive_id, "text": (text or "")[:3000] or None,
             "at": datetime.now(timezone.utc).isoformat()}
    meta.append(entry)
    _save_meta(meta)
    return entry


# ── ingest ──

def save_document(name: str, content: bytes, mime: str, source: str,
                  text: str | None = None) -> dict:
    """Upload to Drive when connected; always keep a local mirror."""
    (LOCAL_DIR / name).write_bytes(content)
    drive_id = None
    location = "local"
    if drive_ready():
        try:
            from googleapiclient.http import MediaIoBaseUpload
            media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime)
            body = {"name": name}
            if config.GDRIVE_FOLDER_ID:
                body["parents"] = [config.GDRIVE_FOLDER_ID]
            f = _drive().files().create(body=body, media_body=media, fields="id").execute()
            drive_id, location = f["id"], "drive"
        except Exception as e:  # noqa: BLE001 — Drive down must not lose the doc
            log.warning("drive upload failed, kept local: %s", e)
    return _record(name, source, location, mime, drive_id, text)


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


def knowledge_context(max_chars: int = 3500) -> str:
    """Digest of the CEO's documents injected into every advisor prompt."""
    parts = []
    for m in reversed(_load_meta()):
        head = f"[เอกสาร: {m['name']} ({m['at'][:10]})]"
        parts.append(f"{head}\n{m['text']}" if m.get("text") else head)
    if not parts:
        return ""
    out = "\n\n".join(parts)
    return out[:max_chars]


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
            if ev.get("replyToken"):
                _line_reply(ev["replyToken"],
                            f"📁 รับเอกสาร \"{entry['name']}\" แล้ว → {where}\nบอร์ดที่ปรึกษาจะใช้ศึกษางานของคุณทันที")
        except Exception as e:  # noqa: BLE001 — one bad event must not kill the webhook
            log.exception("line event failed")
            if ev.get("replyToken"):
                _line_reply(ev["replyToken"], f"⚠️ บันทึกเอกสารไม่สำเร็จ: {str(e)[:100]}")
    return saved
