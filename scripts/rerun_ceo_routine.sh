#!/bin/bash
# Re-run the CEO's own routine #1 (data already pushed) and show every seat.
set -e
cd "$HOME/commander-os/hub"
K=$(grep '^HERMES_API_KEY=' .env | cut -d= -f2-)
U=https://pennsylvania-influences-strength-ebooks.trycloudflare.com

echo "== data currently available to the advisors =="
curl -s -m 30 -H "X-Hermes-API-Key: $K" "$U/api/sources" \
  | python3 -c "import json,sys; s=json.load(sys.stdin)['sources'][0]; print('  rows:', s['rows'], '| status:', s['last_status'])"

echo "== running routine #1 =="
curl -s -m 900 -X POST -H "X-Hermes-API-Key: $K" "$U/api/routines/1/run" -o /tmp/ceo_run2.json
python3 - <<'PY'
import json
r = json.load(open("/tmp/ceo_run2.json"))
print("  at:", r["at_local"], "| telegram:", r.get("delivery"))
for k, v in r["results"].items():
    print(f"\n{'='*72}\n{k.upper()} [{v['provider']}] ok={v['ok']}  ({len(v['text'])} chars)\n{'='*72}")
    print(v["text"] or "(ว่างเปล่า)")
PY
