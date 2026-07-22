# CFO Command — Autonomous AI Chief Financial Officer

> **CFO Command System Initialized. Monitoring financial pipelines.**

ระบบ **AI CFO อัตโนมัติ** ที่ทำหน้าที่เป็น "เรดาร์ทางการเงิน" ให้ทุกโปรเจคธุรกิจ —
วิเคราะห์กำไรขาดทุน (P&L), เฝ้าระวังกระแสเงินสด (Cash Flow), ประเมินความเสี่ยง
และออก **CFO Executive Financial Brief** แบบ async (ไม่ต้องประชุม) โดยเชื่อมต่อกับ
**Claude** เพื่อสั่งการด้วยภาษาธรรมชาติและเรียนรู้จากการทำงานที่ผ่านมา

An always-on AI CFO: a deterministic finance engine computes every number, Claude
interprets and prioritises them, and a scheduler runs the whole loop autonomously.

หน้าตา UI อ้างอิงจากสไตล์ agentic-OS (dark command center + agent tiles) ตามรูปที่ให้มา

---

## ⚡ ทำไมออกแบบแบบนี้ (Design principles)

| หลักการ | การนำไปใช้ |
|---|---|
| **ตัวเลขแม่นยำ 100% ห้ามเดา** | ทุกตัวเลขมาจาก `src/financeEngine.js` (deterministic) — Claude แค่ตีความ ไม่แต่งตัวเลข |
| **Cash Flow มาก่อน** | Projection 30 วันข้างหน้า + แจ้งเตือนเชิงรุกเมื่อเงินสดจะต่ำกว่าเกณฑ์ปลอดภัย |
| **ไม่ประชุม (async)** | ออกเป็น Executive Brief สั้น กระชับ 4 หัวข้อ |
| **ทำงานอัตโนมัติ** | Scheduler (cron) รันวิเคราะห์ + สร้าง brief เองตามรอบเวลา |
| **เรียนรู้ต่อเนื่อง** | Memory เก็บ brief เดิม / alert ที่เกิดซ้ำ / feedback ผู้บริหาร แล้วป้อนกลับเข้า prompt |
| **ทนทาน** | ไม่มี API key ก็ยังรันได้ (deterministic fallback) — การเฝ้าระวังไม่พึ่งเครือข่าย |

---

## 🚀 เริ่มใช้งาน (Quick start)

```bash
# 1) ติดตั้ง dependencies
npm install

# 2) ตั้งค่า (ใส่ Claude API key เพื่อเปิดโหมดสนทนา/บทวิเคราะห์)
cp .env.example .env
#   แก้ ANTHROPIC_API_KEY=... ใน .env

# 3) รันระบบ (dashboard + API + autonomous scheduler)
npm start
#   เปิด http://localhost:3000
```

> **ไม่มี API key?** ระบบยังทำงานเต็มรูปแบบด้วย *deterministic fallback* —
> คำนวณตัวเลข, แจ้งเตือน, และออก brief ได้ครบ เพียงแต่ไม่มีบทวิเคราะห์เชิงภาษา/แชท

### คำสั่ง CLI

```bash
npm run brief     # พิมพ์ CFO Executive Financial Brief ออกทาง terminal
npm run monitor   # รันรอบเฝ้าระวัง 1 ครั้ง (เหมือนที่ scheduler ทำ) แล้วบันทึกลง memory
```

---

## 🧠 สถาปัตยกรรม (Architecture)

```
              ┌─────────────────────────────────────────────┐
   CSV/JSON ─▶│  dataLoader   → financeEngine (deterministic)│─▶ numbers (facts)
   (data/)    └─────────────────────────────────────────────┘        │
                                                                      ▼
                          memory.js ◀───────────────  cfoAgent.js (Claude)
                    (self-learning loop)                 │  brief / chat
                                                         ▼
        scheduler.js (cron) ─┐                    server.js (Express)
        cli.js ──────────────┼──▶ service.js ──▶  ├─ REST API  (/api/*)
                             ┘                     └─ dashboard (public/)
```

| ไฟล์ | หน้าที่ |
|---|---|
| `src/dataLoader.js` | อ่าน CSV/JSON แบบเข้มงวด (เจอค่าที่ไม่ใช่ตัวเลข → throw ไม่เดา) |
| `src/financeEngine.js` | คำนวณ P&L, cost structure + spike detection, cash position, projection 30 วัน, runway, NPL, alerts |
| `src/cfoAgent.js` | เชื่อม Claude สำหรับ brief + chat (มี deterministic fallback) |
| `src/memory.js` | ความจำถาวร: brief เดิม, alert เกิดซ้ำ, feedback, insights → ป้อนกลับเข้า prompt |
| `src/scheduler.js` | รอบเฝ้าระวังอัตโนมัติ (node-cron) + จุดต่อ notify (email/LINE/Slack/webhook) |
| `src/service.js` | ชั้นประสานงานที่ server/CLI/scheduler ใช้ร่วมกัน |
| `server.js` | Express server + REST API + เสิร์ฟ dashboard + arm scheduler |
| `public/` | Dashboard (dark agentic-OS UI) — vanilla JS, ไม่มี build step |

---

## 📊 ข้อมูลการเงิน (Data model)

ระบบอ่านจากโฟลเดอร์ `data/` — เปลี่ยนไฟล์เหล่านี้เป็นข้อมูลจริงของคุณได้เลย:

**`data/projects.json`** — ทะเบียนโปรเจค + เงินสดตั้งต้น
```json
{ "id": "sinchai-refinance", "name": "Sinchai Refinance", "type": "lending",
  "opening_cash": 2450000, "opening_cash_date": "2026-07-01" }
```

**`data/transactions.csv`** — รายการเดินบัญชี
```
date,project,type,category,cost_type,pnl,amount,description
```
- `type`: `income` | `expense`
- `cost_type`: `fixed` | `variable` | `na`
- `pnl`: `yes` = เข้า P&L, `no` = กระแสเงินสดล้วน (เช่น เงินต้นสินเชื่อจ่าย/รับคืน — กระทบเงินสดแต่ไม่ใช่กำไร)

**`data/obligations.csv`** — ภาระ/รายรับที่จะเกิดขึ้น (ใช้พยากรณ์เงินสดล่วงหน้า)
```
date,project,direction,category,amount,status,description   # direction: in | out
```

**`data/receivables.csv`** — ลูกหนี้ (สำหรับความเสี่ยงพอร์ตสินเชื่อ/NPL)
```
customer_id,project,principal,outstanding,due_date,days_overdue,status
```

> ตัวอย่างที่ให้มามี 2 โปรเจคต่างประเภท: **สินเชื่อ/รีไฟแนนซ์** (เงินทุนหมุนเวียน + NPL)
> และ **ร้านกาแฟหน้าร้าน** (ต้นทุนคงที่ + ค่าซ่อมบำรุง) เพื่อสาธิตการวิเคราะห์ที่ต่างกัน

---

## 🔌 REST API

| Method | Endpoint | ทำอะไร |
|---|---|---|
| `GET` | `/api/status` | สถานะระบบ, model, การเชื่อม Claude, thresholds, memory |
| `GET` | `/api/analysis` | ผลวิเคราะห์ตัวเลขทั้งหมด (deterministic) |
| `GET` | `/api/brief` | CFO Executive Financial Brief (Claude หรือ fallback) |
| `POST` | `/api/chat` | สนทนา/สั่งการ CFO — `{ message, history }` |
| `POST` | `/api/feedback` | ส่ง feedback ผู้บริหารเข้าลูปเรียนรู้ — `{ text }` |
| `POST` | `/api/monitor/run` | สั่งรันรอบเฝ้าระวังทันที |

---

## 🤖 การทำงานอัตโนมัติ & การเรียนรู้

- **Autonomous monitoring** — `CFO_MONITOR_CRON` (ค่าเริ่มต้น `0 8 * * *` = ทุกวัน 08:00)
  จะรันวิเคราะห์ + สร้าง brief + log สัญญาณเตือนเอง ตั้ง `off` เพื่อปิด
- **Self-learning loop** — ทุกรอบจะบันทึกลง `memory/cfo-memory.json`:
  alert ที่เกิดซ้ำจะถูกแท็ก *(เกิดซ้ำ)*, feedback และ brief เดิมถูกป้อนกลับเข้า prompt
  ของ Claude เพื่อให้คำแนะนำต่อเนื่องและลด noise
- **ต่อการแจ้งเตือนจริง** — แก้ `notify()` ใน `src/scheduler.js` ให้ยิงเข้า
  email / LINE Notify / Slack / webhook ตามที่ใช้งาน

---

## ⚙️ การตั้งค่า (`.env`)

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Claude API key (เปิดโหมด AI) |
| `CFO_MODEL` | `claude-opus-4-8` | โมเดล Claude |
| `PORT` | `3000` | พอร์ต dashboard/API |
| `CFO_MONITOR_CRON` | `0 8 * * *` | รอบเฝ้าระวังอัตโนมัติ (`off` = ปิด) |
| `CFO_MIN_CASH_BUFFER` | `100000` | เกณฑ์เงินสดปลอดภัยต่อโปรเจค (แจ้งเตือนเมื่อต่ำกว่า) |
| `CFO_PROJECTION_DAYS` | `30` | ช่วงพยากรณ์กระแสเงินสด |
| `CFO_COST_SPIKE_PCT` | `20` | เกณฑ์เตือนต้นทุนพุ่ง (% เทียบเดือนก่อน) |
| `CFO_NPL_DAYS` | `30` | จำนวนวันค้างชำระที่นับเป็นหนี้เสี่ยง |

---

## 🔒 หมายเหตุด้านความปลอดภัย/ข้อมูล

- `.env` และ `memory/*.json` ถูก gitignore ไว้ — อย่า commit API key หรือข้อมูลการเงินจริง
- ตัวเลขทั้งหมดคำนวณจากไฟล์ที่คุณให้เท่านั้น หากข้อมูลไม่ครบ engine จะ throw ทันที
  (ตามนโยบาย "ห้ามเดาข้อมูลการเงิน")

## License
MIT
