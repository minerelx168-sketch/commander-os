#!/bin/bash
# Set default providers per dept (based on keys available in hub/.env) and verify state
set -e
H=http://localhost:8100
for pair in cmo:gemini cfo:anthropic coo:gemini datalyst:gemini; do
  d="${pair%%:*}"; p="${pair##*:}"
  curl -s -X PUT "$H/api/dept/$d/provider" -H 'Content-Type: application/json' \
    -d "{\"provider\":\"$p\"}" -o /dev/null
done
curl -s "$H/api/state" | python3 -c "
import json, sys
s = json.load(sys.stdin)
for d in s['depts']:
    print(d['key'], '| provider:', d['provider'], '| key ready:', d['provider_ready'], '| service online:', d['online'])
"
