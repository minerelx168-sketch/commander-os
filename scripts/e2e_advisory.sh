#!/bin/bash
# Live E2E: 3-round advisory board with real LLMs
set -e
H=http://localhost:8100
sleep 3
curl -s -m 4 "$H/health" > /dev/null || { echo "hub not up"; exit 1; }
curl -s -m 300 -X POST "$H/api/consult" -H 'Content-Type: application/json' \
  -d '{"question":"มีคนเสนอซื้อกิจการตู้กดดอกไม้ของฉันในราคา 2 ล้านบาท ขายดีหรือทำต่อ?"}' \
  -o /tmp/consult_live.json
python3 - <<'PY'
import json
j = json.load(open("/tmp/consult_live.json"))
print("consult id:", j["id"], "| q:", j["question"][:50])
for rnd in ("opinions", "cross_exam", "verdicts"):
    print(f"\n===== {rnd} =====")
    for k, a in j[rnd].items():
        print(f"--- {k} [{a['provider']}] ok={a['ok']} ---")
        print(a["text"][:180].replace("\n", " / "))
PY
