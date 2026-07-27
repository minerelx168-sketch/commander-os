#!/bin/bash
# Assign Manus to Datalyst and run a live 3-round consult through the board
set -e
H=http://localhost:8100
curl -s -X PUT "$H/api/dept/datalyst/provider" -H 'Content-Type: application/json' \
  -d '{"provider":"manus"}' -o /dev/null
curl -s "$H/api/state" | python3 -c "
import json, sys
s = json.load(sys.stdin)
for d in s['depts']:
    print(d['key'], '->', d['provider'], '(ready)' if d['provider_ready'] else '(NO KEY)')
"
echo "== live consult (datalyst answers via Manus agent) =="
curl -s -m 600 -X POST "$H/api/consult" -H 'Content-Type: application/json' \
  -d '{"question":"ยอดขายตู้ดอกไม้ตกจากวันละ 4,500 เหลือ 3,200 บาทใน 2 สัปดาห์ ควรทำอย่างไร"}' \
  -o /tmp/consult_manus.json
python3 - <<'PY'
import json
j = json.load(open("/tmp/consult_manus.json"))
print("consult id:", j["id"])
for rnd in ("opinions", "cross_exam", "verdicts"):
    a = j[rnd]["datalyst"]
    print(f"--- {rnd}: datalyst [{a['provider']}] ok={a['ok']} ---")
    print(a["text"][:150].replace("\n", " / "))
others_ok = all(j[r][k]["ok"] for r in ("opinions", "cross_exam", "verdicts")
                for k in ("cmo", "cfo", "coo"))
print("other advisors all ok:", others_ok)
PY
