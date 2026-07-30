"""C-Suite advisory board — pure strategic consulting, no task automation.

A consult advances ONE step at a time so the CEO stays in the loop:

  0 RESEARCH   — an analyst searches the open internet, screens the hits for
                 relevance/credibility/contradiction, and issues a cited brief.
  1 OPINION    — each advisor answers strictly inside their own lane
                 (guardrails) using a forced answer structure.
  2 CROSS-EXAM — each advisor reads the other three opinions and attacks
                 weak assumptions / defends their stance.
  3 VERDICT    — each advisor issues a final one-line ruling.
  4 SYNTHESIS  — the chairman folds the debate into one ruling for the CEO.

Every advisor is grounded in TWO sources of truth: the CEO's own document
library (LINE / upload / Drive) and the screened web brief — so the output is
based on the real business AND the real market, not one of the two.

Between every step the CEO decides: continue, steer with a directive, skip
ahead, stop, rewind (reset) or explore an alternate timeline (branch).
Rejected paths are replayed into the prompt so the board does not repeat an
angle the CEO already turned down.
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from . import config, docs, llm, research, store

log = logging.getLogger("hub.depts")

STEPS = ["research", "opinions", "cross_exam", "verdicts", "synthesis"]
STEP_LABELS = {
    "research": "Round 0 — สืบข้อมูลจากอินเทอร์เน็ต + คัดกรอง",
    "opinions": "Round 1 — ความเห็นในกรอบความเชี่ยวชาญ",
    "cross_exam": "Round 2 — Cross-Examination วิพากษ์กันเอง",
    "verdicts": "Round 3 — คำตัดสินสุดท้ายต่อ CEO",
    "synthesis": "Round 4 — บทสรุปประธานบอร์ด",
}

# ── Guardrails: each C-level may ONLY speak inside their lane ──
LANES = {
    "cmo": ("การตลาด แบรนด์ ลูกค้า ช่องทางขาย และการเติบโตของรายได้",
            "ห้ามออกความเห็นเรื่องสภาพคล่อง โครงสร้างการเงิน กระบวนการปฏิบัติการ หรือสถิติเชิงลึก"),
    "cfo": ("การเงิน สภาพคล่อง ต้นทุน ผลตอบแทน และความเสี่ยงทางการเงิน",
            "ห้ามออกความเห็นเรื่องกลยุทธ์การตลาด ครีเอทีฟ กระบวนการปฏิบัติการ หรือการวิเคราะห์ข้อมูลเชิงเทคนิค"),
    "coo": ("การปฏิบัติการ กระบวนการ ซัพพลายเชน กำลังคน และความเป็นไปได้ในการลงมือทำจริง",
            "ห้ามออกความเห็นเรื่องการตลาด งบการเงิน หรือโมเดลสถิติ"),
    "researcher": ("หลักฐานจากภายนอกองค์กร: ขนาดตลาด คู่แข่ง ราคา กฎระเบียบ พฤติกรรมผู้บริโภค "
                   "และความน่าเชื่อถือของแหล่งข้อมูล",
                   "ห้ามให้ข้อเสนอเชิงกลยุทธ์การตลาด การเงิน หรือการปฏิบัติการ — หน้าที่คุณคือ "
                   "บอกว่า 'หลักฐานพูดว่าอะไร' และ 'หลักฐานยังขาดอะไร' ทุกข้อต้องอ้างแหล่งที่ให้มา "
                   "ถ้าไม่มีแหล่งรองรับต้องเขียนว่า (ไม่มีหลักฐาน) ห้ามเดาแทน"),
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

QUERY_SYSTEM = (
    "คุณคือนักวิจัยตลาดที่ตั้งคำค้นเก่งที่สุด หน้าที่คือแปลงคำถามเชิงกลยุทธ์ของ CEO "
    "เป็นคำค้นหาสำหรับ search engine ที่จะได้ข้อมูลจริงมาใช้ตัดสินใจ\n"
    "ออกแบบคำค้น 4 ข้อ ให้ครอบคลุมมุมต่างกัน เช่น ขนาดตลาด/ตัวเลข, คู่แข่งและราคา, "
    "กฎระเบียบหรือข้อบังคับ, บทเรียนความล้มเหลวของคนที่เคยทำ\n"
    "ถ้าโจทย์เกี่ยวกับไทย ให้ตั้งคำค้นภาษาไทยอย่างน้อย 2 ข้อ และภาษาอังกฤษอย่างน้อย 1 ข้อ\n"
    "ตอบเป็นคำค้นล้วนๆ บรรทัดละ 1 ข้อ ห้ามใส่เลขลำดับ ห้ามอธิบาย ห้ามใส่เครื่องหมายคำพูด"
)

ANALYST_SYSTEM = (
    "คุณคือหัวหน้าฝ่ายวิจัยข้อมูล (Research Analyst) ของ CEO\n"
    "ด้านล่างคือผลค้นหาดิบจากอินเทอร์เน็ต ซึ่งมีทั้งของจริง ของเก่า และของที่เชื่อไม่ได้ "
    "หน้าที่ของคุณคือ **คัดกรอง** ไม่ใช่สรุปทุกอย่างที่เห็น\n"
    "เกณฑ์คัดกรองที่ต้องใช้:\n"
    "- ตัดแหล่งที่เป็นโฆษณา/คอนเทนต์ขายของ/ไม่มีตัวเลขรองรับทิ้ง\n"
    "- ข้อมูลเก่าเกิน 2 ปีให้ระบุปีกำกับเสมอ และเตือนว่าอาจล้าสมัย\n"
    "- ถ้าสองแหล่งขัดแย้งกัน ห้ามเลือกข้างเงียบๆ ต้องบอกว่าขัดกันตรงไหน\n"
    "- ทุกข้อเท็จจริงต้องมีเลขอ้างอิง [n] ตามหมายเลขแหล่งที่ให้มา ห้ามอ้างเลขที่ไม่มีอยู่\n"
    "- ถ้าไม่เจอข้อมูลที่ต้องใช้จริงๆ ให้บอกตรงๆ ว่าไม่เจอ ห้ามเดาหรือแต่งตัวเลขขึ้นเอง\n"
    "ตอบภาษาไทย ใช้โครงสร้างนี้เท่านั้น:\n"
    "ข้อเท็จจริงที่ใช้ตัดสินใจได้: (bullet พร้อมตัวเลขและ [n] — เอาเฉพาะที่เกี่ยวกับโจทย์ตรงๆ)\n"
    "สัญญาณตลาด/คู่แข่ง: (ใครทำอะไรอยู่ ราคาเท่าไร [n])\n"
    "ข้อมูลที่ขัดแย้งกันหรือน่าสงสัย: (ระบุว่าแหล่งไหนขัดกับแหล่งไหน)\n"
    "ช่องว่างข้อมูล: (สิ่งที่ยังไม่รู้และต้องไปหาต่อก่อนตัดสินใจจริง)\n"
    "แหล่งที่เชื่อถือได้: ([n] ชื่อ — URL เฉพาะที่ผ่านการคัดกรอง)"
)

CHAIR_SYSTEM = (
    "คุณคือประธานบอร์ด (Chairman) ทำหน้าที่สรุปการประชุมให้ CEO ตัดสินใจได้ทันที\n"
    "คุณไม่มีวาระของตัวเอง หน้าที่คือชั่งน้ำหนักความเห็นของที่ปรึกษาทั้ง 4 อย่างตรงไปตรงมา\n"
    "ห้ามเสนอความเห็นใหม่ที่ไม่มีใครในบอร์ดพูด และห้ามกลบประเด็นที่บอร์ดยังขัดแย้งกัน\n"
    "ตอบภาษาไทย ใช้โครงสร้างนี้เท่านั้น:\n"
    "มติบอร์ด: ทำ | ไม่ทำ | ทำแบบมีเงื่อนไข (สรุปเป็นประโยคเดียว)\n"
    "ระดับความเห็นพ้อง: เอกฉันท์ | เสียงข้างมาก x-y | บอร์ดแตก (ระบุใครอยู่ฝ่ายไหน)\n"
    "ประเด็นที่ยังขัดแย้ง: (ข้อที่ CEO ต้องชี้ขาดเอง เพราะบอร์ดตกลงกันไม่ได้)\n"
    "สิ่งที่ต้องทำต่อ: (3 ข้อ เรียงตามลำดับ ทำได้จริงภายใน 30 วัน)\n"
    "เงื่อนไขล้มเลิก: (สัญญาณอะไรที่บอกว่าต้องถอย)\n"
    "ถ้ามีผลสืบค้นจากอินเทอร์เน็ตแนบมา ให้อ้างเลข [n] กำกับข้อที่ใช้ตัวเลขจากภายนอก"
)


# ── department service health (cached; surfaced as the online dot in the UI) ──

_HEALTH_TTL = 15.0
_health_cache: dict[str, tuple[float, bool]] = {}


def _svc_get(dept: str, path: str, timeout: float = 2.5) -> dict | None:
    try:
        r = httpx.get(config.DEPTS[dept]["url"] + path, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        log.debug("svc %s%s unreachable: %s", dept, path, e)
        return None


def svc_health(dept: str) -> bool:
    """Is the department's own service reachable? Cached so /api/state stays fast."""
    hit = _health_cache.get(dept)
    if hit and time.monotonic() - hit[0] < _HEALTH_TTL:
        return hit[1]
    ok = any(_svc_get(dept, p) is not None for p in ("/health", "/api/status", "/api/state"))
    _health_cache[dept] = (time.monotonic(), ok)
    return ok


def health_all() -> dict[str, bool]:
    """Probe every department in parallel — one slow service can't stall the page."""
    with ThreadPoolExecutor(max_workers=len(config.DEPTS)) as ex:
        return dict(zip(config.DEPTS, ex.map(svc_health, config.DEPTS)))


# ── prompt assembly ──

def _dept_provider(dept: str) -> str:
    return store.get_providers().get(dept, "mock")


def _chair_provider() -> str:
    """The chairman borrows the first advisor provider that has a working key."""
    assigned = store.get_providers()
    for dept in config.DEPTS:
        p = assigned.get(dept, "mock")
        if p != "mock" and llm.provider_ready(p):
            return p
    return next((p for p in ("anthropic", "gemini", "manus") if llm.provider_ready(p)), "mock")


def _fmt(dept: str, template: str) -> str:
    d = config.DEPTS[dept]
    lane, guard = LANES[dept]
    return template.format(name=d["name"], role=d["role"], lane=lane, guard=guard)


def _rejected_context(session: dict, step: str) -> str:
    """Replay paths the CEO rewound or branched away from, so the board explores
    a genuinely different angle instead of repeating a rejected one."""
    past = [h for h in session.get("history", []) if h["key"] == step]
    if not past:
        return ""
    lines = ["[เส้นทางที่ CEO เคยลองแล้วไม่เอา — ห้ามเสนอซ้ำแนวเดิม ให้หามุมใหม่ที่ต่างจากนี้]"]
    for h in past[-2:]:
        why = "ย้อนกลับมาแก้" if h.get("reason") == "reset" else "แตกกิ่งไปทางอื่น"
        lines.append(f"— ครั้งก่อน ({why}):")
        for key, v in h.get("results", {}).items():
            name = config.DEPTS.get(key, {}).get("name", key)
            lines.append(f"  [{name}] {str(v.get('text', ''))[:400]}")
    return "\n".join(lines)


def _directive_context(directive: str | None) -> str:
    return (f"\n\n[คำสั่งจาก CEO ก่อนเข้ารอบนี้ — ต้องทำตามอย่างเคร่งครัด]\n{directive}"
            if directive else "")


def _step_of(session: dict, key: str) -> dict | None:
    return next((s for s in session["steps"] if s["key"] == key), None)


def _results_of(session: dict, key: str) -> dict:
    s = _step_of(session, key)
    return s["results"] if s else {}


def next_step(session: dict) -> str | None:
    """The next round that has not run yet. Synthesis is terminal — the CEO may
    skip straight to it, and once the chairman has ruled the meeting is over."""
    done = {s["key"] for s in session["steps"]}
    if "synthesis" in done:
        return None
    skip = set() if session.get("web_research", True) else {"research"}
    return next((s for s in STEPS if s not in done and s not in skip), None)


def _research_brief(session: dict) -> str:
    """The screened web brief, as handed to every advisor downstream."""
    step = _step_of(session, "research")
    if not step:
        return ""
    analyst = step["results"].get("analyst", {})
    if not analyst.get("ok") or not analyst.get("text"):
        return ""
    srcs = "\n".join(f"[{i}] {s.get('title', '')} — {s.get('url', '')}"
                     for i, s in enumerate(analyst.get("sources", []), 1))
    return ("[ผลสืบค้นจากอินเทอร์เน็ตที่ผ่านการคัดกรองแล้ว — ใช้อ้างอิงได้ "
            "ถ้าจะเถียงข้อมูลนี้ต้องบอกเหตุผล]\n"
            f"{analyst['text']}\n\nแหล่งอ้างอิง:\n{srcs}")


def _grounding(session: dict) -> str:
    """Both sources of truth: the CEO's own documents + the screened web brief."""
    blocks = []
    knowledge = docs.knowledge_context(project=session.get("project"))
    if knowledge:
        blocks.append("[คลังเอกสารธุรกิจของ CEO — ใช้เป็นบริบทจริง อย่าเดาสวนข้อมูลนี้]\n"
                      + knowledge)
    brief = _research_brief(session)
    if brief:
        blocks.append(brief)
    return "\n\n".join(blocks)


def _round(session_id: int, template: str, build_user) -> dict:
    """Run one board round across every advisor in parallel."""
    def one(dept: str) -> tuple[str, dict]:
        if store.is_stopped(session_id):
            return dept, {"text": "⏹ CEO สั่งหยุดก่อนรอบนี้จบ", "provider": "-", "ok": False}
        out = llm.chat(_dept_provider(dept), _fmt(dept, template), build_user(dept),
                       cancel=lambda: store.is_stopped(session_id))
        return dept, {"text": out["text"], "provider": out["provider"], "ok": out["ok"]}
    with ThreadPoolExecutor(max_workers=len(config.DEPTS)) as ex:
        return dict(ex.map(one, config.DEPTS))


def run_step(session: dict, step: str, directive: str | None = None) -> dict:
    """Execute one board round and return its results keyed by advisor."""
    question = session["question"]
    rejected = _rejected_context(session, step)
    tail = _directive_context(directive) + (f"\n\n{rejected}" if rejected else "")
    sid = session["id"]

    if step == "research":
        return {"analyst": _analyst(session, directive, tail)}

    grounding = _grounding(session)
    ground_block = f"\n\n{grounding}" if grounding else ""

    if step == "opinions":
        return _round(sid, OPINION_SYSTEM, lambda d: question + ground_block + tail)

    if step == "cross_exam":
        opinions = _results_of(session, "opinions")

        def cross_user(dept: str) -> str:
            others = "\n\n".join(
                f"[{config.DEPTS[k]['name']}]\n{v['text']}"
                for k, v in opinions.items() if k != dept and v["ok"]
            )
            return (f"คำถามของ CEO: {question}{ground_block}\n\n"
                    f"ความเห็นของที่ปรึกษาคนอื่น:\n{others}" + tail)
        return _round(sid, CROSS_SYSTEM, cross_user)

    if step == "verdicts":
        opinions, cross = _results_of(session, "opinions"), _results_of(session, "cross_exam")

        def verdict_user(dept: str) -> str:
            debate = "\n".join(f"[{config.DEPTS[k]['name']} วิพากษ์] {v['text']}"
                               for k, v in cross.items() if v["ok"])
            mine = opinions.get(dept, {}).get("text", "(ยังไม่ได้ให้ความเห็นรอบแรก)")
            return (f"คำถามของ CEO: {question}{ground_block}\n\nความเห็นรอบแรกของคุณ:\n{mine}\n\n"
                    f"บทถกเถียงในบอร์ด:\n{debate}" + tail)
        return _round(sid, VERDICT_SYSTEM, verdict_user)

    if step == "synthesis":
        return {"chair": _chairman(session, tail)}

    raise ValueError(f"unknown step: {step}")


def _search_queries(session: dict, directive: str | None) -> list[str]:
    """Let the LLM turn the strategic question into real search queries; fall
    back to the raw question so research still runs without a working key."""
    question = session["question"]
    project = session.get("project")
    ctx = f"คำถามของ CEO: {question}"
    if project:
        ctx += f"\nโปรเจค/ธุรกิจ: {project}"
    if directive:
        ctx += f"\nCEO สั่งให้เน้น: {directive}"
    out = llm.chat(_chair_provider(), QUERY_SYSTEM, ctx)
    if not out["ok"]:
        return [question]
    queries = [ln.strip(" -•\t") for ln in out["text"].splitlines() if ln.strip()]
    queries = [q for q in queries if len(q) > 3][:4]
    return queries or [question]


def _analyst(session: dict, directive: str | None, tail: str) -> dict:
    """Search the internet, then screen the hits into a cited brief."""
    sid = session["id"]
    cancel = lambda: store.is_stopped(sid)  # noqa: E731
    queries = _search_queries(session, directive)
    sources = research.gather(queries, cancel=cancel)
    if not sources:
        return {"text": ("⚠️ ค้นข้อมูลจากอินเทอร์เน็ตไม่สำเร็จ "
                         f"(backend: {research.backend_label()}) — "
                         "บอร์ดจะถกจากคลังเอกสารของคุณอย่างเดียว\n"
                         f"คำค้นที่ลอง: {', '.join(queries)}"),
                "provider": research.backend(), "ok": False,
                "queries": queries, "sources": []}
    out = llm.chat(_chair_provider(), ANALYST_SYSTEM,
                   f"คำถามของ CEO: {session['question']}\n"
                   f"คำค้นที่ใช้: {', '.join(queries)}\n\n"
                   f"ผลค้นหาดิบ:\n{research.as_prompt(sources)}" + tail,
                   cancel=cancel)
    return {"text": out["text"], "provider": f"{out['provider']} · {research.backend_label()}",
            "ok": out["ok"], "queries": queries,
            "sources": [{"title": s.get("title", ""), "url": s.get("url", ""),
                         "query": s.get("query", "")} for s in sources]}


def _chairman(session: dict, tail: str) -> dict:
    """Fold the whole debate into a single ruling the CEO can act on."""
    parts = []
    for key in ("opinions", "cross_exam", "verdicts"):
        results = _results_of(session, key)
        if not results:
            continue
        parts.append(f"## {STEP_LABELS[key]}")
        parts.extend(f"[{config.DEPTS.get(k, {}).get('name', k)}] {v['text']}"
                     for k, v in results.items() if v.get("ok"))
    transcript = "\n".join(parts) or "(บอร์ดยังไม่ได้ถกเถียง)"
    grounding = _grounding(session)
    out = llm.chat(_chair_provider(), CHAIR_SYSTEM,
                   f"คำถามของ CEO: {session['question']}"
                   + (f"\n\n{grounding}" if grounding else "")
                   + f"\n\nบันทึกการประชุม:\n{transcript}" + tail)
    return {"text": out["text"], "provider": out["provider"], "ok": out["ok"]}
