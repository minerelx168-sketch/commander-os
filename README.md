# 👑 Commander OS — CEO Command Hub

**คุณคือ CEO** — บอร์ด C-level (CMO / CFO / COO / Datalyst) เป็นที่ปรึกษาเชิงกลยุทธ์
ที่ถกกันให้คุณฟังทีละรอบ **โดยหยุดรอคำสั่งคุณก่อนทุกรอบ** และแต่ละที่ปรึกษาเลือกได้ว่า
จะให้ AI ตัวไหน (Claude / Gemini / Manus) ขับเคลื่อน

บอร์ดยืนอยู่บนข้อมูลจริงสองขา: **คลังเอกสารของคุณเอง** (LINE / อัพโหลด / Google Drive)
และ **ข้อมูลจากอินเทอร์เน็ตที่ผ่านการคัดกรอง** — ไม่ใช่ความเห็นลอยๆ

## โครงสร้าง

```
hub/            FastAPI hub + UI (port 8100) — หน้ารวมทุกอย่าง
services/
  cmo/          จาก minerelx168-sketch/CMO_command   (FastAPI, port 8201)
  coo/          จาก minerelx168-sketch/COO_command   (Node,   port 8202)
  cfo/          จาก minerelx168-sketch/CFO_command   (Node,   port 8203)
  datalyst/     Data Analyst service (สร้างใหม่)      (FastAPI, port 8204)
scripts/        start_all.sh, e2e_live.sh, set_default_providers.sh
```

## flow การประชุมบอร์ด (หน้า Boardroom)

เลือก **โปรเจค** ที่จะถก + เปิด/ปิด **🌐 สืบข้อมูลจากอินเทอร์เน็ต** แล้วพิมพ์โจทย์ →
บอร์ดเดินทีละรอบ และ **หยุดที่จุดตัดสินใจก่อนเข้ารอบถัดไปทุกครั้ง**

| รอบ | ใครทำ | ได้อะไร |
|---|---|---|
| **0 · Research** | ฝ่ายวิจัยข้อมูล | ค้นเว็บหลายคำค้น → คัดกรอง (ตัดโฆษณา / ระบุปีของข้อมูลเก่า / ชี้จุดที่แหล่งขัดกัน) → บรีฟพร้อมเลขอ้างอิง `[n]` + ลิงก์ต้นทาง |
| **1 · Opinion** | ทั้ง 4 ที่ปรึกษา | มุมมอง / ความเสี่ยงที่ซ่อนอยู่ / คำแนะนำเด็ดขาด — ตอบได้เฉพาะในเลนตัวเอง (guardrail) |
| **2 · Cross-Exam** | ทั้ง 4 | วิพากษ์สมมติฐานที่อ่อนของคนอื่น ระบุชื่อตำแหน่ง |
| **3 · Verdict** | ทั้ง 4 | ทำ / ไม่ทำ / ทำแบบมีเงื่อนไข |
| **4 · Synthesis** | ประธานบอร์ด | มติบอร์ด · ระดับความเห็นพ้อง · ประเด็นที่ยังขัดแย้ง · 3 สิ่งที่ต้องทำใน 30 วัน · เงื่อนไขล้มเลิก |

**ที่จุดตัดสินใจแต่ละจุด คุณเลือกได้:**

- ▶ **ดำเนินการต่อ** — สั่งบอร์ดเพิ่มก่อนเข้ารอบก็ได้ (คำสั่งถูกยัดเข้า prompt ของรอบนั้นตรงๆ)
- ⏭ **ข้ามไปบทสรุปประธานเลย** — ไม่ต้องครบทุกรอบ
- ⏹ **STOP** — หยุดกลางรอบได้จริง ผลที่ได้มาแล้วไม่หาย และกลับมาถกต่อได้
- ↩ **ย้อนกลับมาแก้จุดนี้ (reset)** — ลบรอบนั้นและรอบถัดไปทิ้ง
- 🔀 **แตกกิ่งจากจุดนี้ (branch)** — เปิดไทม์ไลน์ใหม่ โดยของเดิมยังอยู่ครบ

> **บอร์ดเรียนรู้จากทางที่คุณปัดตก** — ทั้ง reset และ branch เก็บเส้นทางเดิมไว้ใน `history`
> แล้วป้อนกลับเข้า prompt ว่า "ห้ามเสนอซ้ำแนวเดิม ให้หามุมใหม่" คุณจึงเทียบสองทางเลือก
> จากจุดแยกเดียวกันได้เหมือน branch ใน git

## หน้าอื่น

- **⚖️ Decisions** — บันทึกว่าคุณตัดสินใจอย่างไร แล้วให้คะแนนย้อนหลังเมื่อรู้ผลจริง
  (กันความเสียหาย / เร็วขึ้น / เฉยๆ / พลาดจุดบอด) เพื่อวัดว่าที่ปรึกษามีค่าจริงไหม
- **📁 เอกสาร** — คลังความรู้: **อัพโหลดจากเว็บ (ลากวางได้)** / ส่งเข้า LINE bot /
  sync จาก Google Drive — บรรณารักษ์ AI จัดเข้าโปรเจคให้เอง (หรือคุณเลือกโปรเจคตอนอัพโหลด)
- **🤖 Agents** — เลือก AI provider ต่อที่ปรึกษา + ดูสถานะ service ของแต่ละแผนก (จุดเขียว/เทา)

## เริ่มใช้งาน

```bash
# ครั้งแรก: ติดตั้ง dependencies
cd hub && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd ../services/cmo && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd ../cfo && npm install

# รันทั้งระบบ
bash scripts/start_all.sh
# เปิด http://localhost:8100

# ทดสอบ
cd hub && .venv/bin/python -m pytest tests/ -q
```

## API keys (`hub/.env`)

| ตัวแปร | ใช้กับ |
|---|---|
| `ANTHROPIC_API_KEY` | Claude (claude-fable-5) |
| `GOOGLE_API_KEY` | Gemini (ใช้อ่าน/OCR รูปเอกสารด้วย) |
| `MANUS_API_KEY` + `MANUS_API_URL` | Manus (native task API) |
| `TAVILY_API_KEY` / `BRAVE_API_KEY` / `SERPER_API_KEY` | ค้นเว็บ — ใส่ตัวใดตัวหนึ่ง (ไม่ใส่ก็ยังค้นได้ผ่าน DuckDuckGo) |
| `GDRIVE_SERVICE_ACCOUNT_JSON` + `GDRIVE_FOLDER_ID` | เก็บเอกสารขึ้น Google Drive |
| `LINE_CHANNEL_SECRET` + `LINE_CHANNEL_ACCESS_TOKEN` | รับเอกสารผ่าน LINE bot |

ไม่มี LLM key = provider นั้นขึ้น "no key" ในหน้า Agents และ fallback เป็น mock ·
ไม่มี search key = ใช้ DuckDuckGo ซึ่งฟรีแต่โดน rate-limit ง่ายกว่า

> รูปแบบเดิม (LangGraph boardroom + Postgres) ถูกถอดออกทั้งหมด —
> เก็บไว้ที่ branch `legacy-langgraph`
