#!/bin/bash
# Line A triggers refusal and it is not the ** markup. Which clause?
set -e
cd "$HOME/commander-os/hub"
unset PYTHONPATH
.venv/bin/python - <<'PY'
from app import llm, store

P = store.get_providers().get("cfo", "mock")
task = "สรุปสถานะการเงินของธุรกิจตู้ดอกไม้ ยังไม่มีข้อมูลจริงในระบบ"
BASE = (
    "คุณคือ CFO (Finance Radar) ที่ปรึกษาประจำตัว CEO\n"
    "กฎเหล็ก: ตอบเฉพาะสิ่งที่มีหลักฐานรองรับ\n"
    "ตอบภาษาไทยทั้งหมด\n"
)

CLAUSES = {
    "1 sees-the-path only":
        "\nสำคัญ: CEO ต้องเห็นเส้นทางการคิดของคุณ ไม่ใช่แค่คำตอบ\n",
    "2 + he-points-back":
        "\nสำคัญ: CEO ต้องเห็นเส้นทางการคิดของคุณ ไม่ใช่แค่คำตอบ — "
        "เขาจะชี้กลับมาว่าขั้นไหนคิดผิด\n",
    "3 + rethink-from-there":
        "\nสำคัญ: CEO ต้องเห็นเส้นทางการคิดของคุณ ไม่ใช่แค่คำตอบ — "
        "เขาจะชี้กลับมาว่าขั้นไหนคิดผิด แล้วให้คุณคิดใหม่จากจุดนั้น\n",
    "4 full line":
        "\nสำคัญ: CEO ต้องเห็นเส้นทางการคิดของคุณ ไม่ใช่แค่คำตอบ — "
        "เขาจะชี้กลับมาว่าขั้นไหนคิดผิด แล้วให้คุณคิดใหม่จากจุดนั้น "
        "ดังนั้นทุกขั้นต้องเขียนให้ชี้ได้\n",
    "5 neutral rewrite":
        "\nรายงานของคุณต้องแสดงลำดับการคิดให้ครบทุกขั้น เพื่อให้ CEO ตรวจสอบและ"
        "ให้ความเห็นกลับได้เป็นรายขั้น\n",
}

print("provider:", P)
for label, clause in CLAUSES.items():
    out = llm.chat(P, BASE + clause, task, max_tokens=900, attempts=1)
    print(f"  {label:26} {'OK  ' if out['ok'] else 'FAIL'} {out['text'][:55]}")
PY
