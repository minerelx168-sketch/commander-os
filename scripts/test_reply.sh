#!/bin/bash
# Simulate the CEO replying to the LATEST real report and show what comes back.
set -e
cd "$HOME/commander-os/hub"
K=$(grep '^HERMES_API_KEY=' .env | cut -d= -f2-)
CHAT=$(grep '^TELEGRAM_CHAT_ID=' .env | cut -d= -f2-)
U=https://pennsylvania-influences-strength-ebooks.trycloudflare.com

MID=$(curl -s -m 40 -H "X-Hermes-API-Key: $K" "$U/api/routines/1/runs?limit=1" \
  | python3 -c "import json,sys; r=json.load(sys.stdin)['runs'][0]; print((r.get('message_ids') or [0])[0])")
echo "replying to telegram message_id: $MID"

Q="${1:-ถ้าบังคับดาวน์ขั้นต่ำ 15% จะกระทบยอดปล่อยต่อวันประมาณเท่าไหร่ ตอบเป็นตัวเลข}"
curl -s -m 600 -X POST "$U/api/telegram/webhook" -H 'Content-Type: application/json' \
  -d "$(python3 -c "
import json, sys
print(json.dumps({'update_id': 99, 'message': {
  'message_id': 90100, 'chat': {'id': int('$CHAT')},
  'text': '''$Q''',
  'reply_to_message': {'message_id': $MID}}}, ensure_ascii=False))")" -o /tmp/fu2.json

python3 - <<'PY'
import json
j = json.load(open("/tmp/fu2.json"))
print("handled:", j.get("handled"), "| seat:", j.get("dept"),
      "| linked_run:", j.get("linked_run"), "| exact_reply:", j.get("exact_reply"))
print("delivery:", j.get("delivery"))
PY
