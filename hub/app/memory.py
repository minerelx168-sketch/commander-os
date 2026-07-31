"""Persistent memory — what the board concluded in past sessions.

Two jobs:

  recall()   — hand the Frame stage a digest of earlier rulings on this
               business, so a new session starts from what is already settled
               instead of re-deriving it.
  conflicts() — check the question about to be debated against those rulings
               and surface any that pull the other way. A board that quietly
               reverses itself every quarter is worse than no board.

Both fail closed: with no provider or a malformed reply the pipeline gets an
empty result and the session proceeds, rather than blocking on the audit.
"""
import json
import logging
import re

from . import llm, store

log = logging.getLogger("hub.memory")

DISTIL_SYSTEM = (
    "คุณคือเลขานุการบอร์ดที่บันทึกมติเพื่อให้การประชุมครั้งหน้าอ้างอิงได้\n"
    "หน้าที่: กลั่นการประชุมนี้ให้เหลือแก่นที่ยังมีผลผูกพันในอนาคต\n"
    "กฎเหล็ก: บันทึกเฉพาะสิ่งที่บอร์ดสรุปจริง ห้ามเติมข้อสรุปที่ไม่มีใครพูด\n"
    "ตอบเป็น JSON ล้วนเท่านั้น:\n"
    "{\n"
    '  "conclusion": "มติของการประชุมนี้ในประโยคเดียว",\n'
    '  "stance": "ทำ|ไม่ทำ|ทำแบบมีเงื่อนไข|ยังไม่สรุป",\n'
    '  "confidence": 0-100,\n'
    '  "constraints": ["ข้อผูกมัด/เงื่อนไขที่การตัดสินใจครั้งหน้าต้องเคารพ"],\n'
    '  "open_questions": ["สิ่งที่ยังไม่รู้และต้องหาคำตอบ"],\n'
    '  "tripwires": ["สัญญาณที่ถ้าเกิดขึ้นแปลว่าต้องกลับมาทบทวนมตินี้"]\n'
    "}"
)

CONFLICT_SYSTEM = (
    "คุณคือผู้ตรวจความสอดคล้องของการตัดสินใจ (decision consistency auditor)\n"
    "ด้านล่างคือมติเก่าของบอร์ด และคำถามใหม่ที่กำลังจะถกกัน\n"
    "หน้าที่: หาว่าคำถามใหม่นี้ 'ขัด' หรือ 'ทับซ้อน' กับมติเก่าข้อใดบ้าง\n"
    "กฎเหล็ก:\n"
    "- รายงานเฉพาะที่ขัดกันจริงในเชิงเนื้อหา ห้ามจับคู่เพราะแค่หัวข้อคล้ายกัน\n"
    "- ถ้าไม่มีอะไรขัดกันเลย ให้ตอบ conflicts เป็นลิสต์ว่าง — การไม่เจอถือว่าถูกต้อง\n"
    "- อ้าง memory_id ตามที่ให้มาเท่านั้น ห้ามสร้างเลขใหม่\n"
    "ตอบเป็น JSON ล้วนเท่านั้น:\n"
    "{\n"
    '  "conflicts": [{"memory_id": 1,\n'
    '                 "past": "มติเก่าว่าอย่างไร",\n'
    '                 "tension": "คำถามใหม่ขัดกับมตินั้นตรงไหน",\n'
    '                 "severity": "สูง|กลาง|ต่ำ"}],\n'
    '  "carry_forward": ["ข้อผูกมัดจากมติเก่าที่การประชุมนี้ต้องเคารพ"]\n'
    "}"
)


def _parse_json(text: str) -> dict | None:
    """LLMs like to wrap JSON in prose or fences — dig it out."""
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(cleaned[start:end + 1])
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def recall(project: str | None, limit: int = 8) -> list:
    return store.get_memory(project, limit)


def as_prompt(entries: list, max_chars: int = 2500) -> str:
    """Numbered digest of past rulings; the numbers are the memory ids."""
    if not entries:
        return ""
    lines = []
    for m in entries:
        head = f"[memory #{m['id']} · {(m.get('at') or '')[:10]}] {m.get('question', '')}"
        body = f"  มติ: {m.get('conclusion', '')} (จุดยืน: {m.get('stance', '-')}"
        if m.get("confidence") is not None:
            body += f", ความมั่นใจ {m['confidence']}%"
        body += ")"
        parts = [head, body]
        if m.get("constraints"):
            parts.append("  ข้อผูกมัด: " + "; ".join(m["constraints"][:3]))
        if m.get("tripwires"):
            parts.append("  สัญญาณให้ทบทวน: " + "; ".join(m["tripwires"][:2]))
        lines.append("\n".join(parts))
    return "\n\n".join(lines)[:max_chars]


def conflicts(question: str, project: str | None, provider: str) -> dict:
    """Does this question cut against something the board already settled?"""
    past = recall(project)
    if not past:
        return {"conflicts": [], "carry_forward": [], "checked": 0}
    out = llm.chat(provider, CONFLICT_SYSTEM,
                   f"มติเก่าของบอร์ด:\n{as_prompt(past)}\n\nคำถามใหม่: {question}")
    data = _parse_json(out["text"]) if out["ok"] else None
    if data is None:
        log.warning("conflict check failed for %r", question[:60])
        return {"conflicts": [], "carry_forward": [], "checked": len(past)}
    known = {m["id"] for m in past}
    # drop hallucinated memory ids rather than showing the CEO a dangling ref
    found = [c for c in (data.get("conflicts") or []) if c.get("memory_id") in known]
    return {"conflicts": found,
            "carry_forward": data.get("carry_forward") or [],
            "checked": len(past)}


def remember(session: dict, transcript: str, provider: str) -> dict | None:
    """Distil a finished session into one durable entry. None on failure."""
    out = llm.chat(provider, DISTIL_SYSTEM,
                   f"คำถามของ CEO: {session['question']}\n\nบันทึกการประชุม:\n{transcript}")
    data = _parse_json(out["text"]) if out["ok"] else None
    if data is None or not data.get("conclusion"):
        log.warning("memory distil failed for consult %s", session.get("id"))
        return None
    return store.add_memory({
        "consult_id": session.get("id"),
        "question": session.get("question"),
        "project": session.get("project"),
        "conclusion": data.get("conclusion"),
        "stance": data.get("stance"),
        "confidence": data.get("confidence"),
        "constraints": data.get("constraints") or [],
        "open_questions": data.get("open_questions") or [],
        "tripwires": data.get("tripwires") or [],
    })
