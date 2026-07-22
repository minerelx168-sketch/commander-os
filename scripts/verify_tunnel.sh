#!/bin/bash
# Verify the public tunnel end-to-end with a live consult
set -e
U=https://reviewer-utils-shipping-authors.trycloudflare.com
curl -s -m 240 -X POST "$U/api/consult" -H 'Content-Type: application/json' \
  -d '{"question":"เดโม: สรุปสั้นๆ ธุรกิจตู้กดดอกไม้ควรระวังอะไรที่สุดตอนนี้"}' \
  | python3 -c "
import json, sys
j = json.load(sys.stdin)
for k, a in j['answers'].items():
    print(f\"{k} [{a['provider']}] ok={a['ok']}:\", a['text'][:100].replace(chr(10), ' '))
"
