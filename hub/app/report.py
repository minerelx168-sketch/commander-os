"""PDF reports — the audit trail behind every round of the board's debate.

A section report answers "why should I trust this round?": which frameworks
each advisor reasoned with, the numbers they leaned on (as a table and, when
they are comparable, a chart), the assumptions and limits they admitted, and
the documents / web sources each claim traces back to.

The executive summary goes further: it folds what each C-level concluded from
their own lane into a set of concrete options, marks the one the board leans
to, and leaves the CEO a place to record the call.

Neither is invented at render time — extraction passes read the rounds that
actually happened and are told not to introduce a number that is not already
in the text. Results are cached onto the session so re-downloading is free.

Thai typography needs real text shaping: ที่ is ท + ◌ี + ◌่, and without
harfbuzz the tone mark lands on top of the vowel and disappears. fpdf2 with
shaping enabled plus the bundled Sarabun (OFL) font renders it correctly on
any machine with no setup.
"""
import json
import logging
import re
from datetime import datetime, timezone

from fpdf import FPDF
from fpdf.enums import Align, VAlign
from fpdf.fonts import FontFace

from . import config, depts, docs, llm, store

log = logging.getLogger("hub.report")

FONT_DIR = config.ROOT / "assets" / "fonts"
FAMILY = "sarabun"

# Jarvis palette, toned down for paper
INK = (11, 27, 43)
ACCENT = (10, 111, 156)
MUTED = (91, 125, 153)
RULE = (201, 220, 237)
BAND = (238, 245, 251)
WHITE = (255, 255, 255)

PAGE_W, MARGIN = 210, 18          # A4 mm
CONTENT_W = PAGE_W - 2 * MARGIN


# ── document shell ──

class _Doc(FPDF):
    """A4 page with the hub's header rule and a page number in the footer."""

    def __init__(self, subtitle: str):
        super().__init__(format="A4", unit="mm")
        self.subtitle = subtitle
        self.has_thai = False
        self.set_margins(MARGIN, 20, MARGIN)
        self.set_auto_page_break(True, margin=16)
        self._load_fonts()

    def _load_fonts(self) -> None:
        global FAMILY
        try:
            self.add_font(FAMILY, "", str(FONT_DIR / "Sarabun-Regular.ttf"))
            self.add_font(FAMILY, "B", str(FONT_DIR / "Sarabun-Bold.ttf"))
            self.has_thai = True
        except Exception as e:  # noqa: BLE001 — never block a report on a font
            log.warning("Thai font unavailable, Latin fallback: %s", e)
            FAMILY = "helvetica"
        try:
            # the whole point: without shaping, Thai tone marks collide with vowels
            self.set_text_shaping(True)
        except Exception as e:  # noqa: BLE001 — uharfbuzz missing
            log.warning("text shaping unavailable — Thai tone marks may collide: %s", e)

    def header(self) -> None:
        if self.page_no() == 0:
            return
        self.set_font(FAMILY, "B", 7.5)
        self.set_text_color(*ACCENT)
        self.set_xy(MARGIN, 10)
        self.cell(0, 4, "COMMANDER HUB · C-SUITE ADVISORY")
        self.set_font(FAMILY, "", 7.5)
        self.set_text_color(*MUTED)
        self.set_xy(MARGIN, 10)
        self.cell(CONTENT_W, 4, self.subtitle, align="R")
        self.set_draw_color(*RULE)
        self.set_line_width(0.2)
        self.line(MARGIN, 15.5, PAGE_W - MARGIN, 15.5)
        self.set_y(20)

    def footer(self) -> None:
        self.set_y(-13)
        self.set_font(FAMILY, "", 7.5)
        self.set_text_color(*MUTED)
        self.cell(0, 5, f"— {self.page_no()} —", align="C")


# ── text helpers ──

# SARA AM (ำ) is the one Thai vowel harfbuzz splits into two glyphs. fpdf2's
# ToUnicode map cannot describe that 1→2 split, so a PDF built from the composed
# form renders correctly but copies out corrupted. Feeding it pre-decomposed
# keeps every glyph 1:1 with a codepoint: same pixels, and text that survives
# copy-paste and in-file search.
SARA_AM = "ำ"
SARA_AM_DECOMPOSED = "ํา"   # nikhahit + sara aa


def _txt(v) -> str:
    return "" if v is None else str(v).replace(SARA_AM, SARA_AM_DECOMPOSED)


def _h1(pdf: _Doc, text: str) -> None:
    pdf.set_font(FAMILY, "B", 18)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 9, _txt(text), new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")


def _h2(pdf: _Doc, text: str) -> None:
    _need(pdf, 16)
    pdf.ln(3)
    pdf.set_font(FAMILY, "B", 12.5)
    pdf.set_text_color(*ACCENT)
    pdf.multi_cell(0, 7, _txt(text), new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
    pdf.ln(0.5)


def _h3(pdf: _Doc, text: str) -> None:
    _need(pdf, 13)
    pdf.ln(1.5)
    pdf.set_font(FAMILY, "B", 10.5)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 6, _txt(text), new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")


def _body(pdf: _Doc, text: str, size: float = 10) -> None:
    pdf.set_font(FAMILY, "", size)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 5.6, _txt(text), new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")


def _small(pdf: _Doc, text: str) -> None:
    pdf.set_font(FAMILY, "", 8.5)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(0, 4.8, _txt(text), new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
    pdf.set_text_color(*INK)


def _quote(pdf: _Doc, text: str) -> None:
    """Tinted block for anything the CEO said or the board ruled."""
    pdf.set_font(FAMILY, "", 10)
    pdf.set_fill_color(*BAND)
    pdf.set_text_color(*INK)
    pdf.set_draw_color(*ACCENT)
    y0 = pdf.get_y()
    pdf.set_x(MARGIN + 2)
    pdf.multi_cell(CONTENT_W - 2, 5.8, _txt(text), new_x="LMARGIN", new_y="NEXT",
                   fill=True, wrapmode="CHAR")
    pdf.set_line_width(0.6)
    pdf.line(MARGIN + 0.6, y0, MARGIN + 0.6, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(1)


def _bullets(pdf: _Doc, items, empty: str = "—") -> None:
    items = [_txt(x).strip() for x in (items or []) if _txt(x).strip()]
    if not items:
        _small(pdf, empty)
        return
    for x in items:
        pdf.set_font(FAMILY, "", 10)
        pdf.set_text_color(*INK)
        pdf.set_x(MARGIN + 2)
        pdf.multi_cell(CONTENT_W - 2, 5.6, f"•  {x}", new_x="LMARGIN", new_y="NEXT",
                       wrapmode="CHAR")


def _need(pdf: _Doc, height: float) -> None:
    """Push a heading to the next page rather than orphan it at the bottom."""
    if pdf.will_page_break(height):
        pdf.add_page()


def _lines(items) -> str:
    """Bullet list that lives inside one table cell."""
    items = [_txt(x).strip() for x in (items or []) if _txt(x).strip()]
    return "\n".join(f"• {x}" for x in items) if items else "—"


def _table(pdf: _Doc, rows: list[list], widths: list[float], head: bool = True) -> None:
    if not rows:
        return
    pdf.set_font(FAMILY, "", 8.5)
    pdf.set_text_color(*INK)
    pdf.set_draw_color(*RULE)
    with pdf.table(
        col_widths=tuple(widths),
        width=sum(widths),
        line_height=4.8,
        text_align="LEFT",
        v_align=VAlign.T,
        first_row_as_headings=head,
        headings_style=FontFace(emphasis="BOLD", color=WHITE, fill_color=ACCENT),
        cell_fill_color=BAND,
        cell_fill_mode="ROWS" if head else "NONE",
        padding=(1.6, 2.2, 1.6, 2.2),
    ) as table:
        for row in rows:
            r = table.row()
            for cell in row:
                r.cell(_txt(cell))
    pdf.ln(1.5)


def _bar_chart(pdf: _Doc, spec: dict) -> bool:
    """Hand-drawn bars — only when the extractor produced comparable numbers."""
    labels = [_txt(x) for x in (spec.get("labels") or [])]
    try:
        values = [float(v) for v in (spec.get("values") or [])]
    except (TypeError, ValueError):
        return False
    if len(values) < 2 or len(labels) != len(values):
        return False

    title = _txt(spec.get("title"))
    if spec.get("unit"):
        title = f"{title} (หน่วย: {spec['unit']})" if title else f"หน่วย: {spec['unit']}"
    if title:
        pdf.set_font(FAMILY, "B", 9.5)
        pdf.set_text_color(*INK)
        pdf.multi_cell(0, 5.5, title, new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")

    # keep bars clustered instead of smeared across the full width when there
    # are only two or three of them
    height = 40.0
    slot = min(CONTENT_W / len(values), 42.0)
    plot_w = slot * len(values)
    left = MARGIN + (CONTENT_W - plot_w) / 2
    bar_w = max(6.0, min(24.0, slot - 8))

    top = pdf.get_y() + 2
    base = top + height
    ceiling = max(values) or 1

    pdf.set_draw_color(*RULE)
    pdf.line(left, base, left + plot_w, base)
    pdf.set_fill_color(*ACCENT)
    for i, (label, value) in enumerate(zip(labels, values)):
        h = max(0.6, (value / ceiling) * (height - 6))
        cell_x = left + i * slot
        pdf.rect(cell_x + (slot - bar_w) / 2, base - h, bar_w, h, style="F")
        pdf.set_font(FAMILY, "B", 8)
        pdf.set_text_color(*INK)
        pdf.set_xy(cell_x, base - h - 5)
        pdf.cell(slot, 4, f"{value:,.10g}", align="C")
        pdf.set_font(FAMILY, "", 7.5)
        pdf.set_text_color(*MUTED)
        pdf.set_xy(cell_x, base + 1.5)
        pdf.multi_cell(slot, 3.6, label, align="C", wrapmode="CHAR")
    pdf.set_y(base + 11)
    pdf.set_text_color(*INK)
    return True


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ── methodology extraction ──

METHOD_SYSTEM = (
    "คุณคือผู้ตรวจสอบเชิงวิธีวิทยา (methodology auditor) หน้าที่คือถอดว่าที่ปรึกษาแต่ละคน "
    "'คิดด้วยหลักการอะไร' และ 'อ้างข้อมูลอะไร' จากคำตอบที่เกิดขึ้นจริง\n"
    "กฎเหล็ก: ห้ามสร้างตัวเลขหรือหลักการที่ไม่ปรากฏในคำตอบเด็ดขาด "
    "ถ้าที่ปรึกษาไม่ได้อ้างตัวเลขใดเลย ให้ปล่อยตารางว่างและ chart เป็น null "
    "การเดาตัวเลขถือว่าผิดร้ายแรงกว่าการตอบว่าไม่มี\n"
    "ตอบเป็น JSON ล้วนเท่านั้น ห้ามมีข้อความอื่นนอก JSON ตามรูปแบบนี้:\n"
    "{\n"
    '  "principles": ["หลักการ/ทฤษฎี/เฟรมเวิร์กที่ถูกใช้ในรอบนี้โดยรวม"],\n'
    '  "advisors": [{"dept": "cmo|cfo|coo|datalyst",\n'
    '                "frameworks": ["เฟรมเวิร์กที่คนนี้ใช้ เช่น CAC/LTV, unit economics"],\n'
    '                "logic": "ลำดับการให้เหตุผลของคนนี้ 1-2 ประโยค",\n'
    '                "assumptions": ["สมมติฐานที่ตั้งไว้"],\n'
    '                "limitations": ["ข้อจำกัด/จุดที่ยังไม่รู้"],\n'
    '                "citations": ["ที่มาที่อ้าง เช่น เอกสาร:ชื่อไฟล์ หรือ เว็บ:[2]"]}],\n'
    '  "data_table": {"columns": ["ตัวชี้วัด", "ค่า", "หน่วย", "ที่มา"],\n'
    '                 "rows": [["...", "...", "...", "..."]]},\n'
    '  "chart": {"title": "...", "labels": ["..."], "values": [1.0], "unit": "บาท"}\n'
    "}\n"
    "chart ให้ใส่เฉพาะเมื่อมีตัวเลขที่เทียบกันได้จริงตั้งแต่ 2 ค่าขึ้นไปและเป็นหน่วยเดียวกัน "
    "มิฉะนั้นให้เป็น null"
)

OPTIONS_SYSTEM = (
    "คุณคือเลขานุการบอร์ดที่แปลงบทถกเถียงให้กลายเป็น 'ทางเลือกที่กดตัดสินใจได้' สำหรับ CEO\n"
    "หน้าที่คือกลั่นทางเลือกที่บอร์ดพูดถึงจริง 2-4 ทาง ให้ต่างกันชัดเจน (ไม่ใช่ทางเดียวเขียนใหม่ 3 แบบ) "
    "และต้องมีทางที่อนุรักษ์นิยม/ไม่ทำ เป็นหนึ่งในตัวเลือกเสมอถ้าบอร์ดมีใครค้าน\n"
    "กฎเหล็ก: ห้ามเสนอทางเลือกที่ไม่มีใครในบอร์ดพูดถึง และห้ามแต่งตัวเลขที่ไม่ปรากฏในบทถกเถียง\n"
    "สนาม supporters/opponents ให้ใส่เฉพาะ key เหล่านี้: cmo, cfo, coo, datalyst — "
    "อ้างตามที่แต่ละคนแสดงจุดยืนจริงในบทถกเถียง\n"
    "ตอบเป็น JSON ล้วนเท่านั้น ห้ามมีข้อความอื่นนอก JSON:\n"
    "{\n"
    '  "advisor_takeaways": [{"dept": "cmo|cfo|coo|datalyst",\n'
    '                          "headline": "ข้อสรุปของคนนี้ในประโยคเดียว จากมุมความเชี่ยวชาญของเขา",\n'
    '                          "key_risk": "ความเสี่ยงข้อเดียวที่คนนี้ห่วงที่สุด"}],\n'
    '  "options": [{"name": "ชื่อทางเลือกสั้นๆ",\n'
    '               "summary": "ทำอะไรบ้าง 1-2 ประโยค",\n'
    '               "pros": ["ข้อดี"], "cons": ["ข้อเสีย/ความเสี่ยง"],\n'
    '               "supporters": ["cfo"], "opponents": ["cmo"],\n'
    '               "choose_when": "ควรเลือกทางนี้เมื่อ...",\n'
    '               "first_move": "สิ่งแรกที่ต้องทำภายใน 7 วันถ้าเลือกทางนี้"}],\n'
    '  "recommended": "ชื่อทางเลือกที่บอร์ดโน้มไปมากที่สุด (ต้องตรงกับ name ข้างบน)",\n'
    '  "recommended_why": "เหตุผลชี้ขาด 1-2 ประโยค",\n'
    '  "ceo_must_decide": "ประเด็นที่บอร์ดตกลงกันไม่ได้และ CEO ต้องชี้ขาดเอง"\n'
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


def _web_sources(session: dict) -> list:
    step = next((s for s in session["steps"] if s["key"] == "research"), None)
    return (step or {}).get("results", {}).get("analyst", {}).get("sources", []) if step else []


def methodology(session: dict, step_key: str, refresh: bool = False) -> dict:
    """Extract (and cache) how a round was reasoned.

    Returns {} on failure — the report then prints the round without the
    analysis appendix rather than printing something made up.
    """
    step = next((s for s in session["steps"] if s["key"] == step_key), None)
    if step is None:
        return {}
    if not refresh and isinstance(step.get("methodology"), dict) and step["methodology"]:
        return step["methodology"]

    answers = [f"[{key} — {config.DEPTS.get(key, {}).get('name', key)}]\n{val.get('text', '')}"
               for key, val in step["results"].items()]
    if not answers:
        return {}
    sources = "\n".join(f"[{i}] {s.get('title', '')} — {s.get('url', '')}"
                        for i, s in enumerate(_web_sources(session), 1))

    out = llm.chat(depts._chair_provider(), METHOD_SYSTEM,
                   f"คำถามของ CEO: {session['question']}\n"
                   f"รอบที่ตรวจ: {depts.STEP_LABELS.get(step_key, step_key)}\n\n"
                   + "\n\n".join(answers)
                   + (f"\n\nแหล่งเว็บที่บอร์ดมีให้อ้าง:\n{sources}" if sources else ""))
    data = _parse_json(out["text"]) if out["ok"] else None
    if data is None:
        log.warning("methodology extraction failed for consult %s step %s",
                    session.get("id"), step_key)
        return {}
    store.attach_methodology(session["id"], step_key, data)
    return data


def decision_options(session: dict, refresh: bool = False) -> dict:
    """Turn the debate into concrete choices the CEO can act on.

    Returns {} on failure — the summary then omits the options section rather
    than inventing choices nobody on the board argued for.
    """
    if not refresh and isinstance(session.get("options"), dict) and session["options"]:
        return session["options"]

    transcript = []
    for step in session["steps"]:
        if step["key"] == "research":
            continue
        transcript.append(f"## {depts.STEP_LABELS.get(step['key'], step['key'])}")
        for key, val in step["results"].items():
            name = {"chair": "ประธานบอร์ด"}.get(key) or config.DEPTS.get(key, {}).get("name", key)
            expertise = config.DEPTS.get(key, {}).get("expertise", "")
            head = f"[{key} — {name}" + (f" · เชี่ยวชาญ: {expertise}]" if expertise else "]")
            transcript.append(f"{head}\n{val.get('text', '')}")
    if not transcript:
        return {}

    out = llm.chat(depts._chair_provider(), OPTIONS_SYSTEM,
                   f"คำถามของ CEO: {session['question']}\n\n" + "\n\n".join(transcript))
    data = _parse_json(out["text"]) if out["ok"] else None
    if data is None:
        log.warning("decision options failed for consult %s", session.get("id"))
        return {}
    store.attach_options(session["id"], data)
    return data


# ── shared blocks ──

def _names(keys) -> str:
    return ", ".join(config.DEPTS.get(k, {}).get("name", _txt(k)) for k in (keys or [])) or "—"


def _sources_block(pdf: _Doc, session: dict) -> None:
    """Everything the round could legitimately cite: web brief + document library."""
    _h2(pdf, "แหล่งอ้างอิงที่บอร์ดมีให้ใช้")
    web = _web_sources(session)
    if web:
        _h3(pdf, "จากอินเทอร์เน็ต (ผ่านการคัดกรอง)")
        _table(pdf, [["#", "แหล่ง", "URL"]]
               + [[str(i), s.get("title", ""), s.get("url", "")]
                  for i, s in enumerate(web, 1)],
               [10, 62, CONTENT_W - 72])
    library = [d for d in docs.list_documents(200)
               if not session.get("project") or d.get("project") == session.get("project")]
    if library:
        _h3(pdf, "จากคลังเอกสารของ CEO")
        _table(pdf, [["เอกสาร", "โปรเจค", "ที่มา", "วันที่"]]
               + [[d["name"], d.get("project") or "—", d.get("source", ""),
                   (d.get("at") or "")[:10]] for d in library[:25]],
               [70, 34, 26, CONTENT_W - 130])
    if not web and not library:
        _small(pdf, "รอบนี้ไม่มีแหล่งข้อมูลภายนอกแนบมา — ความเห็นตั้งอยู่บนความรู้ของโมเดลล้วน "
                    "ควรตรวจสอบตัวเลขก่อนนำไปใช้จริง")


def _lineage_note(pdf: _Doc, session: dict) -> None:
    if session.get("parent_id"):
        branched = depts.STEP_LABELS.get(session.get("branched_from"), session.get("branched_from"))
        _small(pdf, f"⑂ การประชุมนี้แตกกิ่งมาจาก consult #{session['parent_id']} ที่ {branched} "
                    "— เป็นเส้นทางทางเลือก ไม่ใช่ฉบับเดียวที่มี")


# ── section report (rounds 0–3) ──

def build_step_pdf(session: dict, step_key: str) -> bytes:
    step = next((s for s in session["steps"] if s["key"] == step_key), None)
    if step is None:
        raise ValueError(f"รอบ {step_key} ยังไม่ได้รันในการประชุมนี้")

    label = depts.STEP_LABELS.get(step_key, step_key)
    method = methodology(session, step_key)

    pdf = _Doc(f"consult #{session['id']} · {_stamp()}")
    pdf.set_title(f"{label} — consult #{session['id']}")
    pdf.add_page()

    _h1(pdf, label)
    _small(pdf, f"โจทย์ของ CEO: {session['question']}")
    pdf.ln(2)
    _table(pdf, [["โปรเจค", "สืบข้อมูลเว็บ", "สถานะการประชุม", "รอบนี้รันเมื่อ"],
                 [session.get("project") or "ทุกโปรเจค",
                  "เปิด" if session.get("web_research") else "ปิด",
                  session.get("status", "—"),
                  (step.get("at") or "")[:16].replace("T", " ")]],
           [CONTENT_W * 0.27, CONTENT_W * 0.19, CONTENT_W * 0.24, CONTENT_W * 0.30])
    _lineage_note(pdf, session)
    if step.get("directive"):
        pdf.ln(1)
        _quote(pdf, f"คำสั่งของ CEO ก่อนเข้ารอบนี้: {step['directive']}")

    # 1) principles behind the round
    _h2(pdf, "หลักการและตรรกะที่ใช้ในรอบนี้")
    if method.get("principles"):
        _bullets(pdf, method["principles"])
    elif method:
        _small(pdf, "ไม่พบหลักการที่ระบุชัดในรอบนี้")
    else:
        _small(pdf, "⚠️ ถอดวิธีคิดอัตโนมัติไม่สำเร็จ (provider ไม่พร้อม หรือคืนค่าไม่เป็น JSON) — "
                    "รายงานนี้จึงแสดงเฉพาะเนื้อหาที่บอร์ดตอบจริง "
                    "โดยไม่เติมการวิเคราะห์ที่ไม่ได้เกิดขึ้น")

    # 2) per-advisor reasoning
    advisors = method.get("advisors") or []
    if advisors:
        _h2(pdf, "ตรรกะการคิดรายที่ปรึกษา")
        _table(pdf, [["ที่ปรึกษา", "เฟรมเวิร์ก/หลักการ", "ตรรกะการให้เหตุผล", "สมมติฐาน", "อ้างอิงจาก"]]
               + [[config.DEPTS.get(a.get("dept"), {}).get("name", _txt(a.get("dept"))),
                   _lines(a.get("frameworks")), a.get("logic", "—"),
                   _lines(a.get("assumptions")), _lines(a.get("citations"))]
                  for a in advisors],
               [CONTENT_W * 0.13, CONTENT_W * 0.20, CONTENT_W * 0.28,
                CONTENT_W * 0.20, CONTENT_W * 0.19])
        limits = [f"{config.DEPTS.get(a.get('dept'), {}).get('name', _txt(a.get('dept')))}: {x}"
                  for a in advisors for x in (a.get("limitations") or [])]
        if limits:
            _h3(pdf, "ข้อจำกัดที่ที่ปรึกษายอมรับเอง")
            _bullets(pdf, limits)

    # 3) numbers cited + chart
    dt = method.get("data_table") or {}
    dt_rows = [r for r in (dt.get("rows") or []) if any(_txt(c).strip() for c in r)]
    if dt_rows and dt.get("columns"):
        cols = [_txt(c) for c in dt["columns"]]
        _h2(pdf, "ข้อมูลตัวเลขที่ถูกอ้างถึง")
        _table(pdf, [cols] + [[_txt(c) for c in r] for r in dt_rows],
               [CONTENT_W / len(cols)] * len(cols))
        _small(pdf, "ตัวเลขข้างต้นถอดจากคำตอบของบอร์ดตามที่ปรากฏ ไม่ได้คำนวณเพิ่มโดยระบบ")
    if method.get("chart"):
        _need(pdf, 78)   # heading + plot must land on the same page
        _h2(pdf, "กราฟเปรียบเทียบ")
        if not _bar_chart(pdf, method["chart"]):
            _small(pdf, "ไม่มีตัวเลขที่เทียบกันได้พอจะวาดกราฟ")

    # 4) the round itself, verbatim
    pdf.add_page()
    _h2(pdf, "คำตอบเต็มของรอบนี้")
    for key, val in step["results"].items():
        name = ({"analyst": "ฝ่ายวิจัยข้อมูล", "chair": "ประธานบอร์ด"}.get(key)
                or config.DEPTS.get(key, {}).get("name", key))
        _h3(pdf, f"{name}  ·  {val.get('provider', '')}")
        _body(pdf, val.get("text", ""))
        pdf.ln(1)

    # 5) sources
    pdf.add_page()
    _sources_block(pdf, session)
    return bytes(pdf.output())


# ── executive summary (round 4) ──

def build_executive_summary_pdf(session: dict) -> bytes:
    synth = next((s for s in session["steps"] if s["key"] == "synthesis"), None)
    if synth is None:
        raise ValueError("ยังไม่มีบทสรุปประธาน — รัน Round 4 ก่อน")
    chair = synth["results"].get("chair", {})
    opts = decision_options(session)

    pdf = _Doc(f"EXECUTIVE SUMMARY · consult #{session['id']}")
    pdf.set_title(f"บทสรุปผู้บริหาร — consult #{session['id']}")
    pdf.add_page()

    # cover
    pdf.ln(22)
    pdf.set_font(FAMILY, "B", 26)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 13, _txt("บทสรุปสำหรับผู้บริหาร"), align="C",
                   new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
    pdf.ln(3)
    pdf.set_font(FAMILY, "", 14)
    pdf.set_text_color(*ACCENT)
    pdf.multi_cell(0, 8, _txt(session["question"]), align="C",
                   new_x="LMARGIN", new_y="NEXT", wrapmode="CHAR")
    pdf.ln(10)
    _table(pdf, [["จัดทำเมื่อ", "โปรเจค", "ที่ปรึกษา", "ฐานข้อมูลที่ใช้"],
                 [_stamp(), session.get("project") or "ทุกโปรเจค",
                  "CMO · CFO · COO · Datalyst + ประธานบอร์ด",
                  "คลังเอกสาร" + (" + สืบค้นอินเทอร์เน็ต" if session.get("web_research") else "")]],
           [CONTENT_W * 0.24, CONTENT_W * 0.20, CONTENT_W * 0.30, CONTENT_W * 0.26])
    _lineage_note(pdf, session)
    pdf.ln(2)
    _small(pdf, "เอกสารนี้สรุปผลการประชุมบอร์ดที่ปรึกษาเพื่อประกอบการตัดสินใจของ CEO "
                "วิธีคิดของแต่ละรอบดูได้จากรายงานรายรอบ")

    # the chairman's ruling
    pdf.add_page()
    _h2(pdf, "มติและข้อเสนอของประธานบอร์ด")
    _body(pdf, chair.get("text", ""))

    # what each C-level concluded from their own lane
    takeaways = opts.get("advisor_takeaways") or []
    if takeaways:
        _h2(pdf, "ข้อสรุปจากความเชี่ยวชาญของที่ปรึกษาแต่ละคน")
        _table(pdf, [["ที่ปรึกษา", "เชี่ยวชาญด้าน", "ข้อสรุปของเขา", "ความเสี่ยงที่ห่วงที่สุด"]]
               + [[config.DEPTS.get(t.get("dept"), {}).get("name", _txt(t.get("dept"))),
                   config.DEPTS.get(t.get("dept"), {}).get("expertise", ""),
                   t.get("headline", "—"), t.get("key_risk", "—")]
                  for t in takeaways],
               [CONTENT_W * 0.13, CONTENT_W * 0.27, CONTENT_W * 0.32, CONTENT_W * 0.28])

    # the choices the CEO actually picks between
    options = [o for o in (opts.get("options") or []) if o.get("name")]
    if options:
        recommended = opts.get("recommended")
        _h2(pdf, "ทางเลือกในการตัดสินใจ")
        _table(pdf, [["ทางเลือก", "ทำอะไร", "ข้อดี", "ข้อเสีย/ความเสี่ยง", "หนุน / ค้าน"]]
               + [[("★ " if o["name"] == recommended else "") + _txt(o["name"]),
                   o.get("summary", "—"), _lines(o.get("pros")), _lines(o.get("cons")),
                   f"{_names(o.get('supporters'))}\n/ {_names(o.get('opponents'))}"]
                  for o in options],
               [CONTENT_W * 0.16, CONTENT_W * 0.24, CONTENT_W * 0.21,
                CONTENT_W * 0.21, CONTENT_W * 0.18])

        _h3(pdf, "เลือกทางไหนเมื่อไร และก้าวแรกคืออะไร")
        _table(pdf, [["ทางเลือก", "ควรเลือกเมื่อ", "สิ่งแรกที่ต้องทำใน 7 วัน"]]
               + [[o["name"], o.get("choose_when", "—"), o.get("first_move", "—")]
                  for o in options],
               [CONTENT_W * 0.18, CONTENT_W * 0.42, CONTENT_W * 0.40])

        rec = next((o for o in options if o["name"] == recommended), None)
        if rec:
            _h2(pdf, f"★ ทางที่บอร์ดแนะนำ: {rec['name']}")
            _quote(pdf, opts.get("recommended_why") or rec.get("summary", ""))
        if opts.get("ceo_must_decide"):
            _h3(pdf, "ประเด็นที่ CEO ต้องชี้ขาดเอง")
            _body(pdf, opts["ceo_must_decide"])
            _small(pdf, "บอร์ดตกลงกันไม่ได้ในข้อนี้ — คำแนะนำข้างต้นจึงยังไม่ผูกมัด")

        _h3(pdf, "ช่องบันทึกการตัดสินใจของ CEO")
        _table(pdf, [["ทางเลือกที่เลือก", "เหตุผล", "ลงชื่อ / วันที่"],
                     ["\n\n", "\n\n", "\n\n"]],
               [CONTENT_W * 0.30, CONTENT_W * 0.45, CONTENT_W * 0.25])
    elif opts:
        _small(pdf, "ยังกลั่นทางเลือกไม่ได้จากบทถกเถียงนี้")
    else:
        _small(pdf, "⚠️ สร้างทางเลือกอัตโนมัติไม่สำเร็จ (provider ไม่พร้อม) — "
                    "เอกสารนี้จึงมีเฉพาะมติของประธานบอร์ดตามที่เกิดขึ้นจริง")

    # full verdicts + how the meeting was run
    verdicts = next((s for s in session["steps"] if s["key"] == "verdicts"), None)
    if verdicts:
        pdf.add_page()
        _h2(pdf, "คำตัดสินฉบับเต็มของที่ปรึกษาแต่ละคน")
        _table(pdf, [["ที่ปรึกษา", "ขอบเขตความเชี่ยวชาญ", "คำตัดสิน"]]
               + [[config.DEPTS.get(k, {}).get("name", k),
                   config.DEPTS.get(k, {}).get("expertise", ""), v.get("text", "")]
                  for k, v in verdicts["results"].items()],
               [CONTENT_W * 0.14, CONTENT_W * 0.28, CONTENT_W * 0.58])

    _h2(pdf, "เส้นทางการประชุม")
    _table(pdf, [["รอบ", "เวลา", "คำสั่งของ CEO ก่อนเข้ารอบ"]]
           + [[depts.STEP_LABELS.get(s["key"], s["key"]),
               (s.get("at") or "")[:16].replace("T", " "), s.get("directive") or "—"]
              for s in session["steps"]],
           [CONTENT_W * 0.40, CONTENT_W * 0.22, CONTENT_W * 0.38])
    if session.get("history"):
        _h3(pdf, "เส้นทางที่ CEO ปัดตกระหว่างทาง")
        _bullets(pdf, [
            f"{depts.STEP_LABELS.get(h['key'], h['key'])} — "
            f"{'ย้อนกลับมาแก้' if h.get('reason') == 'reset' else 'แตกกิ่งไปทางอื่น'} "
            f"เมื่อ {(h.get('discarded_at') or '')[:16].replace('T', ' ')}"
            for h in session["history"]])
        _small(pdf, "บอร์ดถูกบอกให้เลี่ยงแนวเดิมเหล่านี้ในรอบถัดมา")

    pdf.add_page()
    _sources_block(pdf, session)
    return bytes(pdf.output())
