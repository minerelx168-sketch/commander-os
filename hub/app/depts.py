"""C-Suite advisory board — pure strategic consulting, no task automation.

Flow per question (consult_all):
  Round 1  OPINION    — each advisor answers strictly inside their own lane
                        (guardrails) using a forced answer structure.
  Round 2  CROSS-EXAM — each advisor reads the other three opinions and
                        attacks weak assumptions / defends their stance.
  Round 3  VERDICT    — each advisor issues a final one-line ruling
                        (ทำ / ไม่ทำ / ทำแบบมีเงื่อนไข) after the debate.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

import httpx

from . import config, llm, store

log = logging.getLogger("hub.depts")

# ── Guardrails: each C-level may ONLY speak inside their lane ──
LANES = {
    "cmo": ("การตลาด แบรนด์ ลูกค้า ช่องทางขาย และการเติบโตของรายได้",
            "ห้ามออกความเห็นเรื่องสภาพคล่อง โครงสร้างการเงิน กระบวนการปฏิบัติการ หรือสถิติเชิงลึก"),
    "cfo": ("การเงิน สภาพคล่อง ต้นทุน ผลตอบแทน และความเสี่ยงทางการเงิน",
            "ห้ามออกความเห็นเรื่องกลยุทธ์การตลาด ครีเอทีฟ กระบวนการปฏิบัติการ หรือการวิเคราะห์ข้อมูลเชิงเทคนิค"),
    "coo": ("การปฏิบัติการ กระบวนการ ซัพพลายเชน กำลังคน และความเป็นไปได้ในการลงมือทำจริง",
            "ห้ามออกความเห็นเรื่องการตลาด งบการเงิน หรือโมเดลสถิติ"),
    "datalyst": ("ข้อมูล ตัวเลข สถิติ แนวโน้ม และสมมติฐานที่พิสูจน์/หักล้างได้ด้วยข้อมูล",
                 "ห้ามออกความเห็นเชิงกลยุทธ์การตลาด การเงิน หรือการปฏิบัติการ นอกเหนือจากที่ข้อมูลรองรับ"),
}

OPINION_SYSTEM = (
    "คุณคือ {name} ({role}) ที่ปรึกษาเชิงกลยุทธ์ประจำตัว CEO\n"
    "ขอบเขตความเชี่ยวชาญของคุณ: {lane}\n"
    "กฎเหล็ก (guardrail): {guard} — ถ้าคำถามอยู่นอกขอบเขต ให้ตอบสั้นๆ ว่าอยู่นอกความเชี่ยวชาญ\n"
    "ตอบภาษาไทย กระชับ คมคาย ไม่เกิน 8 บรรทัด ใช้โครงสร้างนี้เท่านั้น:\n"
    "มุมมอง/โอกาส: (เห็นพ้องหรือเห็นต่างจากไอเดีย เพราะอะไร)\n"
    "ความเสี่ยงที่ซ่อนอยู่: (จุดบอดที่ CEO อาจมองข้าม — ต้องเฉพาะเจาะจง ห้ามพูดกว้าง)\n"
    "คำแนะนำขั้นเด็ดขาด: (สิ่งที่ควรทำหรือห้ามทำเป็นอันขาด 1 ข้อ)"
)

CROSS_SYSTEM = (
    "คุณคือ {name} ({role}) อยู่ในห้องประชุมบอร์ด ขอบเขตของคุณ: {lane}\n"
    "ด้านล่างคือความเห็นของที่ปรึกษาคนอื่นต่อคำถามเดียวกัน จงวิพากษ์แบบมืออาชีพ:\n"
    "- ชี้สมมติฐานที่อ่อนหรือเพ้อฝันที่สุดในความเห็นของคนอื่น (ระบุชื่อตำแหน่ง)\n"
    "- ถ้าความเห็นคนอื่นขัดกับความเสี่ยงในมุมของคุณ ให้ท้วงทันทีพร้อมเหตุผล\n"
    "- ยอมรับจุดที่คนอื่นถูกและคุณพลาด (ถ้ามี)\n"
    "ตอบภาษาไทย ไม่เกิน 5 บรรทัด ห้ามทวนความเห็นเดิมของตัวเอง"
)

VERDICT_SYSTEM = (
    "คุณคือ {name} ({role}) หลังการถกเถียงในบอร์ดจบลง จงให้คำตัดสินสุดท้ายต่อ CEO\n"
    "ตอบภาษาไทย 2 บรรทัดเท่านั้น:\n"
    "คำตัดสิน: ทำ | ไม่ทำ | ทำแบบมีเงื่อนไข (ระบุเงื่อนไขสั้นๆ)\n"
    "เหตุผลชี้ขาด: (1 ประโยค จากมุม{name}เท่านั้น)"
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


def _dept_provider(dept: str) -> str:
    return store.get_providers().get(dept, "mock")


def _fmt(dept: str, template: str) -> str:
    d = config.DEPTS[dept]
    lane, guard = LANES[dept]
    return template.format(name=d["name"], role=d["role"], lane=lane, guard=guard)


def _round(template: str, build_user) -> dict:
    """Run one board round across all four advisors in parallel."""
    def one(dept: str) -> tuple[str, dict]:
        out = llm.chat(_dept_provider(dept), _fmt(dept, template), build_user(dept))
        return dept, {"text": out["text"], "provider": out["provider"], "ok": out["ok"]}
    with ThreadPoolExecutor(max_workers=4) as ex:
        return dict(ex.map(one, config.DEPTS))


def consult_all(question: str) -> dict:
    # Round 1 — independent opinions inside each lane
    opinions = _round(OPINION_SYSTEM, lambda d: question)

    # Round 2 — cross-examination: each advisor critiques the other three
    def cross_user(dept: str) -> str:
        others = "\n\n".join(
            f"[{config.DEPTS[k]['name']}]\n{v['text']}"
            for k, v in opinions.items() if k != dept and v["ok"]
        )
        return f"คำถามของ CEO: {question}\n\nความเห็นของที่ปรึกษาคนอื่น:\n{others}"
    cross = _round(CROSS_SYSTEM, cross_user)

    # Round 3 — final verdicts after the debate
    def verdict_user(dept: str) -> str:
        debate = "\n".join(
            f"[{config.DEPTS[k]['name']} วิพากษ์] {v['text']}" for k, v in cross.items() if v["ok"]
        )
        return (f"คำถามของ CEO: {question}\n\nความเห็นรอบแรกของคุณ:\n{opinions[dept]['text']}\n\n"
                f"บทถกเถียงในบอร์ด:\n{debate}")
    verdicts = _round(VERDICT_SYSTEM, verdict_user)

    return store.add_consult(question, {
        "opinions": opinions, "cross_exam": cross, "verdicts": verdicts,
    })
