#!/bin/bash
# Claude refused the routine prompt (stop_reason=refusal). Which part triggers
# it? Bisect: system prompt alone, schema alone, then together.
set -e
cd "$HOME/commander-os/hub"
unset PYTHONPATH
.venv/bin/python - <<'PY'
from app import llm, routines, store

P = store.get_providers().get("cfo", "mock")
print("provider:", P)

sys_new = routines._seat_prompt("cfo")
sys_old = (
    "คุณคือ CFO (Finance Radar) ที่ปรึกษาประจำตัว CEO\n"
    "ตอบภาษาไทย ไม่เกิน 10 บรรทัด"
)
task = "สรุปสถานะการเงินของธุรกิจตู้ดอกไม้ ยังไม่มีข้อมูลจริงในระบบ"

def probe(label, system, user, max_tokens=1500):
    out = llm.chat(P, system, user, max_tokens=max_tokens, attempts=1)
    state = "OK" if out["ok"] else "FAIL"
    print(f"  {label:34} {state} ({len(out['text'])} chars) {out['text'][:70]}")
    return out["ok"]

print("\n-- bisecting --")
probe("old system, plain task", sys_old, task)
probe("new system, plain task", sys_new, task)
probe("old system + schema", sys_old, task + "\n\n" + routines.ROUTINE_SCHEMA)
probe("new system + schema", sys_new, task + "\n\n" + routines.ROUTINE_SCHEMA)
PY
