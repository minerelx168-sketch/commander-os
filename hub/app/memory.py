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
import logging

from . import jsonx, llm, store

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
    """LLMs like to wrap JSON in prose or fences — dig it out (see app/jsonx.py)."""
    return jsonx.extract(text)


def _confidence_pct(value) -> int | None:
    """Confidence, normalised to 0-100. A seat that answers `0.7` means 70%, not
    zero — and `int(0.7)` is exactly the rounding that files a confident ruling
    into the archive as no confidence at all."""
    if value is None or value == "":
        return None
    if isinstance(value, float) and 0 < value <= 1:
        return int(round(value * 100))
    score = jsonx.as_int(value)
    return score if score is not None and 0 <= score <= 100 else None


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
    # No `required`: an empty conflicts list is the *correct* answer most of the
    # time, so demanding a non-empty one would buy a repair round on every clean
    # question and pressure the model into inventing a clash.
    out = llm.chat_json(provider, CONFLICT_SYSTEM,
                        f"มติเก่าของบอร์ด:\n{as_prompt(past)}\n\nคำถามใหม่: {question}")
    data = out["data"]
    if data is None:
        log.warning("conflict check failed for %r: %s", question[:60], out["error"])
        return {"conflicts": [], "carry_forward": [], "checked": len(past)}
    known = {m["id"] for m in past}
    # Drop hallucinated memory ids rather than showing the CEO a dangling ref —
    # but read "1", "#1" and 1 as the same id first, or a model that quotes the
    # number as a string has every real citation thrown away as a hallucination.
    found = []
    for c in jsonx.as_list(data.get("conflicts")):
        if not isinstance(c, dict):
            continue
        mid = jsonx.as_int(c.get("memory_id"))
        if mid in known:
            found.append({**c, "memory_id": mid})
    return {"conflicts": found,
            "carry_forward": jsonx.as_str_list(data.get("carry_forward")),
            "checked": len(past)}


def remember(session: dict, transcript: str, provider: str) -> dict | None:
    """Distil a finished session into one durable entry. None on failure."""
    out = llm.chat_json(provider, DISTIL_SYSTEM,
                        f"คำถามของ CEO: {session['question']}\n\n"
                        f"บันทึกการประชุม:\n{transcript}",
                        required=("conclusion",))
    data = out["data"]
    if data is None or not data.get("conclusion"):
        log.warning("memory distil failed for consult %s: %s",
                    session.get("id"), out["error"])
        return None
    return store.add_memory({
        "consult_id": session.get("id"),
        "question": session.get("question"),
        "project": session.get("project"),
        "conclusion": jsonx.as_str(data.get("conclusion")),
        "stance": jsonx.as_str(data.get("stance")) or None,
        "confidence": _confidence_pct(data.get("confidence")),
        "constraints": jsonx.as_str_list(data.get("constraints")),
        "open_questions": jsonx.as_str_list(data.get("open_questions")),
        "tripwires": jsonx.as_str_list(data.get("tripwires")),
    })
