#!/bin/bash
# Test the CEO's own routine #1 with a data batch that matches what its prompt
# actually asks for (Volume, Collection, Delinquency, Bad Debt + the fields the
# FPD / CEI / Approval-to-Bad-Debt formulas need).
set -e
cd "$HOME/commander-os/hub"
K=$(grep '^HERMES_API_KEY=' .env | cut -d= -f2-)
U=https://pennsylvania-influences-strength-ebooks.trycloudflare.com
H=(-H "X-Hermes-API-Key: $K" -H 'Content-Type: application/json')

IK=$(curl -s -m 30 -H "X-Hermes-API-Key: $K" "$U/api/sources" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['sources'][0]['ingest_key'])")

echo "== 1) clear the old sample so nothing stale leaks in =="
curl -s -m 30 -X POST "${H[@]}" "$U/api/sources/1/clear" -o /dev/null -w "  cleared: %{http_code}\n"

echo "== 2) push a week of MotalVIP + Cloudforcashpay style data =="
curl -s -m 30 -X POST "$U/api/ingest" -H "X-Source-Key: $IK" \
  -H 'Content-Type: application/json' -d '[
 {"period":"2026-08-12","source":"cloudforcashpay","new_approved_cases":9,"applications":14,"disbursed_thb":268000,
  "due_thb":241000,"collected_thb":184500,"collection_rate":0.766,
  "late_1_30_cases":11,"late_31_60_cases":4,"late_60plus_cases":3,
  "npl_thb":96500,"npl_ratio":0.081,
  "first_payment_due_cases":21,"first_payment_missed_cases":4,
  "zero_down_share":0.62},
 {"period":"2026-08-11","source":"cloudforcashpay","new_approved_cases":12,"applications":17,"disbursed_thb":341000,
  "due_thb":238000,"collected_thb":203000,"collection_rate":0.853,
  "late_1_30_cases":8,"late_31_60_cases":3,"late_60plus_cases":3,
  "npl_thb":91200,"npl_ratio":0.077,
  "first_payment_due_cases":19,"first_payment_missed_cases":2,
  "zero_down_share":0.58},
 {"period":"2026-08-10","source":"motalvip","new_approved_cases":11,"applications":15,"disbursed_thb":299000,
  "due_thb":230000,"collected_thb":201000,"collection_rate":0.874,
  "late_1_30_cases":7,"late_31_60_cases":2,"late_60plus_cases":2,
  "npl_thb":84000,"npl_ratio":0.071,
  "first_payment_due_cases":18,"first_payment_missed_cases":2,
  "zero_down_share":0.55},
 {"period":"2026-08-09","source":"motalvip","new_approved_cases":10,"applications":13,"disbursed_thb":281000,
  "due_thb":226000,"collected_thb":199500,"collection_rate":0.883,
  "late_1_30_cases":6,"late_31_60_cases":2,"late_60plus_cases":2,
  "npl_thb":79000,"npl_ratio":0.068,
  "first_payment_due_cases":17,"first_payment_missed_cases":1,
  "zero_down_share":0.51},
 {"period":"week_summary_2026-W33","source":"combined","new_approved_cases":42,"applications":59,
  "disbursed_thb":1189000,"due_thb":935000,"collected_thb":788000,"collection_rate":0.843,
  "late_1_30_cases":32,"npl_thb":96500,"npl_ratio":0.081,
  "first_payment_due_cases":75,"first_payment_missed_cases":9,"zero_down_share":0.57}
]' | python3 -c "import json,sys; j=json.load(sys.stdin); print('  ->', j['project'], '| rows', j['rows'])"

echo "== 3) re-enable the CEO's routine and run it =="
curl -s -m 30 -X POST "${H[@]}" "$U/api/routines/1/toggle" -d '{"enabled":true}' -o /dev/null
curl -s -m 900 -X POST -H "X-Hermes-API-Key: $K" "$U/api/routines/1/run" -o /tmp/ceo_run.json

python3 - <<'PY'
import json
r = json.load(open("/tmp/ceo_run.json"))
print("  run", r["at_local"], "| telegram:", r.get("delivery"))
for k, v in r["results"].items():
    print(f"\n{'='*70}\n{k.upper()} [{v['provider']}] ok={v['ok']}\n{'='*70}")
    print(v["text"])
PY
