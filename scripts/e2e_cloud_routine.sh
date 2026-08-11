#!/bin/bash
# Live on the cloud: create a routine, run it, confirm Telegram delivery
set -e
U=https://pennsylvania-influences-strength-ebooks.trycloudflare.com

echo "== create routine on the server =="
RID=$(curl -s -m 30 -X POST "$U/api/routines" -H 'Content-Type: application/json' \
  -d '{"task":"สรุปสถานะธุรกิจสั้นๆ และบอกสิ่งที่ต้องตัดสินใจวันนี้","frequency":"daily","time":"09:00","seats":["cfo"]}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
echo "  routine id: $RID"

echo "== run it (real LLM on the VM, real Telegram) =="
curl -s -m 600 -X POST "$U/api/routines/$RID/run" -o /tmp/cloud_run.json
python3 - <<'PY'
import json
r = json.load(open("/tmp/cloud_run.json"))
print("  run:", r["at_local"], "| delivery:", r.get("delivery"))
for k, v in r["results"].items():
    print(f"  {k} [{v['provider']}] ok={v['ok']}: {v['text'][:120]}")
PY

echo "== cleanup the test routine =="
curl -s -m 30 -X DELETE "$U/api/routines/$RID" -o /dev/null -w "  deleted: %{http_code}\n"
