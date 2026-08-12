#!/bin/bash
# Why did the CEO's reply not link to its run? Show what ids we stored.
set -e
cd "$HOME/commander-os/hub"
K=$(grep '^HERMES_API_KEY=' .env | cut -d= -f2-)
U=https://pennsylvania-influences-strength-ebooks.trycloudflare.com
curl -s -m 40 -H "X-Hermes-API-Key: $K" "$U/api/routines/1/runs?limit=5" -o /tmp/runs.json
python3 - <<'PY'
import json
runs = json.load(open("/tmp/runs.json"))["runs"]
print("runs:", len(runs))
for r in runs:
    print(f"  run #{r['id']} {r['at_local']} | message_ids={r.get('message_ids')} "
          f"| delivery={ (r.get('delivery') or {}).get('message_ids') }")
PY
