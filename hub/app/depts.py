"""The Crucible pipeline — an adversarial braintrust, not a chorus.

Asking one model once gets you one confident answer you cannot check. This
runs six stages instead, and the CEO holds a gate before every one:

  1 FRAME     — read the question, convene only the perspectives it actually
                needs, restate what is really being decided, and check it
                against what the board already ruled in past sessions.
  2 RESEARCH  — every seat researches INDEPENDENTLY: its own queries from its
                own lane, its own sources, its own cited brief. Shared research
                would hand all seats the same evidence and the same blind spot.
  3 POSITIONS — each seat opens with a position it is willing to defend.
  4 DEBATE    — seats attack each other's EVIDENCE, not each other's tone, and
                name the contradictions they find.
  5 REDTEAM   — a red team attacks the FRAMING itself (the failure mode a
                debate cannot catch: everyone arguing the wrong question well),
                then every seat states what would still sink its position and
                scores its own confidence.
  6 BRIEF     — one defensible brief: recommendation, confidence, the sources
                behind it, and the dissent left on the record.

Echo-chamber control: each seat runs on a DIFFERENT vendor's model (see
config.DEFAULT_PROVIDERS). Four personas on one model is one brain wearing
four hats — the Frame stage measures that and says so out loud.

Every seat is grounded in the CEO's own document library plus the evidence it
found itself. Between stages the CEO can steer, skip, stop, rewind (reset) or
branch; rejected paths are replayed so the board does not re-serve an angle
that was already turned down.
"""
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from . import config, docs, llm, memory, research, sources, store

log = logging.getLogger("hub.depts")

STEPS = ["frame", "framing_redteam", "research", "positions", "debate", "redteam", "brief"]
STEP_LABELS = {
    "frame": "Stage 1 — Frame: ตั้งกรอบและเลือกมุมมองที่ต้องใช้",
    "framing_redteam": "Stage 1.5 — Framing Red Team: โจมตีกรอบทันที ก่อนเผา token",
    "research": "Stage 2 — Independent Research: แต่ละมุมมองหาหลักฐานเอง",
    "positions": "Stage 3 — Opening Positions: จุดยืนตั้งต้นของแต่ละฝ่าย",
    "debate": "Stage 4 — The Debate: ท้าทายหลักฐานกันและกัน",
    "redteam": "Stage 5 — Evidence Red Team & Converge: หาจุดอ่อนของหลักฐาน + วัดความมั่นใจ",
    "brief": "Stage 6 — Defensible Brief: ข้อเสนอ + แหล่งอ้างอิง + เสียงค้าน",
}

# Sessions recorded before the Crucible pipeline. They stay readable and are
# never resumed — next_step() treats them as archived.
LEGACY_STEPS = {"opinions", "cross_exam", "verdicts", "synthesis"}
STEP_LABELS.update({
    "opinions": "Round 1 — ความเห็นในกรอบความเชี่ยวชาญ (รูปแบบเดิม)",
    "cross_exam": "Round 2 — Cross-Examination วิพากษ์กันเอง (รูปแบบเดิม)",
    "verdicts": "Round 3 — คำตัดสินสุดท้ายต่อ CEO (รูปแบบเดิม)",
    "synthesis": "Round 4 — บทสรุปประธานบอร์ด (รูปแบบเดิม)",
})

# ── Guardrails: each seat may ONLY speak inside its lane ──
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

FRAME_SYSTEM = (
    "คุณคือ moderator ของบอร์ดที่ปรึกษา หน้าที่คือ 'ตั้งกรอบ' ก่อนเปิดประชุม ไม่ใช่ตอบคำถาม\n"
    "งานของคุณมี 3 อย่าง:\n"
    "1) อ่านคำถามแล้วบอกว่า 'จริงๆ แล้วกำลังตัดสินใจอะไร' — คำถามที่ CEO ถามมามักไม่ใช่"
    "คำถามที่ควรตัดสินใจจริง ถ้าเห็นว่าตั้งคำถามผิด ให้บอกตรงๆ\n"
    "2) เลือกเฉพาะมุมมองที่จำเป็นกับคำถามนี้ — ที่ปรึกษาที่ไม่เกี่ยวไม่ต้องเรียกเข้าประชุม "
    "การเรียกครบทุกคนทั้งที่ไม่เกี่ยวคือการเพิ่มเสียงรบกวน ไม่ใช่เพิ่มความรอบคอบ\n"
    "3) ระบุว่า 'หลักฐานแบบไหนที่จะเปลี่ยนคำตอบได้' — ถ้าไม่มีอะไรเปลี่ยนคำตอบได้เลย "
    "แปลว่านี่ไม่ใช่การตัดสินใจ แต่เป็นการหาเหตุผลรองรับสิ่งที่ตัดสินใจไปแล้ว ให้เตือน CEO\n"
    "ตอบเป็น JSON ล้วนเท่านั้น ห้ามมีข้อความอื่นนอก JSON:\n"
    "{\n"
    '  "reframed": "สิ่งที่กำลังตัดสินใจจริงๆ ในประโยคเดียว",\n'
    '  "decision_type": "กลับตัวได้|กลับตัวไม่ได้ — และเดิมพันคืออะไร",\n'
    '  "seats": ["key ของมุมมองที่ต้องเรียก"],\n'
    '  "seat_reasons": {"key": "ทำไมต้องมีคนนี้"},\n'
    '  "excluded": {"key": "ทำไมไม่ต้องเรียกคนนี้"},\n'
    '  "what_would_change_the_answer": ["หลักฐานที่ถ้าเจอแล้วคำตอบพลิก"],\n'
    '  "success_criteria": ["จะรู้ได้อย่างไรว่าตัดสินใจถูก — ต้องวัดได้"],\n'
    '  "framing_risk": "ความเสี่ยงที่จะตอบคำถามผิดข้อ (ถ้าไม่มีให้ใส่ค่าว่าง)"\n'
    "}\n"
    "seats ต้องมีอย่างน้อย 2 คน และเลือกจาก key ที่ให้มาเท่านั้น"
)

SEAT_QUERY_SYSTEM = (
    "คุณคือ {name} ({role}) กำลังจะหาหลักฐานด้วยตัวเองก่อนเข้าประชุมบอร์ด\n"
    "ขอบเขตของคุณ: {lane}\n"
    "ตั้งคำค้นสำหรับ search engine 3 ข้อ ที่จะได้หลักฐานในมุมของ**คุณเอง**เท่านั้น — "
    "ไม่ใช่คำค้นกลางๆ ที่ใครก็ตั้งได้ ถ้าคุณคือ CFO ต้องค้นเรื่องต้นทุน/ผลตอบแทน "
    "ถ้าคุณคือ COO ต้องค้นเรื่องความเป็นไปได้ในการลงมือทำ\n"
    "ถ้าโจทย์เกี่ยวกับไทย ให้มีคำค้นภาษาไทยอย่างน้อย 1 ข้อ และภาษาอังกฤษอย่างน้อย 1 ข้อ\n"
    "ตอบเป็นคำค้นล้วนๆ บรรทัดละ 1 ข้อ ห้ามใส่เลขลำดับ ห้ามอธิบาย ห้ามใส่เครื่องหมายคำพูด"
)

SEAT_RESEARCH_SYSTEM = (
    "คุณคือ {name} ({role}) กำลังคัดกรองผลค้นหาที่คุณสั่งค้นเอง\n"
    "ขอบเขตของคุณ: {lane}\n"
    "กฎเหล็ก: {guard}\n"
    "หน้าที่คือ **คัดกรอง** ไม่ใช่สรุปทุกอย่างที่เห็น:\n"
    "- ตัดโฆษณา/คอนเทนต์ขายของ/ข้ออ้างที่ไม่มีตัวเลขรองรับทิ้ง\n"
    "- ข้อมูลเก่าเกิน 2 ปีต้องระบุปีกำกับและเตือนว่าอาจล้าสมัย\n"
    "- ทุกข้อเท็จจริงต้องมีเลขอ้างอิง [n] ตามหมายเลขแหล่งที่ให้มา ห้ามอ้างเลขที่ไม่มีอยู่\n"
    "- ไม่เจอก็ต้องบอกว่าไม่เจอ ห้ามเดาหรือแต่งตัวเลข\n"
    "ตอบภาษาไทย ไม่เกิน 10 บรรทัด ใช้โครงสร้างนี้:\n"
    "หลักฐานที่ผมได้มา: (bullet พร้อมตัวเลขและ [n] — เฉพาะที่อยู่ในเลนของคุณ)\n"
    "หลักฐานนี้บอกอะไรกับมุมของผม: (1-2 บรรทัด)\n"
    "ช่องว่างที่ยังไม่มีหลักฐาน: (สิ่งที่คุณอยากรู้แต่หาไม่เจอ)"
)

POSITION_SYSTEM = (
    "คุณคือ {name} ({role}) ที่ปรึกษาเชิงกลยุทธ์ประจำตัว CEO\n"
    "ขอบเขตความเชี่ยวชาญของคุณ: {lane}\n"
    "กฎเหล็ก (guardrail): {guard} — ถ้าคำถามอยู่นอกขอบเขต ให้ตอบสั้นๆ ว่าอยู่นอกความเชี่ยวชาญ\n"
    "นี่คือการเปิดจุดยืน ไม่ใช่การสรุป — ให้จุดยืนที่คุณพร้อมปกป้องเมื่อถูกโจมตี\n"
    "อ้างหลักฐานที่คุณหามาเองด้วย [n] ทุกครั้งที่ใช้ตัวเลข\n"
    "ตอบภาษาไทย กระชับ ไม่เกิน 9 บรรทัด ใช้โครงสร้างนี้เท่านั้น:\n"
    "จุดยืน: (เอา/ไม่เอา/เอาแบบมีเงื่อนไข — ประโยคเดียว ชัดเจน ห้ามกั๊ก)\n"
    "หลักฐานที่หนุนจุดยืนนี้: (อ้าง [n] — ถ้าไม่มีหลักฐานให้เขียนว่า (ยังไม่มีหลักฐาน))\n"
    "ความเสี่ยงที่ซ่อนอยู่: (จุดบอดที่ CEO อาจมองข้าม — ต้องเฉพาะเจาะจง ห้ามพูดกว้าง)\n"
    "สิ่งที่จะทำให้ผมเปลี่ยนใจ: (หลักฐานอะไรที่จะหักล้างจุดยืนของผมได้)"
)

DEBATE_SYSTEM = (
    "คุณคือ {name} ({role}) อยู่ในห้องประชุมบอร์ด ขอบเขตของคุณ: {lane}\n"
    "ด้านล่างคือจุดยืนและหลักฐานของที่ปรึกษาคนอื่น จงโจมตี **หลักฐาน** ของเขา ไม่ใช่ท่าที:\n"
    "- ชี้ว่าหลักฐานของใครอ่อน ล้าสมัย หรือไม่รองรับข้อสรุปที่เขาอ้าง (ระบุชื่อตำแหน่งและ [n])\n"
    "- ถ้าหลักฐานของคุณขัดกับของเขาโดยตรง ให้ประกาศว่าขัดกันตรงไหน และแหล่งไหนน่าเชื่อกว่าเพราะอะไร\n"
    "- ยอมรับจุดที่เขาถูกและคุณพลาด — การยอมรับที่ตรงไปตรงมามีค่ากว่าการเอาชนะ\n"
    "ตอบภาษาไทย ไม่เกิน 6 บรรทัด ห้ามทวนจุดยืนเดิมของตัวเอง ใช้โครงสร้างนี้:\n"
    "ข้อโต้แย้ง: (ใคร อ้างอะไร และผิดตรงไหน)\n"
    "หลักฐานขัดกัน: (ระบุคู่ที่ขัดกัน ถ้าไม่มีให้เขียนว่า ไม่พบ)\n"
    "จุดที่ผมยอมรับว่าพลาด: (ถ้าไม่มีให้เขียนว่า ไม่มี)"
)

REDTEAM_SEAT_SYSTEM = (
    "คุณคือ {name} ({role}) หลังถูกวิพากษ์มาแล้ว ตอนนี้ต้องซื่อสัตย์กับตัวเอง\n"
    "ขอบเขตของคุณ: {lane}\n"
    "อย่าปกป้องจุดยืนเดิมโดยอัตโนมัติ ถ้าการถกเถียงทำให้คุณควรเปลี่ยนใจ ให้เปลี่ยน\n"
    "ตอบภาษาไทย ไม่เกิน 6 บรรทัด ใช้โครงสร้างนี้เท่านั้น:\n"
    "จุดยืนหลังถกเถียง: (คงเดิม / เปลี่ยนเป็น… — ประโยคเดียว)\n"
    "จุดอ่อนที่ยังเหลือในจุดยืนของผม: (ข้อที่ยังไม่มีใครหักล้างได้แต่ผมก็ยังพิสูจน์ไม่ได้)\n"
    "ความมั่นใจ: NN%  (ตัวเลข 0-100 เท่านั้น — ถ้าหลักฐานบาง ต้องให้ต่ำ การให้สูงลอยๆ ถือว่าผิด)\n"
    "เหตุผลของระดับความมั่นใจ: (1 บรรทัด อ้างว่าหลักฐานพอหรือไม่พอตรงไหน)"
)

FRAMING_REDTEAM_SYSTEM = (
    "คุณคือ Red Team อิสระที่ถูกเรียกมาโจมตี 'การตั้งกรอบ' ของ moderator "
    "**ก่อนบอร์ดเริ่มค้นหลักฐาน** — จังหวะเดียวที่คุณจะช่วยได้จริง\n"
    "เหตุผลที่คุณอยู่ตรงนี้: การถกเถียงคุณภาพสูงในคำถามที่ผิดข้อคือของเสียของทั้งการประชุม "
    "ถ้ากรอบผิดตอนนี้ บอร์ดจะเผา 4 stage ถัดไปกับสิ่งที่ไม่ควรทำ\n"
    "หน้าที่คุณคือ **ท้าทาย 4 อย่าง** ให้ตรงประเด็น กระชับ ไม่เกิน 8 บรรทัด "
    "ถ้ากรอบใช้ได้จริงต้องบอกว่าใช้ได้ อย่าหาเรื่องเพื่อดูขยัน:\n"
    "- คำถามที่ moderator ตั้งขึ้น เป็นคำถามที่ควรตัดสินใจจริงหรือไม่ "
    "หรือควรเป็นคำถามอื่นก่อน (เช่น 'ควรเปิดสาขาไหม' อาจต้องถามก่อนว่า 'ทำไมสาขาเดิมยอดตก')\n"
    "- ที่นั่งที่ถูกเรียก ครอบคลุมพอไหม ที่นั่งไหนไม่จำเป็น "
    "และมุมมองอะไรที่หายไปโดยที่ moderator มองไม่เห็น (ลูกค้า พนักงาน กฎหมาย ครอบครัว …)\n"
    "- สมมติฐานฝังในการ reframe ที่ moderator ไม่รู้ตัว\n"
    "- 'หลักฐานที่จะเปลี่ยนคำตอบ' ที่ moderator เขียน — พอจะเปลี่ยนคำตอบได้จริง "
    "หรือถูกเลือกให้ยืนยันคำตอบเดิม\n"
    "ตอบเป็น JSON ล้วน:\n"
    "{\n"
    '  "verdict": "OK|CONCERN|BLOCK",\n'
    '  "reframe_suggestion": "คำถามที่ควรตัดสินใจแทน (เว้นว่างถ้ากรอบใช้ได้)",\n'
    '  "unchallenged_assumptions": ["สมมติฐานที่ moderator ยึดโดยไม่ตรวจ"],\n'
    '  "missing_seats": [{"seat": "key หรือชื่อที่ไม่มีในโครงสร้าง เช่น customer, legal",\n'
    '                     "why_missing": "จะพลาดอะไรถ้าไม่มีคนนี้"}],\n'
    '  "evidence_bar_too_low": "หลักฐานที่ moderator ระบุ พอจะพลิกคำตอบได้จริงไหม",\n'
    '  "one_line_summary": "สรุปข้อกังวลใหญ่สุด 1 ประโยค"\n'
    "}\n"
    "verdict:\n"
    "  OK      = กรอบใช้ได้ ให้เดินหน้าค้นหลักฐาน\n"
    "  CONCERN = ควรปรับกรอบ แต่ CEO เดินต่อได้ถ้ารับความเสี่ยง\n"
    "  BLOCK   = อย่าเพิ่งเผา token — reframe หรือขยายที่นั่งก่อน"
)

REDTEAM_SYSTEM = (
    "คุณคือ Evidence Red Team ที่ถูกเรียกหลัง Stage 4 — หลังบอร์ดถกเถียงบนหลักฐานจริงแล้ว\n"
    "**Framing Red Team ทำงานตั้งแต่ Stage 1.5 ไปแล้ว** — ถ้ากรอบผ่านมาถึงตรงนี้ "
    "แปลว่าเคยถูกท้าทายมาแล้ว ให้เคารพส่วนนั้น อย่าถกซ้ำเรื่องกรอบ\n"
    "หน้าที่คุณคือโจมตี **คุณภาพหลักฐานและตรรกะ** ที่ถูกใช้จริงในการประชุมนี้:\n"
    "- หลักฐานที่บอร์ดใช้ตัดสิน มีจุดอ่อนอะไร (มาจากแหล่งประเภทเดียวกัน / เก่าเกินไป / เชอร์รี่พิก / โฆษณา)\n"
    "- ตรรกะจากหลักฐาน → ข้อสรุปมีช่องโหว่ตรงไหน (สรุปเกินสิ่งที่หลักฐานรองรับหรือไม่)\n"
    "- ข้อมูลที่ **มีอยู่แล้ว** แต่ไม่มีใครหยิบมาชนกับข้อสรุป\n"
    "- ระดับความมั่นใจสอดคล้องกับคุณภาพหลักฐานจริงไหม (คน confident เท่ากับ 90% "
    "โดยที่หลักฐานเป็นบทความเดียวจากปี 2022 คือของปลอม)\n"
    "ตอบภาษาไทย ไม่เกิน 10 บรรทัด ใช้โครงสร้างนี้:\n"
    "หลักฐานที่อ่อนที่สุด: (ระบุแหล่ง [n] หรือคำอ้างของใคร พร้อมเหตุผล)\n"
    "ตรรกะที่ข้ามขั้น: (จากหลักฐาน A ไปสรุป B โดยที่ยังต้องพิสูจน์อะไรก่อน)\n"
    "ข้อมูลที่มีอยู่แต่ยังไม่ถูกชน: (ถ้าไม่มีให้เขียนว่า ไม่พบ)\n"
    "ความมั่นใจของบอร์ดสอดคล้องกับหลักฐานไหม: (เต็ม/สูงเกินไป/ต่ำเกินไป พร้อมเหตุผล 1 บรรทัด)\n"
    "ถ้าจะล้มข้อสรุปนี้ ต้องหาอะไรเพิ่ม: (1-2 ข้อ ที่ทำได้จริง)"
)

BRIEF_SYSTEM = (
    "คุณคือประธานบอร์ด ทำหน้าที่ออก Defensible Brief ให้ CEO ตัดสินใจได้ทันที\n"
    "คุณไม่มีวาระของตัวเอง หน้าที่คือชั่งน้ำหนักอย่างตรงไปตรงมา\n"
    "กฎเหล็ก:\n"
    "- ห้ามเสนอความเห็นใหม่ที่ไม่มีใครในบอร์ดพูด\n"
    "- ห้ามกลบเสียงค้าน — ถ้าบอร์ดแตก ต้องบันทึกเสียงข้างน้อยไว้พร้อมเหตุผลของเขา\n"
    "- ความมั่นใจต้องสอดคล้องกับคุณภาพหลักฐานและคำเตือนของ Red Team "
    "ถ้า Red Team ชี้ว่ากรอบผิดหรือหลักฐานบาง ความมั่นใจต้องลดลงตาม\n"
    "- ทุกตัวเลขที่มาจากภายนอกต้องมี [n] กำกับ\n"
    "ตอบภาษาไทย ใช้โครงสร้างนี้เท่านั้น:\n"
    "ข้อเสนอ: ทำ | ไม่ทำ | ทำแบบมีเงื่อนไข (สรุปเป็นประโยคเดียว)\n"
    "ความมั่นใจ: NN%  (ตัวเลข 0-100 — ต้องอธิบายได้ด้วยหลักฐาน ไม่ใช่ความรู้สึก)\n"
    "เหตุผลของระดับความมั่นใจ: (อ้างคุณภาพหลักฐานและคำเตือนของ Red Team)\n"
    "ระดับความเห็นพ้อง: เอกฉันท์ | เสียงข้างมาก x-y | บอร์ดแตก (ระบุใครอยู่ฝ่ายไหน)\n"
    "เสียงค้านที่บันทึกไว้: (ใครค้าน ค้านด้วยเหตุผลอะไร และถ้าเขาถูก จะเกิดอะไรขึ้น)\n"
    "ประเด็นที่ CEO ต้องชี้ขาดเอง: (ข้อที่บอร์ดตกลงกันไม่ได้)\n"
    "สิ่งที่ต้องทำต่อ: (3 ข้อ เรียงตามลำดับ ทำได้จริงภายใน 30 วัน)\n"
    "เงื่อนไขล้มเลิก: (สัญญาณอะไรที่บอกว่าต้องถอย)"
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


# ── seats, providers, prompt assembly ──

def seats(session: dict) -> list[str]:
    """Which perspectives are sitting in this session.

    Frame narrows the board to what the question needs; until it runs (or if it
    picked nothing usable) every seat is convened, so a session is never empty.
    """
    chosen = [s for s in (session.get("seats") or []) if s in config.DEPTS]
    return chosen or list(config.DEPTS)


def _dept_provider(dept: str) -> str:
    return store.get_providers().get(dept, "mock")


def _chair_provider() -> str:
    """The moderator borrows the first seat provider that has a working key."""
    assigned = store.get_providers()
    for dept in config.DEPTS:
        p = assigned.get(dept, "mock")
        if p != "mock" and llm.provider_ready(p):
            return p
    return next((p for p in config.PROVIDERS if p != "mock" and llm.provider_ready(p)), "mock")


def model_diversity(session: dict | None = None) -> dict:
    """How many distinct *vendors* the convened seats actually run on.

    The whole premise is that disagreement comes from different reasoning, not
    from different system prompts. One vendor behind every seat is one brain in
    five hats, and the board's agreement means nothing.

    Counting provider keys is not enough: two Anthropic models are two keys but
    one lab, one pretraining corpus and one set of refusal habits, so they share
    blind spots. Vendors are the unit that matters.
    """
    keys = seats(session) if session else list(config.DEPTS)
    assigned = store.get_providers()
    per_seat = {k: assigned.get(k, "mock") for k in keys}
    live = [p for p in per_seat.values() if p != "mock" and llm.provider_ready(p)]
    vendors = [vendor_of(p) for p in live]
    distinct = len(set(vendors))
    per_vendor: dict[str, list[str]] = {}
    for seat, prov in per_seat.items():
        if prov == "mock" or not llm.provider_ready(prov):
            continue
        per_vendor.setdefault(vendor_of(prov), []).append(seat)
    doubled = {v: s for v, s in per_vendor.items() if len(s) > 1}

    warning = None
    if not live:
        warning = ("ยังไม่มี seat ไหนต่อ AI จริงเลย — บอร์ดจะตอบด้วย mock ทั้งหมด "
                   "ไปที่หน้า Agents เพื่อผูก provider")
    elif distinct == 1:
        warning = (f"ทุก seat ที่ใช้งานได้รันบนค่ายเดียวกัน ({vendors[0]}) — "
                   "ความเห็นที่ได้มาจากสมองเดียวกันสวมหลายหมวก "
                   "ไม่ใช่การถกเถียงจริง ควรกระจายค่ายในหน้า Agents")
    elif doubled:
        overlap = "; ".join(f"{v}: {', '.join(config.DEPTS[s]['name'] for s in ss)}"
                            for v, ss in doubled.items())
        warning = (f"มีค่ายที่ถือหลายที่นั่ง ({overlap}) — "
                   "ที่นั่งเหล่านั้นมีจุดบอดร่วมกัน ถ้าเห็นด้วยกันอย่านับเป็นสองเสียง")
    elif distinct < min(3, len(live)):
        warning = (f"seat ที่ใช้งานได้ {len(live)} ที่นั่ง แต่มาจากค่ายเพียง {distinct} ราย — "
                   "ยิ่งกระจายได้มาก จุดบอดร่วมยิ่งน้อย")
    return {"per_seat": per_seat, "distinct": distinct, "live": len(live),
            "per_vendor": per_vendor, "shared_vendors": doubled, "warning": warning}


def vendor_of(provider: str) -> str:
    """Vendor for a provider key, falling back to the key itself so a provider
    added without a vendor label still counts as its own lab rather than None."""
    return config.PROVIDERS.get(provider, {}).get("vendor") or provider


def _fmt(dept: str, template: str) -> str:
    d = config.DEPTS[dept]
    lane, guard = LANES.get(dept, ("ธุรกิจโดยรวม", "ตอบเฉพาะสิ่งที่มีหลักฐานรองรับ"))
    return template.format(name=d["name"], role=d["role"], lane=lane, guard=guard)


def _parse_json(text: str) -> dict | None:
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


_CONFIDENCE = re.compile(r"ความมั่นใจ\s*[:：]?\s*(\d{1,3})\s*%?")


def parse_confidence(text: str) -> int | None:
    """Pull the self-scored confidence out of a seat's reply."""
    m = _CONFIDENCE.search(text or "")
    if not m:
        return None
    value = int(m.group(1))
    return value if 0 <= value <= 100 else None


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
    """The next stage that has not run yet. The brief is terminal, and sessions
    recorded by the old pipeline are archived rather than resumed."""
    done = {s["key"] for s in session["steps"]}
    if done & LEGACY_STEPS or "brief" in done:
        return None
    skip = set() if session.get("web_research", True) else {"research"}
    # No frame → nothing for the framing red team to attack. The board keeps
    # moving (that's the whole point of fail-open framing) but the 1.5 pass
    # would be spending a call on an empty payload.
    framer = _results_of(session, "frame").get("framer") or {}
    if "frame" in done and not framer.get("ok"):
        skip.add("framing_redteam")
    return next((s for s in STEPS if s not in done and s not in skip), None)


# ── grounding: the CEO's documents + the evidence each seat found itself ──

def _own_evidence(session: dict, dept: str) -> str:
    """The seat's own research, handed back to it in later stages."""
    mine = _results_of(session, "research").get(dept)
    if not mine or not mine.get("ok") or not mine.get("text"):
        return ""
    srcs = "\n".join(f"[{i}] {s.get('title', '')} — {s.get('url', '')}"
                     for i, s in enumerate(mine.get("sources", []), 1))
    return ("[หลักฐานที่คุณค้นมาเอง — อ้างด้วย [n] ได้]\n"
            f"{mine['text']}" + (f"\n\nแหล่งของคุณ:\n{srcs}" if srcs else ""))


def _shared_evidence(session: dict, exclude: str | None = None) -> str:
    """What the other seats found. Shown in the debate so seats can attack each
    other's evidence rather than trade opinions."""
    blocks = []
    for key, val in _results_of(session, "research").items():
        if key in ("analyst",) or key == exclude or not val.get("ok"):
            continue
        name = config.DEPTS.get(key, {}).get("name", key)
        srcs = "; ".join(f"[{i}] {s.get('url', '')}"
                         for i, s in enumerate(val.get("sources", []), 1))
        blocks.append(f"[หลักฐานของ {name}]\n{val.get('text', '')}"
                      + (f"\nแหล่ง: {srcs}" if srcs else ""))
    return "\n\n".join(blocks)


def _library(session: dict, max_chars: int = 3500) -> str:
    """The CEO's documents plus live data pulled from the project's own systems
    (POS / back-office) — unless this is a general question, where dragging in
    the business context would only bias an answer that is not about it."""
    if not session.get("use_docs", True):
        return ""
    project = session.get("project")
    parts = [docs.knowledge_context(project=project, max_chars=max_chars)]
    live = sources.live_context(project=project)
    if live:
        parts.append(live)
    return "\n\n".join(p for p in parts if p)


def _grounding(session: dict, dept: str | None = None) -> str:
    """Documents the CEO owns, plus this seat's own evidence."""
    blocks = []
    knowledge = _library(session)
    if knowledge:
        blocks.append("[คลังเอกสารธุรกิจของ CEO — ใช้เป็นบริบทจริง อย่าเดาสวนข้อมูลนี้]\n"
                      + knowledge)
    if dept:
        own = _own_evidence(session, dept)
        if own:
            blocks.append(own)
    frame = _frame_context(session)
    if frame:
        blocks.append(frame)
    return "\n\n".join(blocks)


def _frame_context(session: dict) -> str:
    """The framing every seat must argue inside."""
    framer = _results_of(session, "frame").get("framer")
    if not framer or not framer.get("ok"):
        return ""
    parts = [f"[กรอบการตัดสินใจที่ moderator ตั้งไว้]\nสิ่งที่กำลังตัดสินใจจริง: {framer.get('reframed', '')}"]
    if framer.get("decision_type"):
        parts.append(f"ลักษณะการตัดสินใจ: {framer['decision_type']}")
    if framer.get("what_would_change_the_answer"):
        parts.append("หลักฐานที่จะเปลี่ยนคำตอบได้: "
                     + "; ".join(framer["what_would_change_the_answer"][:4]))
    if framer.get("carry_forward"):
        parts.append("ข้อผูกมัดจากมติเก่าที่ต้องเคารพ: " + "; ".join(framer["carry_forward"][:4]))
    # If the Framing Red Team objected and the CEO chose to press on, every
    # seat downstream should know what they were told to ignore. A concern that
    # is not passed along is a concern that was quietly deleted.
    fr = _results_of(session, "framing_redteam").get("framing_redteam") or {}
    if fr.get("ok") and fr.get("verdict") in ("CONCERN", "BLOCK"):
        parts.append(f"[Framing Red Team ({fr['verdict']})] " + (fr.get("summary") or ""))
        if fr.get("unchallenged_assumptions"):
            parts.append("สมมติฐานที่ยังไม่ถูกตรวจ: "
                         + "; ".join(fr["unchallenged_assumptions"][:3]))
    return "\n".join(parts)


# ── stage execution ──

def _round(session: dict, template: str, build_user) -> dict:
    """Run one stage across every convened seat, in parallel, each on its own model."""
    sid = session["id"]
    keys = seats(session)

    def one(dept: str) -> tuple[str, dict]:
        if store.is_stopped(sid):
            return dept, {"text": "⏹ CEO สั่งหยุดก่อนรอบนี้จบ", "provider": "-", "ok": False}
        out = llm.chat(_dept_provider(dept), _fmt(dept, template), build_user(dept),
                       cancel=lambda: store.is_stopped(sid))
        return dept, {"text": out["text"], "provider": out["provider"], "ok": out["ok"]}

    with ThreadPoolExecutor(max_workers=max(1, len(keys))) as ex:
        return dict(ex.map(one, keys))


def run_step(session: dict, step: str, directive: str | None = None) -> dict:
    """Execute one stage and return its results keyed by seat."""
    question = session["question"]
    rejected = _rejected_context(session, step)
    tail = _directive_context(directive) + (f"\n\n{rejected}" if rejected else "")

    if step == "frame":
        return {"framer": _frame(session, directive, tail)}

    if step == "framing_redteam":
        return {"framing_redteam": _framing_redteam(session, tail)}

    if step == "research":
        return _independent_research(session, tail)

    if step == "positions":
        def position_user(dept: str) -> str:
            ground = _grounding(session, dept)
            return f"คำถามของ CEO: {question}" + (f"\n\n{ground}" if ground else "") + tail
        return _round(session, POSITION_SYSTEM, position_user)

    if step == "debate":
        positions = _results_of(session, "positions")

        def debate_user(dept: str) -> str:
            others = "\n\n".join(
                f"[{config.DEPTS.get(k, {}).get('name', k)} — จุดยืน]\n{v['text']}"
                for k, v in positions.items() if k != dept and v.get("ok"))
            ground = _grounding(session, dept)
            evidence = _shared_evidence(session, exclude=dept)
            return (f"คำถามของ CEO: {question}"
                    + (f"\n\n{ground}" if ground else "")
                    + f"\n\nจุดยืนของที่ปรึกษาคนอื่น:\n{others}"
                    + (f"\n\nหลักฐานที่คนอื่นใช้:\n{evidence}" if evidence else "")
                    + tail)
        return _round(session, DEBATE_SYSTEM, debate_user)

    if step == "redteam":
        results = _redteam_seats(session, question, tail)
        results["redteam"] = _redteam(session, tail)
        return results

    if step == "brief":
        return {"chair": _brief(session, tail)}

    raise ValueError(f"unknown step: {step}")


# ── stage 1: frame ──

def _frame(session: dict, directive: str | None, tail: str) -> dict:
    """Pick the perspectives, restate the decision, and check the archive."""
    provider = _chair_provider()
    roster = "\n".join(
        f"- {k}: {d['name']} ({d['role']}) — {d.get('expertise', '')}"
        for k, d in config.DEPTS.items())
    past = memory.recall(session.get("project"))
    conflict = memory.conflicts(session["question"], session.get("project"), provider)

    ctx = [f"คำถามของ CEO: {session['question']}"]
    if session.get("project"):
        ctx.append(f"โปรเจค/ธุรกิจ: {session['project']}")
    ctx.append(f"มุมมองที่เรียกได้ (เลือกจาก key เหล่านี้เท่านั้น):\n{roster}")
    if past:
        ctx.append(f"มติเก่าของบอร์ดในโปรเจคนี้:\n{memory.as_prompt(past)}")
    knowledge = _library(session, max_chars=1500)
    if knowledge:
        ctx.append(f"ตัวอย่างเอกสารที่ CEO มี:\n{knowledge}")

    out = llm.chat(provider, FRAME_SYSTEM, "\n\n".join(ctx) + tail)
    data = _parse_json(out["text"]) if out["ok"] else None

    if data is None:
        # Fail open: a bad framing pass must not stop the board convening.
        log.warning("frame parse failed for consult %s", session.get("id"))
        chosen = list(config.DEPTS)
        store.set_seats(session["id"], chosen)
        return {"text": ("⚠️ ตั้งกรอบอัตโนมัติไม่สำเร็จ — เรียกที่ปรึกษาครบทุกที่นั่ง "
                         "และใช้คำถามเดิมของ CEO เป็นกรอบ"),
                "provider": out["provider"], "ok": False, "seats": chosen,
                "reframed": session["question"], "conflicts": conflict["conflicts"],
                "carry_forward": conflict["carry_forward"],
                "memory_checked": conflict["checked"],
                "diversity": model_diversity({"seats": chosen})}

    chosen = [s for s in (data.get("seats") or []) if s in config.DEPTS]
    if len(chosen) < 2:                       # a debate needs at least two voices
        chosen = list(config.DEPTS)
    store.set_seats(session["id"], chosen)

    lines = [f"สิ่งที่กำลังตัดสินใจจริง: {data.get('reframed', '')}"]
    if data.get("decision_type"):
        lines.append(f"ลักษณะการตัดสินใจ: {data['decision_type']}")
    lines.append("เรียกเข้าประชุม: " + ", ".join(
        f"{config.DEPTS[k]['name']} ({(data.get('seat_reasons') or {}).get(k, '')})".strip()
        for k in chosen))
    excluded = {k: v for k, v in (data.get("excluded") or {}).items() if k in config.DEPTS}
    if excluded:
        lines.append("ไม่เรียก: " + ", ".join(
            f"{config.DEPTS[k]['name']} ({v})" for k, v in excluded.items()))
    if data.get("what_would_change_the_answer"):
        lines.append("หลักฐานที่จะเปลี่ยนคำตอบได้:\n"
                     + "\n".join(f"• {x}" for x in data["what_would_change_the_answer"]))
    if data.get("success_criteria"):
        lines.append("จะรู้ได้อย่างไรว่าตัดสินใจถูก:\n"
                     + "\n".join(f"• {x}" for x in data["success_criteria"]))
    if data.get("framing_risk"):
        lines.append(f"ความเสี่ยงที่จะตอบผิดข้อ: {data['framing_risk']}")

    return {"text": "\n".join(lines), "provider": out["provider"], "ok": True,
            "seats": chosen, "seat_reasons": data.get("seat_reasons") or {},
            "excluded": excluded,
            "reframed": data.get("reframed") or session["question"],
            "decision_type": data.get("decision_type"),
            "what_would_change_the_answer": data.get("what_would_change_the_answer") or [],
            "success_criteria": data.get("success_criteria") or [],
            "framing_risk": data.get("framing_risk") or "",
            "conflicts": conflict["conflicts"],
            "carry_forward": conflict["carry_forward"],
            "memory_checked": conflict["checked"],
            "diversity": model_diversity({"seats": chosen})}


# ── stage 1.5: framing red team ──

def _framing_redteam(session: dict, tail: str) -> dict:
    """Attack the framing BEFORE the board burns four stages arguing inside it.

    Cheap: one LLM call, small payload, no research or seat fan-out. This is the
    exact failure the docstring flagged — "everyone arguing the wrong question
    well" — and Stage 5 could not catch it because token was already spent by
    the time it ran. Structured output so the UI can flag CONCERN/BLOCK, and
    the fields flow into every seat's grounding context.
    """
    framer = _results_of(session, "frame").get("framer") or {}
    if not framer.get("ok"):
        # No frame to attack — skip cleanly, keep the pipeline moving.
        return {"text": "ข้าม — Stage 1 ตั้งกรอบไม่สำเร็จ ไม่มีกรอบให้ท้าทาย",
                "provider": "-", "ok": False, "verdict": "OK"}

    provider = _chair_provider()
    seat_roster = ", ".join(f"{k} ({config.DEPTS[k]['name']})" for k in config.DEPTS)
    convened = ", ".join(config.DEPTS.get(k, {}).get("name", k)
                         for k in framer.get("seats", []))
    excluded_note = ""
    if framer.get("excluded"):
        excluded_note = "\nที่นั่งที่ moderator ตัดสินใจไม่เรียก + เหตุผล:\n" + "\n".join(
            f"  - {config.DEPTS.get(k, {}).get('name', k)}: {v}"
            for k, v in framer["excluded"].items())

    ctx = (
        f"คำถามเดิมของ CEO: {session['question']}\n"
        f"โปรเจค/ธุรกิจ: {session.get('project') or '(ไม่ระบุ)'}\n\n"
        f"[กรอบที่ moderator ตั้งไว้]\n"
        f"reframed: {framer.get('reframed', '')}\n"
        f"ลักษณะการตัดสินใจ: {framer.get('decision_type', '(ไม่ระบุ)')}\n"
        f"ที่นั่งที่ moderator เรียก: {convened}"
        + excluded_note
        + "\nหลักฐานที่ moderator บอกว่าจะเปลี่ยนคำตอบ:\n"
        + ("\n".join(f"  - {x}" for x in (framer.get("what_would_change_the_answer") or []))
           or "  (ไม่ได้ระบุ)")
        + f"\n\nที่นั่งที่ระบบมี ให้ moderator เลือก: {seat_roster}"
    )

    out = llm.chat(provider, FRAMING_REDTEAM_SYSTEM, ctx + tail,
                   cancel=lambda: store.is_stopped(session["id"]))
    data = _parse_json(out["text"]) if out["ok"] else None
    if data is None:
        log.warning("framing red team parse failed for consult %s", session.get("id"))
        return {"text": ("⚠️ Framing Red Team วิเคราะห์ไม่สำเร็จ (provider ไม่พร้อม "
                         "หรือคืนค่าไม่เป็น JSON) — เดินหน้าตามกรอบเดิม"),
                "provider": out["provider"], "ok": False, "verdict": "OK"}

    verdict = str(data.get("verdict", "OK")).upper()
    if verdict not in ("OK", "CONCERN", "BLOCK"):
        verdict = "CONCERN"
    lines = [f"คำตัดสิน: {verdict}"]
    if data.get("one_line_summary"):
        lines.append(f"สรุป: {data['one_line_summary']}")
    if data.get("reframe_suggestion"):
        lines.append(f"เสนอ reframe: {data['reframe_suggestion']}")
    if data.get("unchallenged_assumptions"):
        lines.append("สมมติฐานที่ไม่ถูกตรวจ:")
        lines += [f"  • {x}" for x in data["unchallenged_assumptions"]]
    if data.get("missing_seats"):
        lines.append("มุมมองที่หายไป:")
        for m in data["missing_seats"]:
            seat = m.get("seat", "")
            reason = m.get("why_missing", "")
            lines.append(f"  • {seat} — {reason}" if reason else f"  • {seat}")
    if data.get("evidence_bar_too_low"):
        lines.append(f"เกณฑ์หลักฐาน: {data['evidence_bar_too_low']}")

    return {"text": "\n".join(lines), "provider": out["provider"], "ok": True,
            "verdict": verdict,
            "summary": data.get("one_line_summary") or "",
            "reframe_suggestion": data.get("reframe_suggestion") or "",
            "unchallenged_assumptions": data.get("unchallenged_assumptions") or [],
            "missing_seats": data.get("missing_seats") or [],
            "evidence_bar_too_low": data.get("evidence_bar_too_low") or ""}


# ── stage 2: independent research, one desk per seat ──

def _seat_queries(session: dict, dept: str, tail: str) -> list[str]:
    """Each seat writes its own search queries, on its own model."""
    ctx = f"คำถามของ CEO: {session['question']}"
    framer = _results_of(session, "frame").get("framer") or {}
    if framer.get("reframed"):
        ctx += f"\nกรอบที่ตกลงกันไว้: {framer['reframed']}"
    if session.get("project"):
        ctx += f"\nโปรเจค/ธุรกิจ: {session['project']}"
    out = llm.chat(_dept_provider(dept), _fmt(dept, SEAT_QUERY_SYSTEM), ctx + tail,
                   cancel=lambda: store.is_stopped(session["id"]))
    if not out["ok"]:
        return [session["question"]]
    queries = [ln.strip(" -•\t") for ln in out["text"].splitlines() if ln.strip()]
    queries = [q for q in queries if len(q) > 3][:3]
    return queries or [session["question"]]


def _independent_research(session: dict, tail: str) -> dict:
    """Every seat searches on its own. Shared research means shared blind spots."""
    sid = session["id"]
    cancel = lambda: store.is_stopped(sid)  # noqa: E731
    keys = seats(session)

    def one(dept: str) -> tuple[str, dict]:
        if store.is_stopped(sid):
            return dept, {"text": "⏹ CEO สั่งหยุดก่อนรอบนี้จบ", "provider": "-", "ok": False,
                          "queries": [], "sources": []}
        queries = _seat_queries(session, dept, tail)
        found = research.gather(queries, per_query=3, max_sources=5, cancel=cancel)
        sources, errors = found["sources"], found["errors"]
        if not sources:
            # Never let "the search was blocked" read as "the web has nothing on
            # this" — the CEO acts on those two very differently.
            blocked = bool(errors)
            head = ("⚠️ ค้นเว็บไม่สำเร็จ — ยังไม่ได้อ่านอินเทอร์เน็ตเลย ไม่ใช่ว่าอินเทอร์เน็ตไม่มีข้อมูล"
                    if blocked else "ค้นได้แต่ไม่พบหลักฐานที่เกี่ยวกับโจทย์นี้")
            detail = ("\nสาเหตุ:\n" + "\n".join(f"• {e}" for e in errors)
                      + f"\n\nวิธีแก้: ใส่ TAVILY_API_KEY, SERPAPI_API_KEY หรือ BRAVE_API_KEY ใน hub/.env "
                        f"แล้วรีสตาร์ท hub (ตอนนี้ใช้ {research.backend_label()})"
                      if blocked else "")
            return dept, {
                "text": f"{head}{detail}\n\nคำค้นที่ลอง: {', '.join(queries)}",
                "provider": research.backend(), "ok": False, "blocked": blocked,
                "queries": queries, "sources": [], "errors": errors}
        out = llm.chat(_dept_provider(dept), _fmt(dept, SEAT_RESEARCH_SYSTEM),
                       f"คำถามของ CEO: {session['question']}\n"
                       f"คำค้นที่คุณสั่ง: {', '.join(queries)}\n\n"
                       f"ผลค้นหาดิบ:\n{research.as_prompt(sources)}" + tail,
                       cancel=cancel)
        return dept, {"text": out["text"],
                      "provider": f"{out['provider']} · {research.backend_label()}",
                      "ok": out["ok"], "queries": queries,
                      "sources": [{"title": s.get("title", ""), "url": s.get("url", ""),
                                   "query": s.get("query", "")} for s in sources]}

    with ThreadPoolExecutor(max_workers=max(1, len(keys))) as ex:
        results = dict(ex.map(one, keys))

    # A merged evidence index: the union of what the whole board found. PDF and
    # deliverable exports cite from here, and it is what "the session's sources"
    # means anywhere outside a single seat's own reasoning.
    merged: list[dict] = []
    seen: set[str] = set()
    for dept, val in results.items():
        for s in val.get("sources", []):
            url = s.get("url", "")
            if url and url not in seen:
                seen.add(url)
                merged.append({**s, "found_by": dept})
    desks = sum(1 for v in results.values() if v.get("ok"))
    blocked = [d for d, v in results.items() if v.get("blocked")]
    text = (f"หลักฐานรวมของการประชุมนี้: {len(merged)} แหล่ง จาก {desks} ที่นั่งที่ค้นสำเร็จ "
            "(แต่ละที่นั่งค้นเองแยกกัน จึงไม่แชร์จุดบอดเดียวกัน)")
    if blocked:
        names = ", ".join(config.DEPTS.get(d, {}).get("name", d) for d in blocked)
        text += (f"\n\n⚠️ {len(blocked)} ที่นั่งค้นเว็บไม่ได้เลย ({names}) — "
                 f"ใช้ {research.backend_label()} อยู่ ซึ่งบล็อกคำขออัตโนมัติบ่อย "
                 "ข้อสรุปของบอร์ดรอบนี้จึงยืนอยู่บนหลักฐานที่บางกว่าที่ควรเป็น "
                 "ใส่ TAVILY_API_KEY, SERPAPI_API_KEY หรือ BRAVE_API_KEY ใน hub/.env เพื่อให้ค้นได้จริง")
    results["analyst"] = {
        "text": text,
        "provider": research.backend_label(), "ok": bool(merged),
        "blocked_seats": blocked,
        "queries": sorted({q for v in results.values() for q in v.get("queries", [])}),
        "sources": merged,
    }
    return results


# ── stage 5: red team ──

def _redteam_seats(session: dict, question: str, tail: str) -> dict:
    debate = _results_of(session, "debate")
    positions = _results_of(session, "positions")

    def user(dept: str) -> str:
        attacks = "\n".join(
            f"[{config.DEPTS.get(k, {}).get('name', k)} วิพากษ์] {v['text']}"
            for k, v in debate.items() if k != dept and v.get("ok"))
        mine = positions.get(dept, {}).get("text", "(ยังไม่ได้เปิดจุดยืน)")
        ground = _grounding(session, dept)
        return (f"คำถามของ CEO: {question}" + (f"\n\n{ground}" if ground else "")
                + f"\n\nจุดยืนเดิมของคุณ:\n{mine}\n\nสิ่งที่คนอื่นโจมตีคุณ:\n{attacks}" + tail)

    results = _round(session, REDTEAM_SEAT_SYSTEM, user)
    for val in results.values():
        val["confidence"] = parse_confidence(val.get("text", ""))
    return results


def _redteam(session: dict, tail: str) -> dict:
    """Evidence Red Team — attack the quality of the evidence and the logic
    from evidence to conclusion. The framing was already attacked in Stage 1.5,
    so this pass should not re-open that ground."""
    # Feed the earlier framing critique in so this pass doesn't repeat it, but
    # focus this LLM call on evidence quality — the thing that only exists after
    # research and the debate have both happened.
    transcript = _transcript(session, ("positions", "debate"))
    evidence = _shared_evidence(session)
    div = model_diversity(session)
    framing = _results_of(session, "framing_redteam").get("framing_redteam") or {}
    framing_note = (
        f"[Framing Red Team ตัดสินว่า {framing['verdict']} ตอน Stage 1.5]\n"
        + (framing.get("text", "")[:600] if framing.get("ok") else "(ข้ามหรือล้มเหลว)")
    ) if framing else "(Framing Red Team ยังไม่ได้ทำงาน)"

    out = llm.chat(_chair_provider(), REDTEAM_SYSTEM,
                   f"คำถามของ CEO: {session['question']}\n"
                   f"จำนวน vendor ที่ต่างกันจริง: {div['distinct']} จาก {div['live']} ที่นั่งที่ใช้งานได้\n\n"
                   f"{framing_note}\n\n"
                   f"บันทึกการถกเถียง (positions + debate):\n{transcript}"
                   + (f"\n\nหลักฐานทั้งหมดที่บอร์ดใช้:\n{evidence}" if evidence else "")
                   + tail)
    return {"text": out["text"], "provider": out["provider"], "ok": out["ok"],
            "diversity": div}


# ── stage 6: defensible brief ──

def _transcript(session: dict, keys: tuple) -> str:
    parts = []
    for key in keys:
        results = _results_of(session, key)
        if not results:
            continue
        parts.append(f"## {STEP_LABELS.get(key, key)}")
        for k, v in results.items():
            if not v.get("ok"):
                continue
            name = ({"framer": "Moderator", "redteam": "Evidence Red Team",
                     "framing_redteam": "Framing Red Team",
                     "analyst": "ดัชนีหลักฐานรวม", "chair": "ประธานบอร์ด"}.get(k)
                    or config.DEPTS.get(k, {}).get("name", k))
            parts.append(f"[{name}] {v['text']}")
    return "\n".join(parts) or "(บอร์ดยังไม่ได้ถกเถียง)"


def confidence_summary(session: dict) -> dict:
    """Each seat's self-scored confidence, plus the board average."""
    scores = {k: v.get("confidence") for k, v in _results_of(session, "redteam").items()
              if k != "redteam" and v.get("confidence") is not None}
    avg = round(sum(scores.values()) / len(scores)) if scores else None
    return {"per_seat": scores, "average": avg,
            "lowest": min(scores, key=scores.get) if scores else None}


def _brief(session: dict, tail: str) -> dict:
    """Fold the whole session into one ruling the CEO can act on — and file it
    to memory so the next session can be checked against it."""
    transcript = _transcript(session, ("frame", "framing_redteam", "positions",
                                       "debate", "redteam"))
    grounding = _library(session)
    evidence = _shared_evidence(session)
    conf = confidence_summary(session)
    conf_line = ("ความมั่นใจที่แต่ละที่นั่งให้ตัวเอง: "
                 + ", ".join(f"{config.DEPTS.get(k, {}).get('name', k)} {v}%"
                             for k, v in conf["per_seat"].items())
                 + (f" (เฉลี่ย {conf['average']}%)" if conf["average"] is not None else "")
                 ) if conf["per_seat"] else ""

    out = llm.chat(_chair_provider(), BRIEF_SYSTEM,
                   f"คำถามของ CEO: {session['question']}"
                   + (f"\n\n[คลังเอกสารของ CEO]\n{grounding}" if grounding else "")
                   + (f"\n\nหลักฐานที่บอร์ดใช้:\n{evidence}" if evidence else "")
                   + (f"\n\n{conf_line}" if conf_line else "")
                   + f"\n\nบันทึกการประชุม:\n{transcript}" + tail)

    result = {"text": out["text"], "provider": out["provider"], "ok": out["ok"],
              "confidence": parse_confidence(out["text"]),
              "seat_confidence": conf}

    if out["ok"]:
        try:
            entry = memory.remember(session, transcript + "\n\n" + out["text"],
                                    _chair_provider())
            result["memory_id"] = entry["id"] if entry else None
        except Exception as e:  # noqa: BLE001 — filing must not fail the brief
            log.warning("memory write failed for consult %s: %s", session.get("id"), e)
    return result
