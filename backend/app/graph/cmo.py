"""CMO agent node — Meta Ads department. Uses meta-ads-agent as its toolset.

Read/analyze work completes autonomously. A recommendation that would change
the live ad account is NOT sent to the owner here — it's parked in state
(`pending_reco`) so the boardroom can debate it and the CEO can rule first.
The owner_gate node (after the boardroom) owns the single HITL interrupt.
"""
import json

from ..database import get_sessionmaker
from ..models import AuditLog
from ..services import llm, meta_ads_client
from .state import CommanderState

CMO_SYSTEM = """คุณคือ AI CMO (การตลาด) วิเคราะห์ข้อมูล Meta Ads ที่ได้รับ
- สรุปประสิทธิภาพแคมเปญ ชี้จุดที่ต้องปรับ
- ตอบภาษาไทย กระชับ อ้างอิงตัวเลขจากข้อมูลที่ให้เท่านั้น ห้ามแต่งตัวเลขเอง"""


def cmo_work(state: CommanderState) -> CommanderState:
    """Run all subtasks assigned to cmo; park any actionable reco for the board."""
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
        # hold for boardroom debate + CEO ruling — owner sees it once, at the gate
        result["pending_reco"] = recommendations[0]
    return result
