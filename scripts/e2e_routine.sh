#!/bin/bash
# Live E2E: create a routine, run it with real advisors, confirm Telegram + filing
set -e
H=http://localhost:8100
sleep 4

echo "== state =="
curl -s "$H/api/routines" | python3 -c "
import json,sys
j=json.load(sys.stdin)
print('  telegram_ready:', j['telegram_ready'], '| scheduler:', j['scheduler_alive'], '| now:', j['now_local'])
print('  seats:', [s['key'] for s in j['seats']])
"

echo "== create routine (CFO+Datalyst, daily 09:00 UTC+7) =="
RID=$(curl -s -X POST "$H/api/routines" -H 'Content-Type: application/json' \
  -d '{"task":"สรุปสถานะการเงินและตัวเลขสำคัญของธุรกิจตู้ดอกไม้ ชี้สิ่งที่เปลี่ยนและสิ่งที่ต้องตัดสินใจ","frequency":"daily","time":"09:00","seats":["cfo","datalyst"]}' \
  | python3 -c "import json,sys; j=json.load(sys.stdin); print(j['id']); import sys as s; print('  next_at:', j['next_at'], file=s.stderr)")
echo "  routine id: $RID"

echo "== run it now (real LLMs) =="
curl -s -m 600 -X POST "$H/api/routines/$RID/run" -o /tmp/rt_run.json
python3 - <<'PY'
import json
r = json.load(open("/tmp/rt_run.json"))
print("  run id:", r["id"], "| at:", r["at_local"], "| delivery:", r.get("delivery"))
for k, v in r["results"].items():
    print(f"  --- {k} [{v['provider']}] ok={v['ok']} ---")
    print("   ", v["text"][:160].replace("\n", " / "))
PY

echo "== filed into the document library? =="
curl -s "$H/api/docs" | python3 -c "
import json,sys
j=json.load(sys.stdin)
rt=[d for d in j['documents'] if d['source']=='routine']
print('  routine docs:', len(rt))
print('  latest:', rt[0]['name'] if rt else '-')
"
