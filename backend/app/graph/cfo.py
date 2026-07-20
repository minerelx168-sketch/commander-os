"""CFO agent node — finance. Reads real numbers only: cost_entries (LLM spend)
and campaign spend from the CMO's data source. Read-only, no approvals needed.
"""
import json

from sqlalchemy import func, select

from ..database import get_sessionmaker
from ..models import AuditLog, CostEntry
from ..services import llm, meta_ads_client
from .state import CommanderState

CFO_SYSTEM = """คุณคือ AI CFO (การเงิน) วิเคราะห์ตัวเลขที่ได้รับเท่านั้น ห้ามแต่งตัวเลขเอง
- สรุป: ค่าใช้จ่ายโฆษณา, ค่าใช้จ่ายระบบ AI (LLM), ROI/ความคุ้มค่า
- ชี้ความเสี่ยงงบประมาณ + ข้อเสนอแนะ ตอบภาษาไทย กระชับ ใช้ bullet"""


def cfo_work(state: CommanderState) -> CommanderState:
    my_tasks = [t for t in state.get("plan", []) if t["assigned_to"] == "cfo"]
    if not my_tasks:
        return {}

    SessionLocal = get_sessionmaker()
    with SessionLocal() as db:
        llm_costs = [
            {"agent": agent, "cost_thb": float(cost or 0), "calls": int(calls)}
            for agent, cost, calls in db.execute(
                select(
                    CostEntry.agent,
                    func.coalesce(func.sum(CostEntry.cost_thb), 0),
                    func.count(CostEntry.id),
                ).group_by(CostEntry.agent)
            ).all()
        ]
        ads = meta_ads_client.get_dashboard()

        analysis = llm.complete(
            db,
            agent="cfo",
            purpose="cfo_analyze",
            system=CFO_SYSTEM,
            user=(
                f"งาน: {my_tasks[0]['title']}\n"
                f"ค่าใช้จ่าย LLM สะสม (บาท): {json.dumps(llm_costs, ensure_ascii=False)}\n"
                f"แคมเปญโฆษณา: {json.dumps(ads, ensure_ascii=False)}"
            ),
            task_id=state.get("task_id"),
        )
        db.add(AuditLog(agent="cfo", task_id=state.get("task_id"),
                        event="finance_analysis_done", detail={"n_agents": len(llm_costs)}))
        db.commit()

    results = dict(state.get("department_results") or {})
    results["cfo"] = analysis
    return {"department_results": results}
