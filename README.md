# Commander OS 🧠

AI Commander Operating System — **AI CEO** รับคำสั่งจากเจ้าของ แตกงาน มอบหมายให้ AI ระดับ
C-level ประจำแผนก แล้วรวมผลรายงานกลับ ทุก action ที่กระทบของจริงต้องผ่านการอนุมัติ
(Human-in-the-Loop) ผ่าน **Telegram**

## Phase 1 scope

- **CEO agent** — วางแผน (task decomposition), route ให้แผนก, สรุปรายงานภาษาไทย
- **CMO agent** — วิเคราะห์ Meta Ads ผ่าน [meta-ads-agent](https://github.com/minerelx168-sketch/MetaAdsOptimization) REST API
- **HITL approvals** — LangGraph `interrupt()` + คิวอนุมัติ + ปุ่ม ✅/❌ ใน Telegram
- **Cost tracker** — บันทึก token/บาท ทุก LLM call ลง `cost_entries`
- **Daily report** — สรุปงาน+ค่าใช้จ่ายส่ง Telegram (`python -m app.jobs.daily_report`)

```
Owner (Telegram/API)
   └─▶ CEO (plan) ─▶ CMO (analyze via meta-ads-agent) ─▶ [interrupt: รออนุมัติ]
                                                             │ approve/reject
                                                             ▼
                                          CEO (synthesize) ─▶ รายงานภาษาไทย ─▶ Telegram
```

## Quick start

```bash
# 1. Postgres
docker compose up -d postgres

# 2. Backend (MOCK mode — no keys needed)
cd backend
cp .env.example .env
bash scripts/setup_venv.sh
source .venv/bin/activate
uvicorn app.main:app --port 8100

# 3. Smoke test (in another shell)
bash scripts/smoke.sh
```

## Tests

```bash
cd backend && source .venv/bin/activate && python -m pytest tests/ -v
```

## Going live

แก้ `backend/.env`:

| ตัวแปร | ค่า |
|---|---|
| `LLM_MOCK=0` + `ANTHROPIC_API_KEY` | เปิดสมองจริง (Claude) |
| `TELEGRAM_MOCK=0` + `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | bot จริง (คุยกับ @BotFather, หา chat_id จาก @userinfobot) |
| `META_AGENT_MOCK=0` + `META_AGENT_URL` | ชี้ไปที่ meta-ads-agent ที่รันอยู่ (:8000) |

จากนั้นพิมพ์หาบอทใน Telegram ได้เลย เช่น *"วิเคราะห์แคมเปญวันนี้ มีอะไรต้องปรับไหม"*
หรือ `/report` เพื่อดูรายงานประจำวัน

## Roadmap

- Phase 2: Command Center dashboard (Next.js + WebSocket) + CFO
- Phase 3: Voice (Jarvis mode — Whisper STT + Thai TTS) + COO
- Phase 4: Wake word, CTO/CSO, model routing

สถาปัตยกรรมเต็ม: `~/.hermes/plans/2026-07-19_ai-commander-os-architecture.md`
