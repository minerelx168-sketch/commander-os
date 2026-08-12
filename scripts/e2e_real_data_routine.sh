#!/bin/bash
# Prove the full loop: backend pushes realistic lending data -> routine analyses it.
set -e
cd "$HOME/commander-os/hub"
K=$(grep '^HERMES_API_KEY=' .env | cut -d= -f2-)
U=https://pennsylvania-influences-strength-ebooks.trycloudflare.com
IK=$(curl -s -m 30 -H "X-Hermes-API-Key: $K" "$U/api/sources" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['sources'][0]['ingest_key'])")

echo "== 1) backend pushes a realistic batch =="
curl -s -m 30 -X POST "$U/api/ingest" -H "X-Source-Key: $IK" \
  -H 'Content-Type: application/json' -d '[
  {"date":"2026-08-12","new_cases":14,"approved":9,"rejected":5,"disbursed_thb":268000,"avg_ticket_thb":29778},
  {"date":"2026-08-12","collected_thb":184500,"due_thb":241000,"collection_rate":0.766},
  {"date":"2026-08-12","overdue_1_30":11,"overdue_31_60":4,"overdue_60_plus":3,"npl_thb":96500,"npl_ratio":0.081},
  {"date":"2026-08-11","new_cases":17,"approved":12,"rejected":5,"disbursed_thb":341000,"avg_ticket_thb":28417},
  {"date":"2026-08-11","collected_thb":203000,"due_thb":238000,"collection_rate":0.853}
]' | python3 -c "import json,sys; j=json.load(sys.stdin); print('  ->', j['project'], '| rows', j['rows'])"

echo "== 2) confirm the advisors will see it =="
curl -s -m 30 -H "X-Hermes-API-Key: $K" "$U/api/sources" \
  | python3 -c "import json,sys; s=json.load(sys.stdin)['sources'][0]; print('  rows:', s['rows'], '| sample:', s['sample'][:110], '…')"

echo "== 3) run the routine for real =="
RID=$(curl -s -m 30 -X POST "$U/api/routines" -H "X-Hermes-API-Key: $K" \
  -H 'Content-Type: application/json' \
  -d '{"task":"วิเคราะห์คุณภาพพอร์ตสินเชื่อล่าสุด: อัตราอนุมัติ, collection rate, NPL และบอกสิ่งที่ต้องตัดสินใจวันนี้","frequency":"daily","time":"09:00","seats":["cfo","datalyst"],"project":"CloudforCash"}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
echo "  routine #$RID"

curl -s -m 900 -X POST -H "X-Hermes-API-Key: $K" "$U/api/routines/$RID/run" -o /tmp/real_run.json
python3 - <<'PY'
import json
r = json.load(open("/tmp/real_run.json"))
print("  delivery:", r.get("delivery"))
for k, v in r["results"].items():
    print(f"\n  --- {k} [{v['provider']}] ok={v['ok']} ---")
    print("  " + v["text"][:600].replace("\n", "\n  "))
PY

echo
echo "== 4) cleanup the test routine (keep the data) =="
curl -s -m 30 -X DELETE -H "X-Hermes-API-Key: $K" "$U/api/routines/$RID" -o /dev/null -w "  deleted: %{http_code}\n"
