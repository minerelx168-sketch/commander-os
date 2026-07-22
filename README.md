# 👑 Commander OS — CEO Command Hub

**คุณคือ CEO** — สั่งการเองทั้งหมด แผนก C-level (CMO / CFO / COO / Datalyst) เป็น
ที่ปรึกษาและมือทำงาน โดยแต่ละแผนกใช้โค้ดต้นแบบจาก repo ของคุณเอง และเลือกได้ว่า
จะให้ AI ตัวไหน (Claude / Gemini / Manus) ขับเคลื่อนแผนกนั้น

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

## หน้า UI (http://localhost:8100)

1. **⌘ Command Overall** — พิมพ์คำถามลงกล่อง → ทั้ง 4 C-level ตอบพร้อมกันเป็น
   **tree diagram** (CEO บนสุด → แตกกิ่งลง 4 แผนก) แต่ละใบให้ มุมมอง / ผลดี /
   ความเสี่ยง / คำแนะนำ ในมุมที่ตัวเองถนัด
2. **📣 CMO** — สั่งงานจริง: ระบบดึงข้อมูลสดจาก service ของแผนก + บทเรียนสะสม
   (LLM Learning) เข้า prompt แล้วให้ AI ลงมือทำ ผลงานถูกกลั่นเป็นบทเรียน
   ป้อนกลับอัตโนมัติ ทำให้เก่งขึ้นเรื่อยๆ
3. **💰 CFO / 🛰 COO / 📊 Datalyst** — หน้าเดียวกับ CMO ครบทุกแผนก
4. **🤖 Agents** — dropdown เลือก AI provider ต่อแผนก: Claude (Anthropic) /
   Gemini (Google) / Manus / Mock — สลับได้ทันที ไม่ต้อง restart

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
| `GOOGLE_API_KEY` | Gemini |
| `MANUS_API_KEY` + `MANUS_API_URL` | Manus (OpenAI-compatible) |

ไม่มี key = provider นั้นขึ้น "no key" ในหน้า Agents และ fallback เป็น mock

> รูปแบบเดิม (LangGraph boardroom + Postgres) ถูกถอดออกทั้งหมด —
> เก็บไว้ที่ branch `legacy-langgraph`
