#!/bin/bash
# Create the real Cloudforcashpay connector on the cloud and print its key.
set -e
U=https://pennsylvania-influences-strength-ebooks.trycloudflare.com
cd "$HOME/commander-os/hub"
HK=$(grep '^HERMES_API_KEY=' .env | cut -d= -f2-)

# Reuse the connector if it already exists, so re-running does not pile up keys.
EXIST=$(curl -s -m 30 -H "X-Hermes-API-Key: $HK" "$U/api/sources?project=Cloudforcashpay" \
  | python3 -c "import json,sys; s=json.load(sys.stdin)['sources']; print(s[0]['ingest_key'] if s else '')")

if [ -z "$EXIST" ]; then
  EXIST=$(curl -s -m 30 -X POST "$U/api/sources" \
    -H "X-Hermes-API-Key: $HK" -H 'Content-Type: application/json' \
    -d '{"project":"Cloudforcashpay","name":"Cloudforcashpay Backend","kind":"webhook","auth":"none"}' \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['ingest_key'])")
fi

echo "Project : Cloudforcashpay"
echo "Endpoint: POST $U/api/ingest"
echo "Header  : X-Source-Key: $EXIST"
echo
echo "--- live test ---"
curl -s -m 30 -X POST "$U/api/ingest" -H "X-Source-Key: $EXIST" \
  -H 'Content-Type: application/json' \
  -d '[{"txn_id":"TEST-0001","amount":1,"note":"connection test"}]' \
  | python3 -m json.tool
