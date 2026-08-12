#!/bin/bash
# What data does the CloudforCash connector actually hold right now?
set -e
cd "$HOME/commander-os/hub"
K=$(grep '^HERMES_API_KEY=' .env | cut -d= -f2-)
U=https://pennsylvania-influences-strength-ebooks.trycloudflare.com
curl -s -m 30 -H "X-Hermes-API-Key: $K" "$U/api/sources" -o /tmp/src.json
python3 - <<'PY'
import json
j = json.load(open("/tmp/src.json"))
print("projects:", j["projects"])
for s in j["sources"]:
    print(f"\n#{s['id']} {s['name']}")
    print("  owner:", s["project"], "| linked:", s.get("projects"))
    print("  kind:", s["kind"], "| enabled:", s["enabled"])
    print("  last_sync:", s.get("last_sync"), "| status:", s.get("last_status"), "| rows:", s.get("rows"))
    print("  stored sample:", (s.get("sample") or "(empty)")[:400])
PY
