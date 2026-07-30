"""Departmental deliverables — each C-level's own working document, with the
board's critique of it attached.

The board debates well but produced nothing a CEO could take to a bank, a
supplier, or a team meeting. This module gives every advisor the artefact its
discipline actually hands over:

* **CMO** — market survey, competitor table, brand position, opportunity
  sizing, core metrics, sales forecast. Grounded in the web research round, so
  every claim carries a `[n]` citation back to a real URL.
* **COO** — process diagnostic, the business's core flow, systemisation &
  automation plan, lean waste analysis, quality & risk controls, and the
  performance-measurement cadence.
* **Researcher** — verified findings, source-credibility scoring, market facts,
  contradictions between sources, and an explicit evidence-gap register. It
  reports what the evidence says, never what to do about it.
* **Data Analyst** — key numbers, falsifiable hypotheses, segmentation traps,
  sensitivity ranking, data-quality risks, and the measurement plan.
* **CFO** — see ``finmodel.py``; the finance deliverable is a live Excel model
  rather than a document, so it lives on its own.

One engine renders all of them: a SPEC declares the sections, the section kind
(prose / bullets / table / matrix), and the JSON shape each advisor must fill.
Adding a department is a dict entry, not another renderer.

**Every deliverable ends with a peer-review section.** Every other advisor reads
the document and attacks it from their own lane, then the author responds. The
CEO therefore never receives a departmental claim that the rest of the board has
not already stress-tested — which is the whole point of having a board rather
than five consultants who never meet.
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor

from . import config, depts, docs, llm, report, store

log = logging.getLogger("hub.deliverable")


# ── section kinds ──
#   prose   : {"body": "..."}                        → paragraph
#   bullets : {"items": [...]}                       → bullet list
#   table   : {"columns": [...], "rows": [[...]]}    → table
#   matrix  : {"columns": [...], "rows": [[...]],    → table + optional bar chart
#              "chart": {"labels": [], "values": []}}

CMO_SPEC = {
    "dept": "cmo",
    "title": "เอกสารการตลาด — สำรวจตลาด คู่แข่ง จุดยืนแบรนด์ และประมาณการยอดขาย",
    "intro": ("เอกสารนี้คือของที่ CMO ส่งมอบให้ CEO ใช้ตัดสินใจ ทุกข้อความที่อ้างตัวเลขต้องมี "
              "[n] ชี้กลับไปยังแหล่งอ้างอิงจริงท้ายเอกสาร"),
    "sections": [
        ("market_survey", "1. สำรวจตลาด (Market Survey)", "matrix",
         'ขนาดตลาด/แนวโน้ม/พฤติกรรมลูกค้า เป็นตาราง: columns=["ประเด็น","ตัวเลข/ข้อค้นพบ",'
         '"หน่วย","แหล่งอ้างอิง [n]"] และ chart ถ้าตัวเลขเทียบกันได้'),
        ("competitors", "2. วิเคราะห์คู่แข่ง (Competitor Analysis)", "table",
         'columns=["คู่แข่ง","จุดแข็ง","จุดอ่อน","ราคา/ตำแหน่งตลาด","ภัยคุกคามต่อเรา","แหล่ง [n]"] '
         "อย่างน้อย 3 ราย ถ้าหาไม่ได้ให้บอกตรงๆ ว่าไม่พบข้อมูล"),
        ("brand_position", "3. จุดยืนแบรนด์ (Brand Positioning)", "prose",
         "จุดยืนที่ควรยึด ต่างจากคู่แข่งอย่างไร ใครคือลูกค้าที่ต้องชนะ และ 1 ประโยค positioning statement"),
        ("opportunity", "4. โอกาสทางตลาด (Market Opportunity)", "matrix",
         'ประเมินโอกาสเป็นตาราง: columns=["โอกาส","ขนาด/มูลค่าที่ประเมิน","ความยากในการคว้า",'
         '"เหตุผล + แหล่ง [n]"] เรียงจากคว้าง่ายที่สุด'),
        ("core_metrics", "5. ตัวชี้วัดหลักที่ต้องติดตาม (Core Metrics Tracking)", "table",
         'columns=["ตัวชี้วัด","สูตรคำนวณ","ค่าปัจจุบัน/ประมาณการ","เป้าที่ควรตั้ง","ความถี่ในการวัด"] '
         "ต้องเป็นตัวเลขที่วัดได้จริงจากหลังบ้าน ไม่ใช่นามธรรม"),
        ("sales_forecast", "6. ประมาณการยอดขาย (Sales Forecast)", "matrix",
         'columns=["ช่วงเวลา","Base","Best","Worst","สมมติฐานที่ใช้"] อย่างน้อย 4 ช่วง '
         "(เช่น ไตรมาส) และ chart เทียบ Base ต่อช่วง — ระบุด้วยว่าตัวเลขไหนเป็นการประมาณ"),
        ("actions", "7. สิ่งที่ต้องลงมือใน 30 วัน", "bullets",
         "งานที่ทำได้จริงพร้อมผู้รับผิดชอบและตัวเลขที่จะใช้วัดว่าสำเร็จ"),
    ],
}

COO_SPEC = {
    "dept": "coo",
    "title": "เอกสารปฏิบัติการ — วินิจฉัยกระบวนการ ระบบงาน และการวัดผล",
    "intro": ("เอกสารนี้คือของที่ COO ส่งมอบให้ CEO ใช้ตัดสินใจ เน้นสิ่งที่ทำได้จริงกับกำลังคน "
              "ที่มีอยู่ ไม่ใช่ระบบในฝัน"),
    "sections": [
        ("diagnostic", "1. วินิจฉัยกระบวนการ (Process Diagnostic)", "table",
         'columns=["กระบวนการ","อาการที่พบ","สาเหตุราก (root cause)","ผลกระทบต่อธุรกิจ",'
         '"ความรุนแรง 1-5"] เรียงจากรุนแรงที่สุด'),
        ("core_flow", "2. Core Flow การทำงาน", "table",
         'ลำดับงานหลักตั้งแต่ลูกค้าเข้ามาจนจบ: columns=["ลำดับ","ขั้นตอน","ใครทำ","ใช้เวลา",'
         '"ส่งต่อให้ใคร","จุดที่มักติด"] — ต้องเป็น flow ของธุรกิจนี้จริง ไม่ใช่ flow ทั่วไป'),
        ("systemization", "3. สร้างระบบและนำเทคโนโลยีมาใช้ (Systemization & Automation)", "table",
         'columns=["งานที่ควรทำเป็นระบบ","ทำมือตอนนี้กี่ชั่วโมง/สัปดาห์","เครื่องมือ/วิธีที่แนะนำ",'
         '"ต้นทุนประมาณ","เวลาที่ประหยัดได้","ลำดับความสำคัญ"]'),
        ("lean", "4. เพิ่มประสิทธิภาพและลดความสูญเปล่า (Efficiency & Lean)", "matrix",
         'ความสูญเปล่าตามหลัก Lean: columns=["ประเภทความสูญเปล่า","เกิดที่ไหน","ต้นทุนที่เสียไป",'
         '"วิธีกำจัด"] และ chart เทียบต้นทุนที่เสียไปแต่ละจุด'),
        ("quality_risk", "5. ควบคุมคุณภาพและบริหารความเสี่ยง (Quality & Risk)", "table",
         'columns=["ความเสี่ยง/จุดที่คุณภาพหลุด","โอกาสเกิด","ผลกระทบ","จุดตรวจ (control point)",'
         '"ใครรับผิดชอบ","แผนรับมือ"]'),
        ("performance", "6. วัดผลและปรับปรุงต่อเนื่อง (Performance Measurement)", "table",
         'columns=["ตัวชี้วัดปฏิบัติการ","วิธีเก็บข้อมูล","ค่าปัจจุบัน","เป้า","ความถี่ทบทวน",'
         '"ทำอะไรถ้าไม่ถึงเป้า"]'),
        ("actions", "7. สิ่งที่ต้องลงมือใน 30 วัน", "bullets",
         "งานที่ทำได้จริงพร้อมผู้รับผิดชอบและเกณฑ์ว่าสำเร็จ"),
    ],
}

RESEARCHER_SPEC = {
    "dept": "researcher",
    "title": "เอกสารหลักฐาน — สิ่งที่ค้นพบจากภายนอก ความน่าเชื่อถือ และช่องว่างที่ยังไม่รู้",
    "intro": ("เอกสารนี้คือฐานหลักฐานที่ทุกแผนกใช้อ้างอิงร่วมกัน หน้าที่ของ Researcher คือบอกว่า "
              "'หลักฐานพูดว่าอะไร' และ 'หลักฐานยังขาดอะไร' ไม่ใช่เสนอกลยุทธ์"),
    "sections": [
        ("findings", "1. ข้อค้นพบที่ยืนยันได้ (Verified Findings)", "table",
         'columns=["ข้อค้นพบ","ตัวเลข/ข้อเท็จจริง","แหล่งอ้างอิง [n]","ระดับความเชื่อถือ สูง/กลาง/ต่ำ"] '
         "ใส่เฉพาะข้อที่มีแหล่งรองรับจริง ห้ามใส่สิ่งที่อนุมานเอง"),
        ("source_quality", "2. ประเมินคุณภาพแหล่งข้อมูล (Source Credibility)", "table",
         'columns=["แหล่ง [n]","ประเภท (งานวิจัย/ข่าว/บล็อก/ผู้ขาย)","ความใหม่","อคติที่ควรระวัง",'
         '"ใช้อ้างอิงได้แค่ไหน"] — แหล่งที่เป็นหน้าขายของหรือ SEO ต้องระบุตรงๆ'),
        ("market_facts", "3. ข้อเท็จจริงเชิงตลาดและคู่แข่ง (Market & Competitor Facts)", "matrix",
         'ข้อเท็จจริงที่ตรวจสอบย้อนได้: columns=["ประเด็น","ค่าที่พบ","หน่วย","แหล่ง [n]"] '
         "และ chart ถ้าตัวเลขเทียบกันได้จริง — ห้ามตีความ ให้รายงานตามที่แหล่งบอก"),
        ("contradictions", "4. จุดที่หลักฐานขัดแย้งกันเอง", "table",
         'columns=["ประเด็นที่ขัดแย้ง","แหล่ง A บอกว่า","แหล่ง B บอกว่า","ควรเชื่อทางไหนก่อน เพราะอะไร"] '
         "ถ้าไม่พบความขัดแย้งให้บอกว่าไม่พบ"),
        ("evidence_gaps", "5. ช่องว่างของหลักฐาน (Evidence Gaps)", "table",
         'columns=["สิ่งที่ยังไม่รู้","ทำไมมันสำคัญต่อการตัดสินใจ","หาได้จากไหน","ต้นทุน/เวลาที่ต้องใช้"] '
         "เรียงจากสิ่งที่กระทบการตัดสินใจมากที่สุด"),
        ("verdict", "6. หลักฐานสนับสนุนหรือค้านไอเดียนี้", "prose",
         "สรุปว่าน้ำหนักหลักฐานโดยรวมหนุนหรือค้าน และเชื่อได้แค่ไหน "
         "ถ้าหลักฐานยังไม่พอที่จะตัดสินต้องพูดตรงๆ ว่ายังไม่พอ"),
        ("actions", "7. สิ่งที่ควรไปค้นเพิ่มใน 30 วัน", "bullets",
         "งานค้นคว้าที่เจาะจง ระบุว่าจะได้คำตอบอะไรกลับมาและใช้ตัดสินใจอะไรได้"),
    ],
}

DATALYST_SPEC = {
    "dept": "datalyst",
    "title": "เอกสารวิเคราะห์ข้อมูล — ตัวเลข สมมติฐานที่ทดสอบได้ และระบบวัดผล",
    "intro": ("เอกสารนี้แปลงบทถกเถียงให้เป็นสมมติฐานที่พิสูจน์/หักล้างได้ด้วยข้อมูล "
              "พร้อมบอกว่าต้องเก็บข้อมูลอะไรถึงจะรู้คำตอบ"),
    "sections": [
        ("key_numbers", "1. ตัวเลขชี้เป็นชี้ตาย (Key Numbers)", "matrix",
         'columns=["ตัวเลข","ค่าที่ใช้","ที่มา/วิธีคำนวณ","ความแม่นยำ"] และ chart ถ้าเทียบกันได้ '
         "ตัวเลขที่ประมาณเองต้องกำกับ (ประมาณการ)"),
        ("hypotheses", "2. สมมติฐานที่ทดสอบได้ (Testable Hypotheses)", "table",
         'columns=["สมมติฐาน","ถ้าจริงจะเห็นอะไรในข้อมูล","ถ้าเท็จจะเห็นอะไร","ข้อมูลที่ต้องเก็บ",'
         '"ใช้เวลาทดสอบ"] — ทุกข้อต้องหักล้างได้ ห้ามเขียนสมมติฐานที่พิสูจน์ผิดไม่ได้'),
        ("segmentation", "3. แยกส่วนข้อมูล (Segmentation)", "table",
         'columns=["กลุ่ม/มิติที่ควรแยกดู","ทำไมค่าเฉลี่ยรวมหลอกตา","ข้อมูลที่ต้องมีเพื่อแยก"] '
         "ชี้จุดที่ตัวเลขรวมกำลังซ่อนความจริง"),
        ("sensitivity", "4. ตัวแปรที่อ่อนไหวที่สุด (Sensitivity)", "matrix",
         'columns=["ตัวแปร","เปลี่ยนเท่าไร","ผลลัพธ์เปลี่ยนเท่าไร","ต้องเฝ้าแค่ไหน"] '
         "และ chart จัดอันดับผลกระทบ — บอกว่าตัวไหนพลาดแล้วเจ็บที่สุด"),
        ("data_quality", "5. คุณภาพและความเสี่ยงของข้อมูล", "table",
         'columns=["ข้อมูลที่ใช้","ปัญหาที่พบ (ขาด/เอียง/น้อยเกิน)","ผลต่อข้อสรุป","วิธีแก้"] '
         "รวมถึงกรณีที่ข้อมูลน้อยเกินกว่าจะสรุปได้"),
        ("tracking", "6. ระบบวัดผลที่ต้องตั้ง (Measurement Plan)", "table",
         'columns=["ตัวชี้วัด","สูตร","แหล่งข้อมูล","ความถี่","เกณฑ์เตือนภัย (threshold)",'
         '"ทำอะไรเมื่อแตะเกณฑ์"]'),
        ("actions", "7. สิ่งที่ต้องทำใน 30 วันเพื่อให้วัดผลได้", "bullets",
         "งานตั้งระบบเก็บข้อมูล/แดชบอร์ดที่เจาะจงและทำได้จริง"),
    ],
}

SPECS = {"cmo": CMO_SPEC, "coo": COO_SPEC,
         "researcher": RESEARCHER_SPEC, "datalyst": DATALYST_SPEC}

_KIND_SHAPE = {
    "prose": '{"body": "ข้อความ"}',
    "bullets": '{"items": ["ข้อ 1", "ข้อ 2"]}',
    "table": '{"columns": ["คอลัมน์"], "rows": [["ค่า"]]}',
    "matrix": ('{"columns": ["คอลัมน์"], "rows": [["ค่า"]], '
               '"chart": {"title": "...", "labels": ["a"], "values": [1], "unit": "บาท"}}'),
}


def _author_system(spec: dict) -> str:
    d = config.DEPTS[spec["dept"]]
    lane, guard = depts.LANES[spec["dept"]]
    lines = [
        f"คุณคือ {d['name']} ({d['role']}) กำลังจัดทำเอกสารส่งมอบให้ CEO",
        f"ขอบเขตของคุณ: {lane}",
        f"กฎเหล็ก: {guard}",
        "",
        "กฎความซื่อสัตย์ของข้อมูล (สำคัญกว่าความสวยของเอกสาร):",
        "- ตัวเลขหรือข้อเท็จจริงที่มาจากผลค้นหาเว็บ ต้องใส่ [n] ตามหมายเลขแหล่งที่ให้มา",
        "- ตัวเลขที่คุณประมาณเอง ต้องเขียนกำกับว่า (ประมาณการ) ห้ามใส่ [n] ปลอม",
        "- ถ้าไม่มีข้อมูลจริงสำหรับหัวข้อไหน ให้เขียนว่าไม่พบข้อมูลและบอกว่าต้องไปหาจากไหน",
        "- ห้ามแต่งชื่อคู่แข่ง ชื่อบริษัท หรือสถิติที่ไม่ปรากฏในข้อมูลที่ให้มา",
        "",
        "ตอบเป็น JSON ล้วนเท่านั้น ห้ามมีข้อความอื่นนอก JSON โครงสร้าง:",
        "{",
        '  "headline": "ข้อสรุปของเอกสารนี้ในหนึ่งประโยค",',
        '  "sections": {',
    ]
    for key, label, kind, guide in spec["sections"]:
        lines.append(f'    "{key}": {_KIND_SHAPE[kind]},   // {label} — {guide}')
    lines += ["  },",
              '  "confidence": "สูง|กลาง|ต่ำ — และเพราะอะไร",',
              '  "data_gaps": ["ข้อมูลที่ยังขาดและ CEO ควรไปหาเพิ่ม"]',
              "}"]
    return "\n".join(lines)


CRITIQUE_SYSTEM = (
    "คุณคือ {name} ({role}) ขอบเขตของคุณ: {lane}\n"
    "ด้านล่างคือเอกสารที่ {author} จัดทำเพื่อเสนอ CEO จงวิพากษ์จากมุมความเชี่ยวชาญของคุณ:\n"
    "- ตัวเลขหรือสมมติฐานไหนที่อ่อนที่สุด และมันจะพังตรงไหนในมุมของคุณ\n"
    "- อะไรที่ {author} มองข้ามแล้วกระทบงานด้านคุณโดยตรง\n"
    "- ถ้าเอกสารนี้ดีพอในมุมคุณ ให้บอกตรงๆ ว่าผ่าน และชี้จุดที่ดีที่สุด\n"
    "ตอบภาษาไทย ไม่เกิน 4 บรรทัด ห้ามออกความเห็นนอกขอบเขตของคุณ"
)

RESPONSE_SYSTEM = (
    "คุณคือ {name} ({role}) เจ้าของเอกสาร ที่ปรึกษาคนอื่นวิพากษ์เอกสารของคุณแล้ว\n"
    "จงตอบอย่างมืออาชีพ ภาษาไทย ไม่เกิน 6 บรรทัด ตามโครงนี้:\n"
    "ยอมรับและจะแก้: (ข้อวิจารณ์ที่ถูก และคุณจะแก้เอกสารอย่างไร)\n"
    "ขอยืนยันจุดเดิม: (ข้อที่คุณยังยืนยัน พร้อมเหตุผล)\n"
    "ต้องให้ CEO ชี้ขาด: (ประเด็นที่ตกลงกันไม่ได้ ถ้ามี)"
)


def _sources(session: dict) -> list[dict]:
    step = next((s for s in session.get("steps") or [] if s["key"] == "research"), None)
    return ((step or {}).get("results", {}).get("analyst", {}) or {}).get("sources", []) or []


def _grounding(session: dict) -> str:
    """Everything the author may legitimately cite: the debate, the web brief,
    the document library — and nothing else."""
    parts = [f"คำถามของ CEO: {session['question']}"]

    for step in session.get("steps") or []:
        label = depts.STEP_LABELS.get(step["key"], step["key"])
        for who, val in (step.get("results") or {}).items():
            if not val.get("ok"):
                continue
            name = {"analyst": "ฝ่ายวิจัยข้อมูล", "chair": "ประธานบอร์ด"}.get(
                who, config.DEPTS.get(who, {}).get("name", who))
            parts.append(f"[{label} · {name}]\n{val.get('text', '')}")

    srcs = _sources(session)
    if srcs:
        parts.append("แหล่งอ้างอิงจากอินเทอร์เน็ต — ใช้หมายเลขนี้เป็น [n] ในเอกสาร:\n"
                     + "\n".join(f"[{i}] {s.get('title', '')} — {s.get('url', '')}"
                                 for i, s in enumerate(srcs, 1)))
    else:
        parts.append("(ไม่มีผลค้นหาเว็บในการประชุมนี้ — ห้ามใส่ [n] และต้องกำกับว่า (ประมาณการ) "
                     "ทุกตัวเลขที่คุณเสนอ)")

    knowledge = docs.knowledge_context(project=session.get("project"))
    if knowledge:
        parts.append(f"คลังเอกสารของ CEO:\n{knowledge}")
    return "\n\n".join(parts)


def _peer_review(session: dict, author: str, document: dict) -> dict:
    """The other three advisors attack the document; the author answers."""
    body = json.dumps(document.get("sections", {}), ensure_ascii=False)[:6000]
    author_name = config.DEPTS[author]["name"]
    sid = session["id"]
    cancel = lambda: store.is_stopped(sid)  # noqa: E731

    def one(dept: str) -> tuple[str, dict]:
        lane, _guard = depts.LANES[dept]
        d = config.DEPTS[dept]
        out = llm.chat(
            store.get_providers().get(dept, "mock"),
            CRITIQUE_SYSTEM.format(name=d["name"], role=d["role"], lane=lane,
                                   author=author_name),
            f"หัวข้อ: {document.get('headline', '')}\n\nเนื้อหาเอกสาร (JSON):\n{body}",
            cancel=cancel,
        )
        return dept, {"text": out["text"], "provider": out["provider"], "ok": out["ok"]}

    reviewers = [d for d in config.DEPTS if d != author]
    with ThreadPoolExecutor(max_workers=len(reviewers)) as ex:
        critiques = dict(ex.map(one, reviewers))

    debate = "\n\n".join(f"[{config.DEPTS[k]['name']}]\n{v['text']}"
                         for k, v in critiques.items() if v["ok"])
    d = config.DEPTS[author]
    reply = llm.chat(
        store.get_providers().get(author, "mock"),
        RESPONSE_SYSTEM.format(name=d["name"], role=d["role"]),
        f"เอกสารของคุณ (JSON):\n{body}\n\nข้อวิพากษ์จากบอร์ด:\n{debate}",
        cancel=cancel, max_tokens=4096,
    )
    return {"critiques": critiques,
            "response": {"text": reply["text"], "provider": reply["provider"],
                         "ok": reply["ok"]}}


def build(session: dict, dept: str, refresh: bool = False) -> dict:
    """Author the deliverable, then have the board review it. Cached per dept."""
    spec = SPECS.get(dept)
    if spec is None:
        raise ValueError(f"ไม่มีเอกสารส่งมอบสำหรับแผนก {dept}")

    cached = (session.get("deliverables") or {}).get(dept)
    if not refresh and isinstance(cached, dict) and cached.get("document"):
        return cached

    if not (session.get("steps") or []):
        raise ValueError("ยังไม่มีบทถกเถียง — รันบอร์ดให้ถึงรอบความเห็น (Round 1) ก่อน")

    provider = store.get_providers().get(dept, "mock")
    out = llm.chat(provider, _author_system(spec), _grounding(session),
                   cancel=lambda: store.is_stopped(session["id"]), max_tokens=8192)
    document = report._parse_json(out["text"]) if out["ok"] else None
    if not isinstance(document, dict) or not document.get("sections"):
        log.warning("deliverable %s unusable for consult %s (ok=%s chars=%s)",
                    dept, session.get("id"), out.get("ok"), len(out.get("text") or ""))
        raise ValueError(f"{config.DEPTS[dept]['name']} สร้างเอกสารไม่สำเร็จ — ลองกดสร้างใหม่อีกครั้ง")

    data = {"document": document, "provider": out["provider"],
            "review": _peer_review(session, dept, document)}
    store.attach_deliverable(session["id"], dept, data)
    return data


# ── PDF rendering (reuses the report module's shell so both look alike) ──

def _render_section(pdf, kind: str, payload) -> None:
    if not isinstance(payload, dict):
        report._body(pdf, report._txt(payload) or "—")
        return

    if kind == "prose":
        report._body(pdf, report._txt(payload.get("body")) or "—")
        return

    if kind == "bullets":
        report._bullets(pdf, payload.get("items"))
        return

    rows = [r for r in (payload.get("rows") or []) if isinstance(r, (list, tuple))]
    cols = [report._txt(c) for c in (payload.get("columns") or [])]
    if cols and rows:
        n = len(cols)
        # first column carries the label, so give it more room
        widths = [report.CONTENT_W * (0.26 if n > 2 else 0.4)]
        rest = (report.CONTENT_W - widths[0]) / max(1, n - 1)
        widths += [rest] * (n - 1)
        body = [[report._txt(c) for c in (list(r) + [""] * n)[:n]] for r in rows]
        report._table(pdf, [cols] + body, widths)
    else:
        report._body(pdf, "— ไม่พบข้อมูลสำหรับหัวข้อนี้ —")

    if kind == "matrix" and isinstance(payload.get("chart"), dict):
        report._need(pdf, 58)
        report._bar_chart(pdf, payload["chart"])


def build_pdf(session: dict, dept: str) -> bytes:
    data = build(session, dept)
    spec, document = SPECS[dept], data["document"]
    d = config.DEPTS[dept]

    pdf = report._Doc(f"consult #{session['id']} · {report._stamp()}")
    pdf.set_title(f"{d['name']} — {spec['title']}")
    pdf.add_page()

    report._h1(pdf, f"{d['icon']} {spec['title']}")
    report._small(pdf, f"โจทย์ของ CEO: {session['question']}")
    pdf.ln(1)
    report._table(pdf, [["ผู้จัดทำ", "AI provider", "ความมั่นใจของผู้จัดทำ", "จัดทำเมื่อ"],
                        [f"{d['name']} ({d['role']})", data.get("provider", "—"),
                         report._txt(document.get("confidence")) or "—", report._stamp()]],
                  [report.CONTENT_W * 0.3, report.CONTENT_W * 0.22,
                   report.CONTENT_W * 0.26, report.CONTENT_W * 0.22])
    report._lineage_note(pdf, session)
    if document.get("headline"):
        pdf.ln(1)
        report._quote(pdf, report._txt(document["headline"]))
    report._small(pdf, spec["intro"])

    for key, label, kind, _guide in spec["sections"]:
        report._need(pdf, 30)
        report._h2(pdf, label)
        _render_section(pdf, kind, (document.get("sections") or {}).get(key))

    gaps = document.get("data_gaps")
    if gaps:
        report._need(pdf, 30)
        report._h2(pdf, "ข้อมูลที่ยังขาด — CEO ควรสั่งหาเพิ่มก่อนตัดสินใจ")
        report._bullets(pdf, gaps)

    # the collaboration layer, on paper
    review = data.get("review") or {}
    critiques = review.get("critiques") or {}
    if critiques:
        pdf.add_page()
        report._h1(pdf, "บอร์ดวิพากษ์เอกสารนี้")
        report._small(pdf, f"เอกสารนี้ผ่านการตรวจจากที่ปรึกษาอีก {len(critiques)} คนก่อนถึงมือ CEO — "
                           "แต่ละคนวิจารณ์เฉพาะในขอบเขตความเชี่ยวชาญของตัวเอง")
        for key, val in critiques.items():
            report._need(pdf, 26)
            other = config.DEPTS[key]
            report._h3(pdf, f"{other['icon']} {other['name']} ({other['role']})")
            report._body(pdf, report._txt(val.get("text")) or "—")
        answer = (review.get("response") or {}).get("text")
        if answer:
            report._need(pdf, 30)
            report._h2(pdf, f"คำชี้แจงของ {d['name']} ต่อข้อวิพากษ์")
            report._body(pdf, report._txt(answer))

    report._need(pdf, 40)
    report._sources_block(pdf, session)
    return bytes(pdf.output())
