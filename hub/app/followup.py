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

# Telegram redelivers an update whenever it is unsure we got it. Answering the
# same question twice costs a model call and confuses the thread, so remember
# what we have already handled.
_SEEN: set = set()
_SEEN_MAX = 500

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
    """Who should answer.

    A seat the CEO names outranks everything — he is addressing a person, not
    filing a ticket, and that person may well be one who stayed silent in the
    report (or was never on it). Searching only the report's own seats is what
    made "เรียก COO" land on the CFO.

    With nobody named, prefer a seat that actually contributed to the report.
    """
    if hint:
        low = hint.lower()
        for key, d in config.DEPTS.items():
            names = [key, d.get("name", ""), d.get("role", "")]
            if any(n and n.lower() in low for n in names):
                return key
    seats = [k for k, v in (run.get("results") or {}).items() if v.get("ok")]
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


def accepts(update: dict) -> bool:
    """Is this an update we will act on? Checked before queueing so the
    webhook can reject noise — and repeats — without spawning work."""
    if telegram.parse_reply(update) is None or not telegram.from_owner(update):
        return False
    uid = update.get("update_id")
    if uid is not None:
        if uid in _SEEN:
            log.info("telegram update %s already handled — ignoring repeat", uid)
            return False
        _SEEN.add(uid)
        if len(_SEEN) > _SEEN_MAX:
            _SEEN.clear()
    return True


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
