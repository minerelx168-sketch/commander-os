"""Owner gate — the single HITL interrupt point, AFTER the boardroom.

By the time execution reaches this node the departments have finished,
debated in the boardroom, and the CEO has ruled. The owner receives ONE
approval card that carries the proposed action plus the board's opinions
and the CEO's ruling — instead of raw per-department pings.
"""
from datetime import datetime, timedelta, timezone

from langgraph.types import interrupt

from ..database import get_sessionmaker
from ..models import Approval, AuditLog
from ..services import meta_ads_client
from .state import CommanderState


def owner_gate(state: CommanderState) -> CommanderState:
    rec = state.get("pending_reco")
    if not rec:
        return {}

    task_id = state.get("task_id")
    board = state.get("boardroom_log") or []
    ceo_ruling = state.get("ceo_decision") or ""

    SessionLocal = get_sessionmaker()
    with SessionLocal() as db:
        # idempotent: on resume LangGraph re-runs this whole node —
        # reuse the approval already created for this task instead of duplicating
        existing = db.query(Approval).filter(
            Approval.task_id == task_id,
            Approval.action_type == "EXECUTE_RECOMMENDATION",
        ).order_by(Approval.id.desc()).first()
        if existing is not None:
            approval_id = existing.id
        else:
            payload = dict(rec)
            payload["board_opinions"] = [
                {"speaker": m.get("speaker"), "message": str(m.get("message", ""))[:300]}
                for m in board
            ]
            payload["ceo_ruling"] = ceo_ruling[:500]
            approval = Approval(
                task_id=task_id,
                agent="ceo",  # the request reaches the owner from the CEO, post-board
                action_type="EXECUTE_RECOMMENDATION",
                payload=payload,
                risk="medium",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            )
            db.add(approval)
            db.commit()
            db.refresh(approval)
            approval_id = approval.id

    # HITL: pause here until owner decides (via Telegram / dashboard)
    decision = interrupt(
        {
            "approval_id": approval_id,
            "action": rec["action"],
            "target": rec["target"],
            "reason": rec["reason"],
            "ceo_ruling": ceo_ruling[:300],
        }
    )

    result: CommanderState = {
        "pending_approval_id": approval_id,
        "approval_decision": decision,
    }
    if decision in ("approve", "reject"):
        # forward to meta-ads-agent — it executes via Meta API (or its own mock).
        # Upstream failures (e.g. 409 = reco already decided in a previous task)
        # must not brick the resume: record the outcome and move on to synthesis.
        try:
            outcome = meta_ads_client.decide_recommendation(rec["id"], decision)
        except Exception as e:  # noqa: BLE001
            outcome = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
        with SessionLocal() as db:
            db.add(AuditLog(agent="ceo", task_id=task_id,
                            event=f"recommendation_{decision}d",
                            detail={"reco_id": rec["id"], "outcome": outcome}))
            db.commit()
    return result
