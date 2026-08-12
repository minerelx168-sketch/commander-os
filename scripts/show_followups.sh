#!/bin/bash
# Read back the follow-up the advisor produced for the CEO's reply.
set -e
cd "$HOME/commander-os/hub"
K=$(grep '^HERMES_API_KEY=' .env | cut -d= -f2-)
U=https://pennsylvania-influences-strength-ebooks.trycloudflare.com
curl -s -m 40 -H "X-Hermes-API-Key: $K" "$U/api/followups?limit=3" -o /tmp/fu_list.json
python3 - <<'PY'
import json
fs = json.load(open("/tmp/fu_list.json"))["followups"]
print("followups recorded:", len(fs))
for f in fs:
    print(f"\n#{f['id']} seat={f['dept']} linked_run={f['run_id']} ok={f['ok']} at={f['at'][:19]}")
    print("  Q:", f["question"][:120])
    print("  A:", f["answer"][:500])
PY
