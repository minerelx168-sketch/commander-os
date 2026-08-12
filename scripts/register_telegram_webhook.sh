#!/bin/bash
# Register the Telegram webhook so replies reach the hub, and verify it stuck.
set -e
cd "$HOME/commander-os/hub"
K=$(grep '^HERMES_API_KEY=' .env | cut -d= -f2-)
U=https://pennsylvania-influences-strength-ebooks.trycloudflare.com

echo "== register =="
curl -s -m 40 -X POST "$U/api/telegram/webhook/register" \
  -H "X-Hermes-API-Key: $K" -H 'Content-Type: application/json' \
  -d "{\"url\":\"$U/api/telegram/webhook\"}" | python3 -m json.tool

echo "== confirm with Telegram =="
curl -s -m 40 -H "X-Hermes-API-Key: $K" "$U/api/telegram/status" | python3 -c "
import json, sys
j = json.load(sys.stdin)
w = j['webhook'].get('result', {})
print('  ready:', j['ready'], '| bot:', j['bot'])
print('  url:', w.get('url'))
print('  pending:', w.get('pending_update_count'), '| last_error:', w.get('last_error_message', '-'))
"
