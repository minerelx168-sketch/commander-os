"""Command Center — a lightweight FastAPI dashboard echoing the Sureflow Agentic OS look.

Endpoints:
  GET  /                -> dashboard UI (web/index.html)
  GET  /api/state       -> agent cards + latest report + pending command queue
  POST /api/chat        -> chat with the CMO agent  {"message": "..."}
  POST /api/run         -> trigger a fresh autonomous analysis run
  POST /api/approve     -> mark a queued command approved (in-memory demo)

Run:  uvicorn src.dashboard:app --reload --port 8000
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import agent as cmo_agent
from . import main as engine
from .settings import load_config, resolve

app = FastAPI(title="CMO Command Center")
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# The agent roster from the reference OS. CMO is live; others are scaffolded stubs.
AGENTS = [
    {"name": "CEO", "role": "Command Layer", "icon": "👑", "status": "idle", "live": False},
    {"name": "Researcher", "role": "Intel Gatherer", "icon": "🔎", "status": "idle", "live": False},
    {"name": "CMO", "role": "Market Voice", "icon": "📣", "status": "working", "live": True},
    {"name": "Sales Rep", "role": "Revenue Ops", "icon": "💰", "status": "idle", "live": False},
    {"name": "Dev", "role": "Build System", "icon": "⚙️", "status": "idle", "live": False},
    {"name": "Data Analyst", "role": "Signal Layer", "icon": "📊", "status": "idle", "live": False},
]


class ChatIn(BaseModel):
    message: str


class ApproveIn(BaseModel):
    channel: str
    project: str


def _latest_report() -> str:
    cfg = load_config()
    p = resolve(cfg["paths"]["reports_dir"]) / "latest.md"
    return p.read_text(encoding="utf-8") if p.exists() else "_ยังไม่มีรายงาน — กด Run Analysis_"


def _latest_queue() -> dict:
    cfg = load_config()
    p = resolve(cfg["paths"]["commands_dir"]) / "latest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"commands": [], "summary": {}}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    idx = WEB_DIR / "index.html"
    return idx.read_text(encoding="utf-8")


@app.get("/api/state")
def state() -> JSONResponse:
    return JSONResponse(
        {"agents": AGENTS, "report_md": _latest_report(), "queue": _latest_queue()}
    )


@app.post("/api/chat")
def chat(body: ChatIn) -> JSONResponse:
    return JSONResponse(cmo_agent.chat(body.message))


@app.post("/api/run")
def run() -> JSONResponse:
    result = engine.run()
    return JSONResponse({"ok": True, "run_id": result["run_id"], "report_md": _latest_report(),
                         "queue": _latest_queue()})


@app.post("/api/approve")
def approve(body: ApproveIn) -> JSONResponse:
    # Demo approval gate. A production build would persist status + call the ad-platform adapter.
    return JSONResponse({
        "ok": True,
        "message": f"อนุมัติคำสั่ง {body.project}/{body.channel} แล้ว (demo — ยังไม่ต่อ API แพลตฟอร์มจริง)",
    })
