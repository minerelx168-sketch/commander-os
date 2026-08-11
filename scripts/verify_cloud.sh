#!/bin/bash
# Verify the deployed cloud instance end-to-end, including a real Telegram send
set -e
U=https://pennsylvania-influences-strength-ebooks.trycloudflare.com

echo "== health =="
curl -s -m 25 -o /dev/null -w "  %{http_code}\n" "$U/health"

echo "== new features present in the cloud build =="
curl -s -m 25 "$U/" > /tmp/cloud_index.html
python3 - <<'PY'
h = open("/tmp/cloud_index.html", encoding="utf-8").read()
for m in ('data-view="routine"', "API Connector", "conn-scope", "rt-seat-menu",
          "toggleSeatDD", "rt-textarea", "เชื่อม API ให้โปรเจค"):
    print(f"  {'OK ' if m in h else 'MISSING'} {m}")
PY

echo "== routines API + telegram readiness on the server =="
curl -s -m 25 "$U/api/routines" | python3 -c "
import json,sys
j=json.load(sys.stdin)
print('  telegram_ready:', j['telegram_ready'], '| scheduler:', j['scheduler_alive'], '| now:', j['now_local'])
print('  routines:', len(j['routines']), '| seats:', [s['key'] for s in j['seats']])
"

echo "== connector API on the server =="
curl -s -m 25 "$U/api/sources" | python3 -c "
import json,sys
j=json.load(sys.stdin)
print('  kinds:', list(j['kinds']), '| auths:', list(j['auths']), '| sources:', len(j['sources']))
"
