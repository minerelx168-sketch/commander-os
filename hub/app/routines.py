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
from datetime import datetime, timedelta, timezone

from . import config, docs, llm, sources, store, telegram

log = logging.getLogger("hub.routines")

TZ = timezone(timedelta(hours=7))          # UTC+7, the CEO's clock
FREQUENCIES = ("daily", "weekly", "monthly")

ROUTINE_SYSTEM = (
    "คุณคือ {name} ({role}) ที่ปรึกษาประจำตัว CEO\n"
    "ขอบเขตความเชี่ยวชาญของคุณ: {lane}\n"
    "กฎเหล็ก: {guard} — ถ้างานอยู่นอกขอบเขต ให้บอกตรงๆ ว่าอยู่นอกความเชี่ยวชาญ\n"
    "นี่คืองานประจำ (routine) ที่ CEO สั่งไว้ให้รายงานตามรอบเวลา "
    "จงรายงานเฉพาะสิ่งที่เปลี่ยนแปลงและสิ่งที่ต้องตัดสินใจ ไม่ต้องทวนสิ่งที่ CEO รู้อยู่แล้ว\n"
    "ตอบภาษาไทย ไม่เกิน 10 บรรทัด ใช้โครงสร้างนี้:\n"
    "สถานะ: (สิ่งที่เห็นตอนนี้ในมุมของคุณ)\n"
    "สิ่งที่เปลี่ยน/น่ากังวล: (เจาะจง มีตัวเลขถ้ามี)\n"
    "ต้องตัดสินใจ: (สิ่งที่ CEO ต้องเคาะ หรือ 'ยังไม่มี')"
)


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


def run_routine(routine: dict) -> dict:
    """Execute one routine now: every assigned seat reports, grounded in the
    CEO's library and in what this same routine said last time."""
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

    ctx = [f"งานประจำที่ต้องรายงาน: {task}"]
    if note:
        ctx.append(note)
    if library:
        ctx.append(f"[คลังเอกสารธุรกิจของ CEO]\n{library}")
    if live:
        ctx.append(f"[ข้อมูลสดจากระบบ POS / หลังบ้านของโปรเจคนี้]\n{live}")
    if previous:
        for dept, r in (previous.get("results") or {}).items():
            if r.get("ok"):
                ctx.append(f"[รายงานรอบก่อนของ {config.DEPTS.get(dept, {}).get('name', dept)} "
                           f"({previous['at'][:10]})]\n{r['text'][:700]}")
    user = "\n\n".join(ctx)

    results = {}
    for dept in routine["seats"]:
        if dept not in config.DEPTS:
            continue
        out = llm.chat(store.get_providers().get(dept, "mock"), _seat_prompt(dept), user)
        results[dept] = {"text": out["text"], "provider": out["provider"], "ok": out["ok"]}

    run = store.add_routine_run(routine["id"], results)
    _deliver(routine, run)
    _file_report(routine, run)
    # _deliver stamps the delivery result on the stored copy; re-read so the
    # caller (and the API) sees whether Telegram actually accepted it.
    return next((x for x in store.get_routine_runs(routine["id"], limit=5)
                 if x["id"] == run["id"]), run)


def _deliver(routine: dict, run: dict) -> None:
    stamp = run["at_local"]
    lines = [f"🔁 Routine: {routine['task']}", f"🕒 {stamp} (UTC+7)", ""]
    for dept, r in run["results"].items():
        d = config.DEPTS.get(dept, {})
        lines.append(f"{d.get('icon', '•')} {d.get('name', dept)} [{r['provider']}]")
        lines.append(r["text"].strip())
        lines.append("")
    lines.append("— นำผลสะสมไปให้ Boardroom ถกต่อได้จากหน้า เอกสาร")
    res = telegram.send("\n".join(lines))
    store.mark_routine_delivery(routine["id"], run["id"], res)


def _file_report(routine: dict, run: dict) -> None:
    """Persist the run into the document library so the board can cite it."""
    body = [f"# Routine: {routine['task']}",
            f"รอบ: {routine['frequency']} เวลา {routine['time']} (UTC+7)",
            f"รันเมื่อ: {run['at_local']}", ""]
    for dept, r in run["results"].items():
        body.append(f"## {config.DEPTS.get(dept, {}).get('name', dept)} [{r['provider']}]")
        body.append(r["text"].strip())
        body.append("")
    text = "\n".join(body)
    name = f"routine_{routine['id']}_{run['at_local'].replace(':', '').replace(' ', '_')}.md"
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
