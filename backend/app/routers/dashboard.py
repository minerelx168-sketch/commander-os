"""Dashboard router — live snapshot API + WebSocket push + kill switch."""
import asyncio
import json
import logging
from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db, get_sessionmaker
from ..models import Agent, Approval, AuditLog, CostEntry, Task

log = logging.getLogger("commander.dashboard")
router = APIRouter(tags=["dashboard"])

# ---- kill switch (in-memory; checked by /api/command) ----
KILL_SWITCH = {"engaged": False}


@router.post("/api/kill-switch")
def toggle_kill_switch(engage: bool) -> dict:
    KILL_SWITCH["engaged"] = engage
    return {"engaged": KILL_SWITCH["engaged"]}


def build_snapshot(db: Session) -> dict:
    today_start = datetime.combine(
        datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc
    )

    agents = db.scalars(select(Agent)).all()
    # derive live status: WORKING if agent has an in-progress task
    active = dict(
        db.execute(
            select(Task.assigned_to, func.count(Task.id))
            .where(Task.status.in_(["pending", "in_progress"]))
            .group_by(Task.assigned_to)
        ).all()
    )
    waiting = dict(
        db.execute(
            select(Approval.agent, func.count(Approval.id))
            .where(Approval.status == "pending")
            .group_by(Approval.agent)
        ).all()
    )
    cost_today = dict(
        db.execute(
            select(CostEntry.agent, func.coalesce(func.sum(CostEntry.cost_thb), 0))
            .where(CostEntry.created_at >= today_start)
            .group_by(CostEntry.agent)
        ).all()
    )

    tasks = db.scalars(select(Task).order_by(Task.id.desc()).limit(15)).all()
    approvals = db.scalars(
        select(Approval).where(Approval.status == "pending").order_by(Approval.id)
    ).all()
    activity = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(20)).all()

    done_today = db.scalar(
        select(func.count(Task.id)).where(Task.status == "done", Task.updated_at >= today_start)
    ) or 0
    total_cost_today = float(sum(float(v) for v in cost_today.values()))

    return {
        "kill_switch": KILL_SWITCH["engaged"],
        "agents": [
            {
                "name": a.name,
                "role": a.role,
                "model": a.model,
                "status": (
                    "WORKING" if active.get(a.name) else
                    "WAITING" if waiting.get(a.name) else "IDLE"
                ),
                "cost_today_thb": round(float(cost_today.get(a.name, 0)), 2),
            }
            for a in agents
        ],
        "tasks": [
            {"id": t.id, "title": t.title, "assigned_to": t.assigned_to, "status": t.status}
            for t in tasks
        ],
        "approvals": [
            {
                "id": ap.id, "agent": ap.agent, "action_type": ap.action_type,
                "risk": ap.risk, "payload": ap.payload,
            }
            for ap in approvals
        ],
        "activity": [
            {
                "id": ev.id, "agent": ev.agent, "event": ev.event,
                "at": ev.created_at.isoformat() if ev.created_at else None,
            }
            for ev in activity
        ],
        "kpi": {"done_today": done_today, "cost_today_thb": round(total_cost_today, 2)},
    }


@router.get("/api/snapshot")
def snapshot(db: Session = Depends(get_db)) -> dict:
    return build_snapshot(db)


@router.websocket("/ws")
async def ws_dashboard(ws: WebSocket) -> None:
    await ws.accept()
    SessionLocal = get_sessionmaker()
    try:
        while True:
            with SessionLocal() as db:
                snap = build_snapshot(db)
            await ws.send_text(json.dumps(snap, ensure_ascii=False))
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        log.warning("ws error: %s", e)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page() -> str:
    from pathlib import Path

    html = Path(__file__).parent.parent / "static" / "dashboard.html"
    return html.read_text(encoding="utf-8")
