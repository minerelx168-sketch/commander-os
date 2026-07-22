# COO Command 🛰️

**ระบบสั่งการ AI Chief Operating Officer (COO) แบบอัตโนมัติ**
_Agentic Back-Office Operations — เชื่อมต่อกับ Manus LLM ได้_

COO Command คือระบบหลังบ้านที่ทำงานได้ด้วยตัวเอง (autonomous) ทำหน้าที่เป็น
"ประธานเจ้าหน้าที่บริหารฝ่ายปฏิบัติการ" ที่เน้นการลงมือทำจริง — จัดการเอกสารอัตโนมัติ,
ติดตาม pipeline/ยอดค้างชำระ, จัดการประกาศ และออก **"สรุปการปฏิบัติงาน COO
(COO Operational Brief)"** แบบอซิงโครนัสตามนโยบายงดการประชุม

> แนวคิด/หน้าตาอ้างอิงจากคลิป Agentic OS — แต่โฟกัสที่ **ฝั่งปฏิบัติการ (Ops)** แทนฝั่ง Growth

---

## ✨ จุดเด่น

- **รันได้ทันที ไม่ต้องมี API key** — มีตัววางแผนภายใน (`mock` planner) ที่เดินตาม
  operational playbook ทำให้ระบบเป็น autonomous ได้เลย
- **เสียบ Manus / LLM ได้ทันที** — เปลี่ยน `LLM_PROVIDER=manus` แล้วใส่ endpoint + key
  (รองรับ OpenAI-compatible Chat Completions + function-calling)
- **Zero dependency** — ใช้เฉพาะ Node.js built-in (`node:http`, `node --test`) ไม่ต้อง `npm install`
- **ตรวจสอบวัน/เวลาเข้มงวด** — โมดูล `datetime` ปฏิเสธรูปแบบผิด/วันที่ไม่มีจริง/เวลาในอดีต
- **ความถูกต้องทางการเงิน** — จัดรูปแบบเงินบาททศนิยม 2 ตำแหน่งเสมอ

---

## 🚀 เริ่มใช้งาน

```bash
# 1) รัน agent loop หนึ่งรอบ แล้วดู COO Operational Brief (ไม่ต้องตั้งค่าอะไร)
npm run brief

# 2) เปิด server + dashboard
npm start
#   → เปิดเบราว์เซอร์ที่ http://localhost:8080

# 3) รันแบบอัตโนมัติเป็นรอบ ๆ (เช่น ทุก 60 นาที)
npm run loop 60

# 4) รันชุดทดสอบ
npm test
```

ต้องใช้ Node.js เวอร์ชัน 20 ขึ้นไป

---

## 🧩 สถาปัตยกรรม

```
คำสั่ง (directive) ─▶ Agent Loop ─▶ LLM (Manus | mock) ─┐
                          ▲                              │ ขอเรียก tools
                          │        ผลลัพธ์ป้อนกลับ        ▼
                          └──────────────── Tool Registry (เครื่องมือจริง)
                                                 │
        ┌────────────────┬─────────────────┬─────┴──────────┐
        ▼                ▼                 ▼                ▼
   documents         pipeline        announcements       brief
 (PDF/PDPA)     (overdue/ทวงหนี้)    (ประกาศ+เช็ควันที่)  (COO Brief)
                                                 │
                                                 ▼
                                    COO Operational Brief ──▶ webhook (ถ้าตั้งค่า)
```

โครงไฟล์:

| ไฟล์ | หน้าที่ |
|------|--------|
| `src/server.js` | HTTP server + REST API ให้ Manus เรียก |
| `src/agent/agentLoop.js` | วงจรทำงานอัตโนมัติ (LLM ↔ tools ↔ brief) |
| `src/agent/llmClient.js` | อะแดปเตอร์ LLM: `manus` (จริง) / `mock` (ในตัว) |
| `src/agent/systemPrompt.js` | บทบาท/กฎการทำงานของ COO |
| `src/tools/pipeline.js` | ตรวจ pipeline, ทวงยอดค้างชำระ |
| `src/tools/documents.js` | สร้างเอกสาร PDF สัญญา/PDPA (ต่อ Google Apps Script ได้) |
| `src/tools/announcements.js` | ตั้ง/ส่งประกาศ พร้อมเช็ควัน-เวลาเข้มงวด |
| `src/tools/brief.js` | สร้าง COO Operational Brief 3 ส่วน |
| `src/utils/datetime.js` | ตรวจสอบวัน/เวลาแบบเข้มงวด (หัวใจความถูกต้อง) |
| `manus/openapi.yaml` | สเปก API ให้ Manus import |

---

## 🔌 การเชื่อมต่อ Manus LLM

Manus (หรือ LLM อื่นที่ทำ tool-calling ได้) เชื่อมต่อได้ 2 แบบ:

### แบบ A — ให้ Manus เป็นสมองของ agent loop
ตั้งค่าใน `.env`:
```bash
LLM_PROVIDER=manus
MANUS_API_URL=https://api.manus.im/v1/chat/completions
MANUS_API_KEY=sk-...
MANUS_MODEL=manus-1
```
จากนั้น `POST /api/agent/run` — ระบบจะให้ Manus ตัดสินใจว่าจะเรียกเครื่องมือใดเอง

### แบบ B — ให้ Manus เรียกเครื่องมือผ่าน HTTP โดยตรง
1. Manus ค้นเครื่องมือได้จาก `GET /api/tools` (คืน function-calling schema)
2. เรียกเครื่องมือด้วย `POST /api/tools/<ชื่อ>` พร้อม JSON body
3. import `manus/openapi.yaml` เข้า Manus เป็น tool spec ได้เลย

---

## 🛠️ REST API

| Method & Path | หน้าที่ | Auth |
|---------------|--------|:----:|
| `GET /health` | ตรวจสถานะบริการ | — |
| `GET /api/tools` | รายการเครื่องมือ + schema (ให้ Manus ค้นหา) | — |
| `POST /api/tools/{name}` | เรียกเครื่องมือหนึ่งตัว | 🔑 |
| `POST /api/agent/run` | รัน agent loop → คืน COO Brief | 🔑 |
| `GET /api/state` | สถานะรวมสำหรับ dashboard | — |
| `GET /api/brief/latest` | COO Brief ล่าสุด | — |
| `POST /api/reset` | รีเซ็ตข้อมูลกลับ seed (เดโม/ทดสอบ) | 🔑 |

> 🔑 = ต้องส่ง header `x-coo-key: <COO_API_KEY>` — จะบังคับก็ต่อเมื่อมีการตั้งค่า
> `COO_API_KEY` ไว้ใน `.env` (ตอน dev ปล่อยว่างไว้ก็รันได้)

ตัวอย่าง:
```bash
curl -X POST http://localhost:8080/api/tools/pipeline_check \
  -H 'content-type: application/json' -d '{"reference":"2026-07-21"}'
```

---

## 🧰 เครื่องมือที่มีให้ (Tools)

| ชื่อ | หน้าที่ |
|------|--------|
| `pipeline_check` | ตรวจ pipeline หาบัญชีเกินกำหนด + สรุปยอด |
| `pipeline_send_reminder` | ร่าง+ส่งข้อความทวงยอดค้าง (กันส่งซ้ำต่อวัน) |
| `document_generate` | สร้างเอกสาร PDF สัญญา/PDPA + ตั้งชื่อ+จัดเก็บ |
| `document_list` | ดูเอกสารรอสร้าง/สร้างแล้ว |
| `announcement_schedule` | ตั้งประกาศ + ตรวจวัน-เวลาเข้มงวด |
| `announcement_dispatch` | ส่งประกาศที่ถึงกำหนด |
| `announcement_list` | ดูประกาศ |
| `coo_brief` | สร้าง COO Operational Brief |

---

## 🔗 ต่อของจริง (Production TODO)

ระบบนี้เป็นโครงที่รันได้ครบวงจร โดยจุดที่ต่อเข้าระบบจริงถูกทำเป็น "จุดเสียบ" ชัดเจน:

- **Document Automation** → `src/tools/documents.js` รับพารามิเตอร์ `appsScriptUrl`
  เพื่อ POST ไปยัง Google Apps Script Web App จริง (ปัจจุบันจำลองผลลัพธ์)
- **การส่งข้อความ/ประกาศ** → `src/tools/pipeline.js`, `announcements.js`
  ต่อ SMS/LINE/Email gateway ที่จุดที่ log ว่า "ส่ง..."
- **ข้อมูล** → `src/data/store.js` ปัจจุบันใช้ JSON; เปลี่ยนเป็น DB/Google Sheets ได้
- **รายงาน** → ตั้ง `REPORT_WEBHOOK_URL` เพื่อให้ POST COO Brief ไปยังปลายทาง (LINE/Slack/ฯลฯ)

---

## 📄 License

MIT
