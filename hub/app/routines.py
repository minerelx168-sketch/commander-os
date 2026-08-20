"""Routines — standing orders the board executes on a schedule.

A consult answers one question once. A routine answers the same question every
day/week/month and tells the CEO on Telegram, so drift shows up as a trend
instead of as a surprise.

Design decisions worth keeping:
  * Times are the CEO's wall clock (UTC+7). Storing UTC and converting on
    display invites off-by-one-day bugs at midnight; the schedule is authored,
    read and fired in Bangkok time.
  * Only the seats the CEO assigned answer — a routine is a standing order to
    named people, not a full board session.
  * Every run is filed into the document library, so `Boardroom` can pick a
    routine's accumulated history up as evidence later.
  * The scheduler is a plain background thread with a one-minute tick. No
    external cron: the service already runs under systemd with Restart=always,
    and a missed tick catches up on the next one.
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from . import config, docs, jsonx, llm, pipeline, sources, store, telegram

log = logging.getLogger("hub.routines")

# What is executing this second, so the Pipeline dashboard can tell a seat that
# is thinking from one whose report simply never arrived. Keyed by routine id;
# the value carries which seats are still out.
_LIVE: dict = {}
_LIVE_LOCK = threading.Lock()


def live() -> list:
    """Routines running right now, each with how long it has been going."""
    now = time.monotonic()
    with _LIVE_LOCK:
        entries = list(_LIVE.values())
    return sorted(
        ({k: v for k, v in e.items() if not k.startswith("_")}
         | {"elapsed_ms": int((now - e["_started"]) * 1000)} for e in entries),
        key=lambda e: -e["elapsed_ms"])


def is_running(routine_id: int) -> bool:
    with _LIVE_LOCK:
        return routine_id in _LIVE


def _mark_running(routine: dict, seats: list) -> None:
    with _LIVE_LOCK:
        _LIVE[routine["id"]] = {"routine_id": routine["id"],
                                "task": routine["task"][:80],
                                "seats": list(seats), "pending": list(seats),
                                "_started": time.monotonic()}


def _mark_seat_done(routine_id: int, dept: str) -> None:
    with _LIVE_LOCK:
        e = _LIVE.get(routine_id)
        if e and dept in e["pending"]:
            e["pending"].remove(dept)


def _mark_finished(routine_id: int) -> None:
    with _LIVE_LOCK:
        _LIVE.pop(routine_id, None)

TZ = timezone(timedelta(hours=7))          # UTC+7, the CEO's clock
FREQUENCIES = ("daily", "weekly", "monthly")

ROUTINE_SYSTEM = (
    "คุณคือ {name} ({role}) ที่ปรึกษาประจำตัว CEO\n"
    "ขอบเขตความเชี่ยวชาญของคุณ: {lane}\n"
    "กฎเหล็ก: {guard} — ถ้างานอยู่นอกขอบเขต ให้บอกตรงๆ ว่าอยู่นอกความเชี่ยวชาญ\n"
    "นี่คืองานประจำ (routine) ที่ CEO สั่งไว้ให้รายงานตามรอบเวลา "
    "จงรายงานเฉพาะสิ่งที่เปลี่ยนแปลงและสิ่งที่ต้องตัดสินใจ ไม่ต้องทวนสิ่งที่ CEO รู้อยู่แล้ว\n"
    "ตอบภาษาไทยทั้งหมด\n"
    "- ถ้ามีคำสั่งแก้จาก CEO ที่จุดใด ให้ทำตามให้ครบทุกข้อในรอบนี้ "
    "และรายงานใน fix_responses ว่าแก้อะไรไปบ้าง ข้อไหนทำตามไม่ได้ให้บอกเหตุผลตรงๆ\n"
    "- ห้ามเดาตัวเลข ถ้าไม่มีข้อมูลจริงให้ใส่ไว้ใน unknowns และบอกว่าต้องได้อะไรมาก่อน\n"
)
# NOTE: do not add a line telling the seat that the CEO "will see your chain of
# thought / เส้นทางการคิด". Measured on claude-fable-5: with that sentence the
# API returns stop_reason=refusal 5/5, without it 5/5 succeed — it reads as a
# request to expose internal reasoning. The schema below asks for the same
# structure as ordinary report fields, which the model answers happily.

# The report the CEO reads in Telegram is `answer`; the rest is the path he
# corrects on the Pipeline page. Same trace shape the seat-level runs use, so
# one renderer and one correction flow serve both.
ROUTINE_SCHEMA = pipeline.TASK_SCHEMA


def now() -> datetime:
    return datetime.now(TZ)


# ── schedule maths (pure, unit-testable) ──

def next_run(freq: str, hhmm: str, day: int | None, after: datetime) -> datetime:
    """First fire time strictly after `after`, in UTC+7.

    daily   — every day at hh:mm
    weekly  — `day` = 0..6 (Mon..Sun) at hh:mm
    monthly — `day` = 1..31 at hh:mm; months without that date fire on their
              last day, so a 31st routine never silently skips February.
    """
    hh, mm = (int(x) for x in hhmm.split(":"))
    base = after.astimezone(TZ)
    cand = base.replace(hour=hh, minute=mm, second=0, microsecond=0)

    if freq == "daily":
        return cand if cand > base else cand + timedelta(days=1)

    if freq == "weekly":
        target = 0 if day is None else int(day) % 7
        delta = (target - cand.weekday()) % 7
        cand += timedelta(days=delta)
        return cand if cand > base else cand + timedelta(days=7)

    if freq == "monthly":
        want = 1 if day is None else max(1, min(31, int(day)))
        year, month = cand.year, cand.month
        for _ in range(14):                      # walk forward until it fits
            last = _days_in_month(year, month)
            attempt = cand.replace(year=year, month=month, day=min(want, last))
            if attempt > base:
                return attempt
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)

    raise ValueError(f"unknown frequency: {freq}")


def _days_in_month(year: int, month: int) -> int:
    nxt = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=TZ)
    return (nxt - timedelta(days=1)).day


# ── execution ──

def _seat_prompt(dept: str) -> str:
    from .depts import LANES
    d = config.DEPTS[dept]
    lane, guard = LANES.get(dept, ("ธุรกิจโดยรวม", "ตอบเฉพาะสิ่งที่มีหลักฐานรองรับ"))
    return ROUTINE_SYSTEM.format(name=d["name"], role=d["role"], lane=lane, guard=guard)


def _trace_of(out: dict) -> dict | None:
    """The reasoning path, or None when the seat did not answer in JSON.

    `out` comes from llm.chat_json, which has already parsed and — if the reply
    was nearly right — asked the model to repair it. A model that still writes
    prose has nonetheless reported: the text is kept as the report either way.
    Losing the report to a formatting slip would be far worse than losing the
    flow view for one round.
    """
    if not out.get("ok"):
        return None
    data = out.get("data")
    if not isinstance(data, dict):
        data = jsonx.extract(out.get("text") or "")
    if not isinstance(data, dict):
        return None
    trace = pipeline._normalise(data)
    return trace if trace.get("answer") or trace.get("understanding") else None


def _report_text(out: dict, trace: dict | None) -> str:
    """What the CEO reads in Telegram: the deliverable, not the scaffolding.

    A failed call already carries its error in `text`; passing the raw JSON of a
    half-parsed reply would put braces in his Telegram instead.
    """
    if trace and trace.get("answer"):
        return trace["answer"]
    return out.get("text") or ""


def run_routine(routine: dict) -> dict:
    """Execute one routine now: every assigned seat reports, grounded in the
    CEO's library, in what this same routine said last time, and in whatever
    the CEO marked wrong in that last report."""
    task = routine["task"]
    project = routine.get("project")
    library = docs.knowledge_context(project=project, max_chars=2500)
    live = sources.live_context(project=project, max_chars=2500)
    previous = store.last_routine_run(routine["id"])

    # A routine that asks for numbers nobody sent is the common failure, and
    # three advisors each rediscovering it wastes a round. Say it once, up top.
    if not live and not library:
        note = ("⚠️ ยังไม่มีข้อมูลจากระบบ (API Connector) หรือเอกสารสำหรับ"
                f"{'โปรเจค ' + project if project else 'ขอบเขตนี้'} — "
                "ให้รายงานตรงๆ ว่ายังประเมินไม่ได้ ระบุว่าต้องได้ข้อมูลอะไรบ้าง "
                "และห้ามเดาตัวเลขขึ้นมาเอง")
    else:
        note = ""

    base = [f"งานประจำที่ต้องรายงาน: {task}"]
    if note:
        base.append(note)
    if library:
        base.append(f"[คลังเอกสารธุรกิจของ CEO]\n{library}")
    if live:
        base.append(f"[ข้อมูลสดจากระบบ POS / หลังบ้านของโปรเจคนี้]\n{live}")

    seats = [d for d in routine["seats"] if d in config.DEPTS]

    def prompt_for(dept: str) -> str:
        """This seat's context: shared grounding, its own last report, and the
        corrections the CEO pinned to that report."""
        ctx = list(base)
        prev = ((previous or {}).get("results") or {}).get(dept) or {}
        if prev.get("ok") and prev.get("text"):
            ctx.append(f"[รายงานรอบก่อนของคุณ ({previous['at'][:10]})]\n"
                       f"{prev['text'][:700]}")
        # Other seats' last word, so the board does not contradict itself
        for other, r in ((previous or {}).get("results") or {}).items():
            if other != dept and r.get("ok") and r.get("text"):
                ctx.append(f"[รายงานรอบก่อนของ "
                           f"{config.DEPTS.get(other, {}).get('name', other)}]\n"
                           f"{r['text'][:400]}")

        fixes = store.open_routine_corrections(routine["id"], dept)
        if fixes:
            body = "\n\n".join(
                f"- จุด `{c['node']}` ({c['label']})\n"
                f"  รอบก่อนคุณเขียนว่า: {c['was']}\n"
                f"  CEO สั่งให้แก้เป็น: {c['should']}"
                for c in fixes)
            # Phrased as instructions to follow, not as "the road is closed" —
            # see the note on ROUTINE_SYSTEM about claude-fable-5 refusals.
            ctx.append("[คำสั่งแก้จาก CEO — ต้องทำตามให้ครบทุกข้อในรอบนี้ "
                       "และตอบใน fix_responses ให้ครบทุก node]\n" + body)
        ctx.append(ROUTINE_SCHEMA)
        return "\n\n".join(ctx)

    def one(dept: str) -> tuple[str, dict]:
        # chat_json, not chat: the seat was asked for a schema, and a reply that
        # is nearly-JSON gets one repair round rather than silently degrading
        # into prose the CEO cannot correct node by node.
        #
        # 8192, not 4096: the trace carries the path as well as the answer, and
        # measured on deepseek the same prompt truncates mid-JSON at 4096
        # (1901 chars, truncated=True) but completes at 8192 — a cut trace
        # reaches the CEO as an empty report.
        out = llm.chat_json(store.get_providers().get(dept, "mock"), _seat_prompt(dept),
                            prompt_for(dept), max_tokens=8192,
                            required=("understanding", "answer"))
        _mark_seat_done(routine["id"], dept)
        trace = _trace_of(out)
        return dept, {"text": _report_text(out, trace), "trace": trace,
                      "provider": out["provider"], "ok": out["ok"]}

    # Serially, three seats on slow reasoning models outrun any sane HTTP
    # timeout; they have nothing to say to each other here, so run them at once.
    _mark_running(routine, seats)
    try:
        with ThreadPoolExecutor(max_workers=max(1, len(seats))) as ex:
            results = dict(ex.map(one, seats))
    finally:
        # A crash must clear the marker too, or the dashboard shows a phantom
        # run forever and the CEO cannot tell it from a slow one.
        _mark_finished(routine["id"])

    run = store.add_routine_run(routine["id"], results)
    # Whatever the seats did with them, the corrections reached this run; leaving
    # them open would replay the same instruction every round forever.
    store.answer_routine_corrections(routine["id"], run["id"])
    _deliver(routine, run)
    _file_report(routine, run)
    # _deliver stamps the delivery result on the stored copy; re-read so the
    # caller (and the API) sees whether Telegram actually accepted it.
    return next((x for x in store.get_routine_runs(routine["id"], limit=5)
                 if x["id"] == run["id"]), run)


def _deliver(routine: dict, run: dict) -> None:
    stamp = run["at_local"]
    lines = [f"🔁 Routine: {routine['task'][:120]}", f"🕒 {stamp} (UTC+7)", ""]
    for dept, r in run["results"].items():
        d = config.DEPTS.get(dept, {})
        flag = "" if r["ok"] else " ⚠️ ตอบไม่สำเร็จ"
        lines.append(f"{d.get('icon', '•')} {d.get('name', dept)} [{r['provider']}]{flag}")
        lines.append(r["text"].strip() or "(ไม่มีคำตอบกลับมา)")
        lines.append("")
    lines.append("— ตอบกลับข้อความนี้ (Reply) เพื่อถามที่ปรึกษาต่อได้ทันที")
    res = telegram.send("\n".join(lines))
    store.mark_routine_delivery(routine["id"], run["id"], res)


def _file_report(routine: dict, run: dict) -> None:
    """Persist the run into the document library so the board can cite it."""
    body = [f"# Routine: {routine['task']}",
            f"รอบ: {routine['frequency']} เวลา {routine['time']} (UTC+7)",
            f"รันเมื่อ: {run['at_local']}", ""]
    for dept, r in run["results"].items():
        body.append(f"## {config.DEPTS.get(dept, {}).get('name', dept)} [{r['provider']}]")
        body.append((r.get("text") or "(ไม่มีคำตอบ)").strip())
        body.append("")
    text = "\n".join(body)
    name = f"routine_{routine['id']}_{run['at_local'].replace(':', '').replace(' ', '_')}.md"
    if not any((r.get("text") or "").strip() for r in run["results"].values()):
        # Every seat came back empty. Filing an empty report would put a
        # citable document with nothing in it into the library, and the board
        # would later quote it as evidence.
        log.info("routine %s produced no text; not filing a report", routine["id"])
        return
    try:
        docs.save_document(name, text.encode(), "text/markdown", "routine",
                           text=text, project=routine.get("project"))
    except Exception as e:  # noqa: BLE001 — a filing failure must not lose the run
        log.warning("routine report filing failed: %s", e)


# ── scheduler ──

_THREAD: threading.Thread | None = None
_STOP = threading.Event()


def due_routines(at: datetime | None = None) -> list[dict]:
    at = at or now()
    out = []
    for r in store.get_routines():
        if not r.get("enabled", True) or not r.get("next_at"):
            continue
        if datetime.fromisoformat(r["next_at"]) <= at:
            out.append(r)
    return out


def tick(at: datetime | None = None) -> int:
    """Run everything due and reschedule it. Returns how many ran."""
    at = at or now()
    ran = 0
    for r in due_routines(at):
        try:
            run_routine(r)
        except Exception as e:  # noqa: BLE001 — one bad routine must not stop the rest
            log.exception("routine %s failed", r["id"])
            store.add_routine_run(r["id"], {"_error": {
                "text": f"รันไม่สำเร็จ: {type(e).__name__}: {str(e)[:200]}",
                "provider": "-", "ok": False}})
        store.reschedule_routine(r["id"], next_run(r["frequency"], r["time"], r.get("day"), at))
        ran += 1
    return ran


def _loop() -> None:
    while not _STOP.wait(60):
        try:
            tick()
        except Exception:  # noqa: BLE001
            log.exception("routine tick failed")


def start_scheduler() -> None:
    global _THREAD
    if _THREAD and _THREAD.is_alive():
        return
    _STOP.clear()
    _THREAD = threading.Thread(target=_loop, name="routine-scheduler", daemon=True)
    _THREAD.start()
    log.info("routine scheduler started (UTC+7)")


def scheduler_alive() -> bool:
    return bool(_THREAD and _THREAD.is_alive())
