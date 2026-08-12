#!/bin/bash
# Prove multi-backend attribution: two projects push to the SAME endpoint with
# different keys, and the hub files each one under the right project.
set -e
U="${1:-http://localhost:8100}"
cd "$HOME/commander-os/hub"
HK=$(grep '^HERMES_API_KEY=' .env | cut -d= -f2-)
H=(-H "X-Hermes-API-Key: $HK" -H 'Content-Type: application/json')
sleep 2

mk() {  # project name -> ingest_key
  curl -s -m 30 "${H[@]}" -X POST "$U/api/sources" \
    -d "{\"project\":\"$1\",\"name\":\"$2\",\"kind\":\"webhook\",\"auth\":\"none\"}" \
    | python3 -c "import json,sys; s=json.load(sys.stdin); print(s['id'], s['ingest_key'])"
}

echo "== 1) issue a key per project =="
read -r A_ID A_KEY < <(mk "Cloudforcashpay" "Cloudforcashpay backend")
read -r B_ID B_KEY < <(mk "FlowerVending" "ตู้ดอกไม้ backend")
echo "  Cloudforcashpay -> #$A_ID  ${A_KEY:0:14}…"
echo "  FlowerVending   -> #$B_ID  ${B_KEY:0:14}…"

echo "== 2) both backends POST to the SAME url, differing only by key =="
curl -s -m 30 -X POST "$U/api/ingest" -H "X-Source-Key: $A_KEY" -H 'Content-Type: application/json' \
  -d '[{"txn_id":"CFC-9001","amount":15900,"status":"paid"}]' \
  | python3 -c "import json,sys; j=json.load(sys.stdin); print('  key A ->', j['project'], '|', j['source'], '| rows', j['rows'])"
curl -s -m 30 -X POST "$U/api/ingest" -H "X-Source-Key: $B_KEY" -H 'Content-Type: application/json' \
  -d '[{"machine":"EKM-02","stems_sold":37,"revenue":2590}]' \
  | python3 -c "import json,sys; j=json.load(sys.stdin); print('  key B ->', j['project'], '|', j['source'], '| rows', j['rows'])"

echo "== 3) an unknown key is refused (no silent misfiling) =="
curl -s -m 30 -o /dev/null -w '  bogus key -> %{http_code}\n' \
  -X POST "$U/api/ingest" -H 'X-Source-Key: cx_fake' -H 'Content-Type: application/json' -d '[{"x":1}]'

echo "== 4) each project sees only its own data =="
for P in Cloudforcashpay FlowerVending; do
  curl -s -m 30 "${H[@]}" "$U/api/sources?project=$P" | python3 -c "
import json,sys
ss=json.load(sys.stdin)['sources']
for s in ss:
    print(f\"  $P: {s['name']} rows={s['rows']} sample={(s.get('sample') or '')[:60]}\")
"
done

echo "== 5) cleanup =="
for ID in $A_ID $B_ID; do
  curl -s -m 30 "${H[@]}" -X DELETE "$U/api/sources/$ID" -o /dev/null -w "  deleted #$ID: %{http_code}\n"
done
