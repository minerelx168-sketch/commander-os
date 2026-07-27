#!/bin/bash
# Live check: Z.AI (GLM) adapter + Claude Opus 5 + full provider readiness
set -e
cd "$HOME/commander-os/hub"
unset PYTHONPATH
sleep 3

echo "== 1) /api/state: all providers =="
curl -s http://localhost:8100/api/state > /tmp/state_zai.json
.venv/bin/python -c "
import json
s = json.load(open('/tmp/state_zai.json'))
for p in s['providers']:
    print(f\"  {p['key']:<10} {p['model']:<18} ready={p['ready']}\")
zai = next(p for p in s['providers'] if p['key'] == 'zai')
ant = next(p for p in s['providers'] if p['key'] == 'anthropic')
assert zai['ready'], 'zai key not detected'
assert ant['model'] == 'claude-opus-5', ant
"

echo "== 2) real GLM call via adapter =="
.venv/bin/python - <<'PY'
import sys
sys.path.insert(0, ".")
from app import llm
out = llm.chat("zai", "ตอบสั้นที่สุด", "ตอบคำว่า 'GLM พร้อม' เท่านั้น")
print("  provider:", out["provider"], "| model:", out["model"], "| ok:", out["ok"])
print("  reply:", out["text"][:80])
assert out["ok"] and out["provider"] == "zai", out
PY

echo "== 3) real Claude Opus 5 call via adapter =="
.venv/bin/python - <<'PY'
import sys
sys.path.insert(0, ".")
from app import llm
out = llm.chat("anthropic", "ตอบสั้นที่สุด", "ตอบคำว่า 'Opus5 พร้อม' เท่านั้น")
print("  provider:", out["provider"], "| model:", out["model"], "| ok:", out["ok"])
print("  reply:", out["text"][:80])
assert out["ok"] and out["model"] == "claude-opus-5", out
PY
echo "ZAI + OPUS5 WIRED OK"
