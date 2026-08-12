#!/bin/bash
# End-to-end: run a routine (real Telegram message), then simulate the CEO
# replying to it and check the advisor answers in the same thread.
set -e
cd "$HOME/commander-os/hub"
K=$(grep '^HERMES_API_KEY=' .env | cut -d= -f2-)
CHAT=$(grep '^TELEGRAM_CHAT_ID=' .env | cut -d= -f2-)
U=https://pennsylvania-influences-strength-ebooks.trycloudflare.com

echo "== 1) run routine #1 so a real report lands in Telegram =="
curl -s -m 900 -X POST -H "X-Hermes-API-Key: $K" "$U/api/routines/1/run" -o /tmp/fu_run.json
MID=$(python3 -c "
import json; r=json.load(open('/tmp/fu_run.json'))
print((r.get('delivery') or {}).get('message_ids', [0])[0])")
echo "  telegram message_id: $MID"

echo "== 2) the CEO replies to that exact message =="
curl -s -m 600 -X POST "$U/api/telegram/webhook" -H 'Content-Type: application/json' \
  -d "{\"update_id\":1,\"message\":{\"message_id\":90001,\"chat\":{\"id\":$CHAT},
       \"text\":\"ถ้าบังคับดาวน์ขั้นต่ำ 15% จะกระทบยอดปล่อยต่อวันประมาณเท่าไหร่ ตอบเป็นตัวเลข\",
       \"reply_to_message\":{\"message_id\":$MID}}}" -o /tmp/fu_reply.json
python3 -m json.tool < /tmp/fu_reply.json

echo "== 3) what the advisor actually answered =="
curl -s -m 40 -H "X-Hermes-API-Key: $K" "$U/api/followups?limit=1" | python3 -c "
import json, sys
f = json.load(sys.stdin)['followups'][0]
print('  seat:', f['dept'], '| linked run:', f['run_id'], '| ok:', f['ok'])
print('  Q:', f['question'])
print('  A:', f['answer'])
"
