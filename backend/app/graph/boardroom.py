"""Boardroom node — departments discuss each other's results, then the CEO
(Claude Fable 5) makes the final decision. Runs only when 2+ departments
contributed; every utterance lands in audit_log so the dashboard can show
the conversation live.
"""
import json

from ..database import get_sessionmaker
from ..models import AuditLog
from ..services import llm
from .state import CommanderState

DEPT_SYSTEM = {
    "cmo": (
        "คุณคือ AI CMO อยู่ในห้องประชุมบอร์ด แสดงความเห็นต่อผลงานของแผนกอื่น"
        "จากมุมการตลาด/โฆษณา — สั้น ตรงประเด็น 2-3 ประโยค ภาษาไทย"
        " ถ้าเห็นต่างให้บอกเหตุผล ถ้าเห็นด้วยให้เสริมข้อเสนอ"
    ),
    "cfo": (
        "คุณคือ AI CFO อยู่ในห้องประชุมบอร์ด แสดงความเห็นต่อผลงานของแผนกอื่น"
        "จากมุมการเงิน/งบประมาณ/ROI — สั้น ตรงประเด็น 2-3 ประโยค ภาษาไทย"
        " ห้ามแต่งตัวเลขเอง อ้างเฉพาะตัวเลขที่มีในข้อมูล"
    ),
}

CEO_DECIDE_SYSTEM = (
    "คุณคือ AI CEO (Claude Fable 5) ประธานห้องประชุมบอร์ด"
    " อ่านผลงานของทุกแผนกและความเห็นโต้แย้งในที่ประชุม แล้ว 'ตัดสินใจ':"
    " เลือกแนวทาง สรุปเหตุผล และสั่งการขั้นถัดไปให้แต่ละแผนก"
    " ตอบภาษาไทย กระชับ ขึ้นต้นด้วย 'มติ:'"
)


def _audit(agent: str, task_id: int | None, event: str, detail: dict) -> None:
    SessionLocal = get_sessionmaker()
    with SessionLocal() as db:
        db.add(AuditLog(agent=agent, task_id=task_id, event=event, detail=detail))
        db.commit()


def boardroom(state: CommanderState) -> CommanderState:
    results = state.get("department_results") or {}
    if len(results) < 2:  # nothing to debate with one (or zero) voices
        return {}

    task_id = state.get("task_id")
    transcript: list[dict] = []
    SessionLocal = get_sessionmaker()

    # round 1: each department reacts to the OTHERS' results
    for dept in results:
        if dept not in DEPT_SYSTEM:
            continue
        others = {k: v for k, v in results.items() if k != dept}
        with SessionLocal() as db:
            comment = llm.complete(
                db,
                agent=dept,
                purpose=f"boardroom_{dept}",
                system=DEPT_SYSTEM[dept],
                user="ผลงานของแผนกอื่น:\n" + json.dumps(others, ensure_ascii=False),
                task_id=task_id,
            )
        transcript.append({"speaker": dept, "message": comment})
        _audit(dept, task_id, "boardroom_comment", {"message": comment[:500]})

    # CEO reads everything and rules
    with SessionLocal() as db:
        decision = llm.complete(
            db,
            agent="ceo",
            purpose="ceo_decide",
            system=CEO_DECIDE_SYSTEM,
            user=(
                f"คำสั่งเดิม: {state['user_command']}\n\n"
                "ผลจากแผนก:\n" + json.dumps(results, ensure_ascii=False)
                + "\n\nความเห็นในที่ประชุม:\n" + json.dumps(transcript, ensure_ascii=False)
            ),
            task_id=task_id,
        )
    transcript.append({"speaker": "ceo", "message": decision})
    _audit("ceo", task_id, "boardroom_decision", {"message": decision[:500]})

    return {"boardroom_log": transcript, "ceo_decision": decision}
