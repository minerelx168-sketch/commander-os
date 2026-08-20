#!/bin/bash
# The clause bisect contradicted itself (short clause refused, longer one passed,
# neutral rewrite refused). Test whether refusal is wording-dependent at all, or
# just intermittent: same prompt, several times.
set -e
cd "$HOME/commander-os/hub"
unset PYTHONPATH
.venv/bin/python - <<'PY'
import time
from app import llm, store

P = store.get_providers().get("cfo", "mock")
task = "สรุปสถานะการเงินของธุรกิจตู้ดอกไม้ ยังไม่มีข้อมูลจริงในระบบ"
BASE = ("คุณคือ CFO (Finance Radar) ที่ปรึกษาประจำตัว CEO\n"
        "กฎเหล็ก: ตอบเฉพาะสิ่งที่มีหลักฐานรองรับ\nตอบภาษาไทยทั้งหมด\n")
CLAUSE = "\nสำคัญ: CEO ต้องเห็นเส้นทางการคิดของคุณ ไม่ใช่แค่คำตอบ\n"

print("provider:", P)
print("\n-- same prompt (base only), 5 times --")
ok = 0
for i in range(5):
    out = llm.chat(P, BASE, task, max_tokens=900, attempts=1)
    ok += out["ok"]
    print(f"  {i+1}: {'OK' if out['ok'] else 'REFUSED'}")
    time.sleep(1)
print(f"  base: {ok}/5 ok")

print("\n-- same prompt (base + clause), 5 times --")
ok2 = 0
for i in range(5):
    out = llm.chat(P, BASE + CLAUSE, task, max_tokens=900, attempts=1)
    ok2 += out["ok"]
    print(f"  {i+1}: {'OK' if out['ok'] else 'REFUSED'}")
    time.sleep(1)
print(f"  base+clause: {ok2}/5 ok")
PY
