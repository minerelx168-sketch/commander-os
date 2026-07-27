#!/bin/bash
# Live: verify Manus is wired through the hub's llm adapter end-to-end
set -e
cd "$HOME/commander-os/hub"
unset PYTHONPATH
sleep 3

echo "== 1) provider readiness via /api/state =="
curl -s http://localhost:8100/api/state | .venv/bin/python -c "
import json, sys
s = json.load(sys.stdin)
m = next(p for p in s['providers'] if p['key'] == 'manus')
print('manus:', m['label'], '| model:', m['model'], '| ready:', m['ready'])
assert m['ready'], 'manus key not detected'
"

echo "== 2) direct adapter call (llm.chat provider=manus, real task API) =="
.venv/bin/python - <<'PY'
import sys
sys.path.insert(0, ".")
from app import llm
out = llm.chat("manus", "คุณคือผู้ช่วยทดสอบระบบ ตอบสั้นๆ", "ตอบคำว่า 'เชื่อมต่อสำเร็จ' เป็นภาษาไทยคำเดียว")
print("provider:", out["provider"], "| model:", out["model"], "| ok:", out["ok"])
print("reply:", out["text"][:200])
assert out["ok"] and out["provider"] == "manus", out
PY
echo "MANUS WIRED OK"
