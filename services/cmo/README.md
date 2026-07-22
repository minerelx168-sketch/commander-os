# 📣 CMO Command System

ระบบ **AI Chief Marketing Officer** แบบ autonomous & data-driven — วิเคราะห์ข้อมูลการตลาด
omnichannel (Meta / TikTok / Affiliate / บูธ / ใบปลิว) หลายโปรเจคพร้อมกัน แล้ว **ออกคำสั่งโยกงบ**
+ **เสนอกลยุทธ์** โดยใช้ **Gemini** เป็นสมองเชิงกลยุทธ์

> ออกแบบตามแนวคิด **Agentic OS** (อ้างอิงจาก "Sureflow Agentic OS") — CMO คือหนึ่ง agent
> ที่คุณสั่งงานผ่าน Command Center ได้โดยตรง โครงสร้างเปิดให้เสียบ agent อื่น (Data Analyst,
> Researcher …) เพิ่มภายหลัง

---

## สถาปัตยกรรม

```
data/raw/*.csv|xlsx ──▶ ingest ──▶ metrics ──▶ analyze ──▶ budget ──▶ command_queue (รออนุมัติ)
                          │           │           │            │
                       (clean)   CAC/ROAS/     verdict      guardrails
                                 CPA/CVR    SCALE/CUT/KILL   (max shift, floor)
                                                  │
                                          gemini_advisor ──▶ report (Thai) ──▶ dashboard
```

| ในคลิป (Sureflow) | ในระบบนี้ |
|---|---|
| CMO agent (Market Voice) | `src/agent.py` — แชทสั่งได้ ตอบโดยอิงตัวเลขจริง |
| Chat with an agent | Dashboard `/api/chat` → Gemini + live context |
| Command Center | `web/index.html` (FastAPI) — dark theme |
| Schedule (working อัตโนมัติ) | `.github/workflows/cmo-command.yml` |
| Tasks / Command queue | `output/commands/latest.json` (PENDING_APPROVAL) |

---

## เริ่มใช้งาน

```bash
pip install -r requirements.txt

# 1) รันวิเคราะห์ (ใช้ข้อมูลใน data/raw/)
python -m src.main

# 2) แชทกับ CMO จาก CLI
python -m src.agent "ช่องทางไหนควรหยุดด่วน?"

# 3) เปิด Command Center dashboard
uvicorn src.dashboard:app --reload --port 8000
#    เปิด http://localhost:8000
```

### เปิดใช้ Gemini (ไม่บังคับ)
```bash
cp .env.example .env      # ใส่ GEMINI_API_KEY
export GEMINI_API_KEY=...  # หรือ set ผ่าน environment
```
ถ้าไม่มี key ระบบจะใช้ **fallback engine** ที่ให้ไอเดียอิงข้อมูลจริง (ไม่ล้ม CI)

---

## ข้อมูลนำเข้า

วางไฟล์ `.csv` / `.xlsx` ใน `data/raw/` คอลัมน์ที่รองรับ:

| บังคับ | ตัวเลข (เติม 0 อัตโนมัติถ้าไม่มี) |
|---|---|
| `Project`, `Channel` | `Spend`, `Impressions`, `Clicks`, `Leads`, `Conversions`, `Revenue`, `Foot_Traffic`, `Flyers_Distributed` |

เสริม: `Date`, `Campaign` — ดูตัวอย่างที่ `data/raw/sample_marketing_data.csv`

---

## ตัวชี้วัด & กติกาตัดสิน

- **ROAS** = Revenue / Spend · **CAC/CPA** = Spend / Conversions · **CVR** = Conversions / Leads
- **Booth_CVR** = Conversions / Foot_Traffic (คนเดินผ่านบูธ → ลูกค้า)
- คำตัดสิน: `SCALE` (ROAS สูง+volume พอ) · `CUT` · `KILL` (ROAS ต่ำ) · `WATCH` (sample เล็ก) · `HOLD`
- ปรับเกณฑ์ทั้งหมดได้ที่ `config/config.yaml`

## Guardrail การโยกงบ
- โยกได้สูงสุด `max_shift_pct` ต่อช่องทาง/รอบ · ห้ามต่ำกว่า `min_floor`
- budget-neutral: ตัดที่ไหน อัดที่ชนะ · ส่วนที่ redeploy ไม่หมด = กันเป็นงบสำรอง
- **ทุกคำสั่ง `PENDING_APPROVAL`** — ไม่มีเงินขยับจนกว่าคนจะอนุมัติ

---

## ทดสอบ
```bash
python -m pytest tests/ -q
```

## Roadmap
- [ ] ต่อ Meta/TikTok Ads API เพื่อ execute คำสั่งหลังอนุมัติ (adapter อยู่ที่ `/api/approve`)
- [ ] เพิ่ม agent: Data Analyst (Signal Layer), Researcher (Intel Gatherer)
- [ ] ดึงข้อมูลสดจาก Google Sheets / Ads API แทนไฟล์ static
