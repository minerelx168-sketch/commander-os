#!/bin/bash
# The new system prompt triggers refusal. Which line? Add them back one at a time.
set -e
cd "$HOME/commander-os/hub"
unset PYTHONPATH
.venv/bin/python - <<'PY'
from app import llm, store

P = store.get_providers().get("cfo", "mock")
task = "สรุปสถานะการเงินของธุรกิจตู้ดอกไม้ ยังไม่มีข้อมูลจริงในระบบ"

BASE = (
    "คุณคือ CFO (Finance Radar) ที่ปรึกษาประจำตัว CEO\n"
    "ขอบเขตความเชี่ยวชาญของคุณ: การเงิน สภาพคล่อง ต้นทุน\n"
    "กฎเหล็ก: ตอบเฉพาะสิ่งที่มีหลักฐานรองรับ — ถ้างานอยู่นอกขอบเขต ให้บอกตรงๆ\n"
    "นี่คืองานประจำ (routine) ที่ CEO สั่งไว้ให้รายงานตามรอบเวลา "
    "จงรายงานเฉพาะสิ่งที่เปลี่ยนแปลงและสิ่งที่ต้องตัดสินใจ\n"
    "ตอบภาษาไทยทั้งหมด\n"
)

LINES = {
    "A: ceo-sees-path (มี **)":
        "\nสำคัญ: CEO ต้องเห็น **เส้นทางการคิด** ของคุณ ไม่ใช่แค่คำตอบ — เขาจะชี้กลับมาว่า "
        "ขั้นไหนคิดผิด แล้วให้คุณคิดใหม่จากจุดนั้น ดังนั้นทุกขั้นต้องเขียนให้ชี้ได้\n",
    "B: closed-road":
        "- ถ้ามีคำสั่งแก้จาก CEO ที่จุดใด ทางนั้นถือว่าปิดแล้ว ห้ามเดินซ้ำ ต้องคิดใหม่จากจุดนั้น "
        "แล้วรายงานใน fix_responses ทีละจุด — ตอบผลเดิมโดยเขียนใหม่ให้ดูต่าง ถือว่าไม่ได้แก้\n",
    "C: no-guessing":
        "- ห้ามเดาตัวเลข ถ้าไม่มีข้อมูลจริงให้ใส่ไว้ใน unknowns และบอกว่าต้องได้อะไรมาก่อน\n",
}

def probe(label, system):
    out = llm.chat(P, system, task, max_tokens=1200, attempts=1)
    print(f"  {label:32} {'OK  ' if out['ok'] else 'FAIL'} {out['text'][:60]}")
    return out["ok"]

print("provider:", P)
probe("base only", BASE)
acc = BASE
for label, line in LINES.items():
    probe(f"base + {label}", BASE + line)

print("\n-- is it the ** markup? --")
a_plain = LINES["A: ceo-sees-path (มี **)"].replace("**", "")
probe("A without **", BASE + a_plain)
PY
