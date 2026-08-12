"""Data sources — per-project connections to POS / back-office APIs.

Each project runs on different systems: one is on a POS with a REST endpoint,
another on a Google Sheet, another on a webhook that pushes. So a connector is
described, not hard-coded: the CEO says where to call, how to authenticate and
which field holds the rows, and the hub fetches on demand.

Fetched data is summarised (never dumped whole) into the same knowledge context
the advisors already read, so a routine or a board session sees live numbers
from the project's own system instead of last month's PDF.

Secrets are stored server-side and never returned by the API — the UI only ever
sees whether a key exists.
"""
import hmac
import json
import logging
import secrets
import threading
from datetime import datetime, timezone

import httpx

from . import config

log = logging.getLogger("hub.sources")

_LOCK = threading.Lock()
_FILE = config.MEMORY_DIR / "sources.json"

KINDS = {
    "pos_rest": "POS / REST API (JSON)",
    "sheet_csv": "Google Sheet / CSV (published link)",
    "webhook": "Webhook (ระบบหลังบ้านส่งข้อมูลเข้ามาเอง)",
}

AUTHS = {
    "none": "ไม่ต้องยืนยันตัวตน",
    "bearer": "Bearer token",
    "header": "Custom header (เช่น X-API-Key)",
    "query": "Query parameter (เช่น ?api_key=…)",
}

MAX_ROWS = 200          # what we keep from one pull
MAX_CHARS = 2600        # what one source may contribute to a prompt


def _load() -> list:
    if _FILE.exists():
        rows = json.loads(_FILE.read_text(encoding="utf-8"))
        changed = False
        for s in rows:
            # Connectors created before per-project keys existed get one now,
            # rather than silently staying unattributable.
            if not s.get("ingest_key"):
                s["ingest_key"] = f"cx_{secrets.token_urlsafe(24)}"
                changed = True
            # One feed can legitimately inform several projects (a shared POS,
            # a group-wide ledger). `project` stays as the attribution owner —
            # the one an inbound push is filed under — while `projects` is the
            # set of boards allowed to read it.
            if not s.get("projects"):
                s["projects"] = [s["project"]] if s.get("project") else []
                changed = True
        if changed:
            _FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        return rows
    return []


def _save(rows: list) -> None:
    _FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def _public(s: dict) -> dict:
    """Everything except the outbound credential.

    `secret` is what we send TO the CEO's system, so it never leaves the
    server. `ingest_key` is the opposite direction — the credential their
    backend must present to us — so it is returned: they cannot use what they
    cannot read.
    """
    return {k: v for k, v in s.items() if k != "secret"} | {"has_secret": bool(s.get("secret"))}


def list_sources(project: str | None = None) -> list:
    with _LOCK:
        rows = _load()
    if project:
        rows = [s for s in rows if project in _linked(s)]
    return [_public(s) for s in rows]


def _linked(s: dict) -> list:
    """Every project this connector feeds — owner included."""
    return s.get("projects") or ([s["project"]] if s.get("project") else [])


def set_projects(source_id: int, projects: list) -> dict | None:
    """Which boards may read this feed. The owner project always stays in the
    set: it is where inbound pushes are filed, so dropping it would orphan the
    data it is already collecting."""
    s = get_source(source_id)
    if s is None:
        return None
    owner = s.get("project")
    linked = [p for p in dict.fromkeys(projects) if p]
    if owner and owner not in linked:
        linked.insert(0, owner)
    return update_source(source_id, projects=linked)


def get_source(source_id: int) -> dict | None:
    with _LOCK:
        return next((s for s in _load() if s["id"] == source_id), None)


def by_ingest_key(key: str) -> dict | None:
    """Which connector — and therefore which project — does this key belong to?

    This is what makes multi-backend attribution unambiguous: the key IS the
    identity, so a caller cannot claim to be a project it does not own.
    """
    if not key:
        return None
    with _LOCK:
        rows = _load()
    return next((s for s in rows
                 if s.get("ingest_key") and hmac.compare_digest(s["ingest_key"], key)), None)


def add_source(project: str, name: str, kind: str, url: str, auth: str,
               secret: str, header_name: str, data_path: str) -> dict:
    entry = {"id": None, "project": project, "projects": [project],
             "name": name, "kind": kind, "url": url,
             "auth": auth, "secret": secret, "header_name": header_name or "X-API-Key",
             "data_path": data_path, "enabled": True,
             # Every connector gets its own inbound key, so pushed data is
             # attributed to one project by construction rather than by trust.
             "ingest_key": f"cx_{secrets.token_urlsafe(24)}",
             "last_sync": None, "last_status": None, "rows": 0, "sample": None,
             "created_at": datetime.now(timezone.utc).isoformat()}
    with _LOCK:
        rows = _load()
        entry["id"] = max((s["id"] for s in rows), default=0) + 1
        rows.append(entry)
        _save(rows)
    return _public(entry)


def rotate_ingest_key(source_id: int) -> dict | None:
    return update_source(source_id, ingest_key=f"cx_{secrets.token_urlsafe(24)}")


def update_source(source_id: int, **fields) -> dict | None:
    with _LOCK:
        rows = _load()
        s = next((x for x in rows if x["id"] == source_id), None)
        if s is None:
            return None
        s.update({k: v for k, v in fields.items() if v is not None})
        _save(rows)
        return _public(s)


def delete_source(source_id: int) -> bool:
    with _LOCK:
        rows = _load()
        before = len(rows)
        rows = [s for s in rows if s["id"] != source_id]
        _save(rows)
        return len(rows) < before


def ingest_webhook(source_id: int, payload) -> dict:
    """A back-office system pushing data in, rather than us pulling."""
    rows = payload if isinstance(payload, list) else [payload]
    return _store_rows(source_id, rows, "pushed")


# ── fetching ──

def _dig(data, path: str):
    """Walk a dotted path into the response ('data.orders'); '' means the root."""
    for part in filter(None, path.split(".")):
        if isinstance(data, dict):
            data = data.get(part)
        elif isinstance(data, list) and part.isdigit():
            data = data[int(part)]
        else:
            return None
    return data


def _parse_csv(text: str) -> list:
    import csv
    import io
    return list(csv.DictReader(io.StringIO(text)))


def fetch(source_id: int) -> dict:
    """Pull once, store a bounded sample, report honestly what happened."""
    s = get_source(source_id)
    if s is None:
        return {"ok": False, "error": "source not found"}
    headers, params = {}, {}
    if s["auth"] == "bearer" and s.get("secret"):
        headers["Authorization"] = f"Bearer {s['secret']}"
    elif s["auth"] == "header" and s.get("secret"):
        headers[s.get("header_name") or "X-API-Key"] = s["secret"]
    elif s["auth"] == "query" and s.get("secret"):
        params[s.get("header_name") or "api_key"] = s["secret"]

    try:
        r = httpx.get(s["url"], headers=headers, params=params, timeout=45,
                      follow_redirects=True)
        r.raise_for_status()
        if s["kind"] == "sheet_csv" or "csv" in r.headers.get("content-type", ""):
            rows = _parse_csv(r.text)
        else:
            body = r.json()
            picked = _dig(body, s.get("data_path") or "")
            rows = picked if isinstance(picked, list) else [picked or body]
    except Exception as e:  # noqa: BLE001 — a dead POS must be visible, not fatal
        log.warning("source %s fetch failed: %s", source_id, e)
        update_source(source_id, last_sync=datetime.now(timezone.utc).isoformat(),
                      last_status=f"error: {type(e).__name__}: {str(e)[:150]}")
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}

    return _store_rows(source_id, rows, "ok")


def _store_rows(source_id: int, rows: list, status: str) -> dict:
    rows = [r for r in rows if r is not None][:MAX_ROWS]
    update_source(source_id,
                  last_sync=datetime.now(timezone.utc).isoformat(),
                  last_status=status, rows=len(rows),
                  sample=json.dumps(rows, ensure_ascii=False)[:12000])
    return {"ok": True, "rows": len(rows), "preview": rows[:3]}


# ── what the advisors actually read ──

def live_context(project: str | None = None, max_chars: int = 3000) -> str:
    """Digest of every enabled source's latest pull, for the prompt.

    A source reaches a board only if that board is in its linked set, so the
    CEO decides explicitly which feeds an agent reasons from.
    """
    parts = []
    with _LOCK:
        rows = _load()
    for s in rows:
        if not s.get("enabled", True) or not s.get("sample"):
            continue
        if project and project not in _linked(s):
            continue
        head = (f"[ข้อมูลสดจากระบบ: {s['name']} ({KINDS.get(s['kind'], s['kind'])}) "
                f"· โปรเจค {' + '.join(_linked(s)) or 'ทั่วไป'} "
                f"· ดึงเมื่อ {(s.get('last_sync') or '')[:16]}]")
        parts.append(f"{head}\n{s['sample'][:MAX_CHARS]}")
    return "\n\n".join(parts)[:max_chars]
