"""Follow-ups — the CEO replies to a report in Telegram and gets an answer.

A routine report lands on his phone. He wants one thing clarified. Opening the
dashboard to convene a board for that is absurd, so a reply IS the question:
Telegram carries the id of the message being answered, the hub looks up which
run produced it, and the seat that wrote the report answers with that context
plus the project's live data.

Deliberately one shot. A follow-up is not a routine (no schedule, no filing as
a standing report) and not a board session (no debate, no stages) — it is the
CEO asking one advisor one thing and getting a straight answer back in the
same thread.
"""
import logging

from . import config, docs, llm, sources, store, telegram

log = logging.getLogger("hub.followup")

FOLLOWUP_SYSTEM = (
    "คุณคือ {name} ({role}) ที่ปรึกษาประจำตัว CEO\n"
    "ขอบเขตความเชี่ยวชาญของคุณ: {lane}\n"
    "กฎเหล็ก: {guard} — ถ้าคำถามอยู่นอกขอบเขต ให้บอกตรงๆ ว่าอยู่นอกความเชี่ยวชาญ "
    "และระบุว่าใครควรตอบ\n"
    "CEO กำลังตอบกลับรายงานที่คุณเพิ่งส่งไป และถามคำถามเฉพาะเจาะจงหนึ่งข้อ\n"
    "ตอบคำถามนั้นตรงๆ สั้น กระชับ ไม่เกิน 8 บรรทัด ไม่ต้องทวนรายงานเดิม "
    "ไม่ต้องใส่หัวข้อหรือโครงสร้างรายงาน\n"
    "ถ้าข้อมูลที่มีไม่พอจะตอบ ให้บอกว่าไม่พอและระบุว่าต้องใช้ข้อมูลอะไร "
    "ห้ามเดาตัวเลขขึ้นมาเอง"
)


def _seat_of(run: dict, hint: str | None = None) -> str:
    """Who should answer. The report's own seats are the candidates; when the
    CEO names one ('CFO ...') that wins, otherwise the first seat that
    actually produced the report does."""
    seats = [k for k, v in (run.get("results") or {}).items() if v.get("ok")]
    if hint:
        low = hint.lower()
        for key in seats or list(config.DEPTS):
            d = config.DEPTS.get(key, {})
            if key in low or d.get("name", "").lower() in low:
                return key
    return seats[0] if seats else next(iter(config.DEPTS))


def _prompt(dept: str) -> str:
    from .depts import LANES
    d = config.DEPTS[dept]
    lane, guard = LANES.get(dept, ("ธุรกิจโดยรวม", "ตอบเฉพาะสิ่งที่มีหลักฐานรองรับ"))
    return FOLLOWUP_SYSTEM.format(name=d["name"], role=d["role"], lane=lane, guard=guard)


def answer(question: str, run: dict | None, routine: dict | None) -> dict:
    """Answer one follow-up. `run`/`routine` may be None when the CEO messages
    the bot without replying to anything — then it is simply a fresh question
    to the board's default seat, still one shot."""
    dept = _seat_of(run or {}, question)
    project = (routine or {}).get("project")

    ctx = []
    if routine:
        ctx.append(f"[งานประจำที่รายงานไป]\n{routine['task'][:600]}")
    if run:
        mine = (run.get("results") or {}).get(dept, {})
        if mine.get("text"):
            ctx.append(f"[รายงานที่คุณเพิ่งส่งให้ CEO เมื่อ {run.get('at_local', '')}]\n"
                       f"{mine['text'][:1500]}")
        others = [f"[{config.DEPTS.get(k, {}).get('name', k)} รายงานว่า]\n{v['text'][:600]}"
                  for k, v in (run.get("results") or {}).items()
                  if k != dept and v.get("ok") and v.get("text")]
        ctx.extend(others[:2])

    live = sources.live_context(project=project, max_chars=2200)
    if live:
        ctx.append(f"[ข้อมูลสดจากระบบของโปรเจคนี้]\n{live}")
    library = docs.knowledge_context(project=project, max_chars=1200)
    if library:
        ctx.append(f"[คลังเอกสาร]\n{library}")

    ctx.append(f"[คำถามของ CEO]\n{question}")

    out = llm.chat(store.get_providers().get(dept, "mock"), _prompt(dept),
                   "\n\n".join(ctx), max_tokens=2048)
    return {"dept": dept, "text": out["text"], "provider": out["provider"], "ok": out["ok"]}


def handle_update(update: dict) -> dict:
    """Telegram webhook entry point: parse, answer, reply in the same thread."""
    msg = telegram.parse_reply(update)
    if msg is None:
        return {"handled": False, "reason": "no text"}
    if not telegram.from_owner(update):
        log.warning("ignoring telegram message from chat %s", msg.get("chat_id"))
        return {"handled": False, "reason": "not the owner"}

    run, routine = store.find_run_by_message(msg["reply_to"]) if msg["reply_to"] else (None, None)
    linked = run is not None
    if run is None:
        # Either he replied to a report sent before ids were recorded, or he
        # messaged the bot directly. Either way the subject is almost certainly
        # the latest report — answering from a blank slate would be worse.
        run, routine = store.latest_run()

    res = answer(msg["text"], run, routine)

    d = config.DEPTS.get(res["dept"], {})
    header = f"{d.get('icon', '💬')} {d.get('name', res['dept'])} ตอบกลับ"
    if not linked and run:
        header += f" (อ้างอิงรายงานล่าสุด {run.get('at_local', '')})"
    if not res["ok"]:
        header += " ⚠️"
    delivery = telegram.send(f"{header}\n\n{res['text']}", reply_to=msg["message_id"])

    store.add_followup(question=msg["text"], dept=res["dept"], answer=res["text"],
                       routine_id=(routine or {}).get("id"),
                       run_id=(run or {}).get("id"), ok=res["ok"])
    return {"handled": True, "dept": res["dept"], "ok": res["ok"],
            "linked_run": (run or {}).get("id"), "exact_reply": linked,
            "delivery": delivery}
