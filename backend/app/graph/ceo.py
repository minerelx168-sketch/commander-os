"""CEO agent nodes: plan (decompose + route) and synthesize (final report)."""
import json

from ..database import get_sessionmaker
from ..models import AuditLog
from ..services import llm
from .state import CommanderState

CEO_SYSTEM = """คุณคือ AI CEO ของบริษัท ทำหน้าที่:
1. รับคำสั่งจากเจ้าของ (Owner) แล้วแตกเป็นงานย่อย (subtasks)
2. มอบหมายให้แผนกที่เหมาะสม — ตอนนี้มีแผนกเดียว: "cmo" (การตลาด Meta Ads)
3. ตอบเป็น JSON เท่านั้น: {"subtasks": [{"assigned_to": "cmo", "title": "...", "description": "..."}]}

กติกา: งานที่ไม่เกี่ยวกับการตลาด/โฆษณา ให้สร้าง subtask ที่ assigned_to = "cmo" ไม่ได้ —
ให้ตอบ {"subtasks": []} แล้วระบบจะแจ้ง Owner ว่ายังไม่มีแผนกรองรับ"""

CEO_SYNTH_SYSTEM = """คุณคือ AI CEO สรุปผลงานจากแผนกต่างๆ ให้เจ้าของฟัง
- ตอบภาษาไทย กระชับ เป็นรายงานอ่านง่าย ใช้ bullet
- ระบุ: ผลที่ได้, สิ่งที่รออนุมัติ (ถ้ามี), ข้อเสนอแนะถัดไป"""


def _audit(agent: str, task_id: int | None, event: str, detail: dict) -> None:
    SessionLocal = get_sessionmaker()
    with SessionLocal() as db:
        db.add(AuditLog(agent=agent, task_id=task_id, event=event, detail=detail))
        db.commit()


def ceo_plan(state: CommanderState) -> CommanderState:
    SessionLocal = get_sessionmaker()
    with SessionLocal() as db:
        raw = llm.complete(
            db,
            agent="ceo",
            purpose="ceo_plan",
            system=CEO_SYSTEM,
            user=state["user_command"],
            task_id=state.get("task_id"),
        )
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):  # strip markdown fences (Gemini habit)
            cleaned = cleaned.split("```")[1].removeprefix("json").strip()
        plan = json.loads(cleaned).get("subtasks", [])
    except (json.JSONDecodeError, IndexError):
        plan = []
    _audit("ceo", state.get("task_id"), "plan_created", {"subtasks": plan})
    return {"plan": plan}


def ceo_synthesize(state: CommanderState) -> CommanderState:
    results = state.get("department_results", {})
    approval_note = ""
    if state.get("pending_approval_id"):
        decision = state.get("approval_decision") or "pending"
        approval_note = f"\n[การอนุมัติ #{state['pending_approval_id']}: {decision}]"

    SessionLocal = get_sessionmaker()
    with SessionLocal() as db:
        report = llm.complete(
            db,
            agent="ceo",
            purpose="ceo_synthesize",
            system=CEO_SYNTH_SYSTEM,
            user=f"คำสั่งเดิม: {state['user_command']}\n\nผลจากแผนก:\n"
            + json.dumps(results, ensure_ascii=False)
            + approval_note,
            task_id=state.get("task_id"),
        )
    _audit("ceo", state.get("task_id"), "report_created", {"report": report[:500]})
    return {"final_report": report}
