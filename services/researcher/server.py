"""Researcher — Evidence Desk service (port 8205).

The other three seats have a command service; the Researcher had none, so the
board showed it permanently offline. This is that service, and it does the one
job the seat exists for: making citations checkable.

It deliberately reuses the hub's ``app.research`` module rather than
re-implementing search — one search stack, one set of backends, one place to fix
a bug. What it adds on top is auditability:

* ``/api/status``   which backend is actually live and whether it needs a key
* ``/api/search``   run a query now and get sources back
* ``/api/verify``   fetch a cited URL and report whether it still resolves, so a
                    ``[n]`` in a deliverable can be checked instead of trusted
* ``/api/summary``  what the hub injects into the Researcher's prompt
* ``/api/ledger``   every query this desk has run, appended to disk

Run: uvicorn server:app --port 8205
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException

ROOT = Path(__file__).resolve().parent
HUB = ROOT.parent.parent / "hub"
sys.path.insert(0, str(HUB))

from app import config, research  # noqa: E402  (needs the path above)

app = FastAPI(title="Researcher — Evidence Desk")

LEDGER = ROOT / "ledger.jsonl"
MAX_LEDGER_REPLY = 50


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log(entry: dict) -> None:
    """Append-only: an evidence trail you can delete but not silently rewrite."""
    entry["at"] = _now()
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _ledger_rows() -> list[dict]:
    if not LEDGER.exists():
        return []
    rows = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue          # a truncated final write must not break the desk
    return rows


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "researcher-evidence-desk"}


@app.get("/api/status")
def status() -> dict:
    live = [name for name, _fn, _label in research.configured()]
    return {
        "backend": research.backend(),
        "backend_label": research.backend_label(),
        "backends": live,
        "searchable": bool(live),
        "paid_backends_configured": live,
        "queries_logged": len(_ledger_rows()),
    }


@app.get("/api/search")
def search(q: str, k: int = 5) -> dict:
    """Run one query now. Never raises — a dead backend returns zero sources
    rather than a 500, same contract the board relies on."""
    if not q.strip():
        raise HTTPException(400, "ต้องระบุคำค้น (q)")
    sources = research.search(q.strip(), k=max(1, min(k, 10)))
    _log({"kind": "search", "query": q.strip(), "backend": research.backend(),
          "hits": len(sources)})
    return {"query": q.strip(), "backend": research.backend_label(),
            "count": len(sources), "sources": sources}


@app.get("/api/verify")
def verify(url: str, chars: int = 400) -> dict:
    """Check that a citation still resolves and carries readable text.

    This is the difference between a footnote and a fact: a [n] nobody can
    open is not evidence. Returns what was actually retrieved, not a verdict.
    """
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "url ต้องเริ่มด้วย http:// หรือ https://")
    text = research.fetch_text(url, max_chars=max(80, min(chars, 4000)))
    ok = bool(text.strip())
    _log({"kind": "verify", "url": url, "resolved": ok, "chars": len(text)})
    return {"url": url, "resolved": ok, "chars": len(text),
            "excerpt": text[:chars],
            "note": "ดึงเนื้อหาได้" if ok else "เปิดไม่ได้หรือไม่มีเนื้อหาอ่านได้ — อย่าใช้อ้างอิง"}


@app.get("/api/summary")
def summary() -> dict:
    """Injected into the Researcher's prompt by the hub, so the seat knows the
    state of its own tools instead of assuming search works."""
    rows = _ledger_rows()
    verified = [r for r in rows if r.get("kind") == "verify"]
    live = [name for name, _fn, _label in research.configured()]
    return {
        "backend": research.backend_label(),
        "queries_run": sum(1 for r in rows if r.get("kind") == "search"),
        "citations_checked": len(verified),
        "citations_broken": sum(1 for r in verified if not r.get("resolved")),
        "note": ("ค้นข้อมูลได้ตามปกติ" if live else
                 "ยังไม่ได้ตั้ง API key สำหรับค้นหา — ค้นเว็บไม่ได้เลย "
                 "ห้ามเดาข้อมูลตลาดหรือคู่แข่ง ต้องรายงานว่ายังไม่มีหลักฐาน"),
    }


@app.get("/api/ledger")
def ledger(limit: int = 20) -> dict:
    rows = _ledger_rows()
    return {"total": len(rows),
            "entries": rows[-max(1, min(limit, MAX_LEDGER_REPLY)):]}
