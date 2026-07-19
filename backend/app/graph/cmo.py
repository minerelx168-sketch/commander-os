"""CMO agent node — Meta Ads department. Uses meta-ads-agent as its toolset.

Read/analyze work completes autonomously. Any recommendation that would change
the live ad account creates an approval record and interrupts the graph (HITL).
"""
import json
from datetime import datetime, timedelta, timezone

from langgraph.types import interrupt

from ..database import get_sessionmaker
from ..models import Approval, AuditLog
from ..services import llm, meta_ads_client
from .state import CommanderState

CMO_SYSTEM = """คุณคือ AI CMO (การตลาด) วิเคราะห์ข้อมูล Meta Ads ที่ได้รับ
- สรุปประสิทธิภาพแคมเปญ ชี้จุดที่ต้องปรับ
- ตอบภาษาไทย กระชับ อ้างอิงตัวเลขจากข้อมูลที่ให้เท่านั้น ห้ามแต่งตัวเลขเอง"""


def cmo_work(state: CommanderState) -> CommanderState:
    """Run all subtasks assigned to cmo; interrupt if an action needs approval."""
    my_tasks = [t for t in state.get("plan", []) if t["assigned_to"] == "cmo"]
    if not my_tasks:
        return {"department_results": {"cmo": "ไม่มีงานที่มอบหมายให้ CMO"}}

    dashboard = meta_ads_client.get_dashboard()
    recommendations = meta_ads_client.get_recommendations(status="PENDING")

    SessionLocal = get_sessionmaker()
    with SessionLocal() as db:
        analysis = llm.complete(
            db,
            agent="cmo",
            purpose="cmo_analyze",
            system=CMO_SYSTEM,
            user=(
                f"งาน: {my_tasks[0]['title']}\n"
                f"Dashboard: {json.dumps(dashboard, ensure_ascii=False)}\n"
                f"Recommendations รอดำเนินการ: {json.dumps(recommendations, ensure_ascii=False)}"
            ),
            task_id=state.get("task_id"),
        )
        db.add(AuditLog(agent="cmo", task_id=state.get("task_id"),
                        event="analysis_done", detail={"n_recs": len(recommendations)}))
        db.commit()

    result: CommanderState = {"department_results": {"cmo": analysis}}

    if recommendations:
        rec = recommendations[0]
        with SessionLocal() as db:
            # idempotent: on resume LangGraph re-runs this whole node —
            # reuse the approval already created for this task instead of duplicating
            existing = db.query(Approval).filter(
                Approval.task_id == state.get("task_id"),
                Approval.action_type == "EXECUTE_RECOMMENDATION",
            ).order_by(Approval.id.desc()).first()
            if existing is not None:
                approval_id = existing.id
            else:
                approval = Approval(
                    task_id=state.get("task_id"),
                    agent="cmo",
                    action_type="EXECUTE_RECOMMENDATION",
                    payload=rec,
                    risk="medium",
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
                )
                db.add(approval)
                db.commit()
                db.refresh(approval)
                approval_id = approval.id

        # HITL: pause here until owner decides (via Telegram / API)
        decision = interrupt(
            {
                "approval_id": approval_id,
                "action": rec["action"],
                "target": rec["target"],
                "reason": rec["reason"],
            }
        )
        result["pending_approval_id"] = approval_id
        result["approval_decision"] = decision
        if decision == "approve" and not _is_mock():
            # forward the approval to meta-ads-agent to actually execute
            pass  # Phase 1: execution happens inside meta-ads-agent's own approval flow

    return result


def _is_mock() -> bool:
    from ..config import get_settings
    return get_settings().meta_agent_mock
