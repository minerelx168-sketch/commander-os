#!/bin/bash
# Live check that HERMES_API_KEY is enforced and both header forms work.
# Target defaults to localhost; pass a base URL to test the cloud instance.
set -e
U="${1:-http://localhost:8100}"
cd "$HOME/commander-os/hub"
KEY=$(grep '^HERMES_API_KEY=' .env | cut -d= -f2-)
sleep 2

code() { curl -s -o /dev/null -w '%{http_code}' -m 25 "$@"; }

echo "target: $U"
echo "  /health            (open)      -> $(code "$U/health")"
echo "  /                  (open)      -> $(code "$U/")"
echo "  /api/state  no key             -> $(code "$U/api/state")"
echo "  /api/state  X-Hermes-API-Key   -> $(code -H "X-Hermes-API-Key: $KEY" "$U/api/state")"
echo "  /api/state  Bearer             -> $(code -H "Authorization: Bearer $KEY" "$U/api/state")"
echo "  /api/state  wrong key          -> $(code -H "X-Hermes-API-Key: wrong" "$U/api/state")"
echo "  /api/routines no key           -> $(code "$U/api/routines")"
echo "  /api/routines Bearer           -> $(code -H "Authorization: Bearer $KEY" "$U/api/routines")"
echo "  /api/line/webhook (exempt)     -> $(code -X POST -H 'Content-Type: application/json' -d '{"events":[]}' "$U/api/line/webhook")"
