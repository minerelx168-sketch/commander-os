"""Department client — bridges the hub to each dept service + its assigned AI provider.

consult(): all four C-levels answer the CEO's question in parallel (risk + upside).
run_task(): a dept executes a real task — live data from its service is injected
into the prompt, and each result feeds the dept's learning log (LLM Learning).
"""
import logging
from concurrent.futures import ThreadPoolExecutor

import httpx

from . import config, llm, store

log = logging.getLogger("hub.depts")

CONSULT_SYSTEM = (
    "คุณคือ {name} ({role}) ที่ปรึกษาประจำตัว CEO ความถนัด: {expertise}\n"
    "CEO ถามความเห็น จงตอบเป็นภาษาไทย กระชับ ไม่เกิน 6 บรรทัด ในโครงสร้าง:\n"
    "มุมมอง: (สรุป 1-2 ประโยคจากมุม {name})\n"
    "ผลดี: (bullet สั้น)\n"
    "ความเสี่ยง: (bullet สั้น)\n"
    "คำแนะนำ: (ประโยคเดียว ชัดเจน)"
)

TASK_SYSTEM = (
    "คุณคือ {name} ({role}) ผู้ลงมือทำจริงให้ CEO ความถนัด: {expertise}\n"
    "จงทำงานที่ได้รับมอบหมายให้เสร็จเป็นรูปธรรม ตอบเป็นภาษาไทย มีหัวข้อ: "
    "สิ่งที่ทำ / ผลลัพธ์ / ขั้นถัดไป\n"
    "ข้อมูลสดจากระบบของแผนก:\n{context}\n"
    "บทเรียนจากงานก่อนหน้า (ใช้ปรับปรุงการทำงาน):\n{lessons}"
)


def _svc_get(dept: str, path: str) -> dict | None:
    try:
        r = httpx.get(config.DEPTS[dept]["url"] + path, timeout=8)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        log.debug("svc %s%s unreachable: %s", dept, path, e)
        return None


def svc_health(dept: str) -> bool:
    for path in ("/health", "/api/status", "/api/state"):
        if _svc_get(dept, path) is not None:
            return True
    return False


def _svc_context(dept: str) -> str:
    """Pull live numbers from the dept service to ground the LLM."""
    paths = {"cmo": "/api/state", "coo": "/api/state",
             "cfo": "/api/analysis", "datalyst": "/api/summary"}
    data = _svc_get(dept, paths[dept])
    if data is None:
        return "(service ของแผนกยังไม่ online — ตอบจากความรู้ทั่วไปและระบุว่าไม่มีข้อมูลสด)"
    return str(data)[:4000]


def _dept_provider(dept: str) -> str:
    return store.get_providers().get(dept, "mock")


def consult_one(dept: str, question: str) -> dict:
    d = config.DEPTS[dept]
    system = CONSULT_SYSTEM.format(**d)
    out = llm.chat(_dept_provider(dept), system, question)
    return {"dept": dept, **d, "url": None, **out}


def consult_all(question: str) -> dict:
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(lambda d: consult_one(d, question), config.DEPTS))
    answers = {r["dept"]: {"text": r["text"], "provider": r["provider"], "ok": r["ok"]}
               for r in results}
    return store.add_consult(question, answers)


def run_task(dept: str, command: str) -> dict:
    d = config.DEPTS[dept]
    system = TASK_SYSTEM.format(
        **d, context=_svc_context(dept),
        lessons="\n".join(f"- {x}" for x in store.get_lessons(dept)) or "- (ยังไม่มี)",
    )
    out = llm.chat(_dept_provider(dept), system, command)
    entry = store.add_task(dept, command, out["text"], out["provider"])
    if out["ok"]:
        # LLM Learning: distill a one-line lesson from this task for future runs
        lesson = llm.chat(
            _dept_provider(dept),
            "สรุปบทเรียนจากงานนี้เป็น 1 ประโยคภาษาไทย (สำหรับให้ AI แผนกนี้เก่งขึ้นในงานถัดไป)",
            f"งาน: {command}\nผลลัพธ์: {out['text'][:800]}",
        )
        if lesson["ok"]:
            store.add_lesson(dept, lesson["text"][:200])
    return entry
