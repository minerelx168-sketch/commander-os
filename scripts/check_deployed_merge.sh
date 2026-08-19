#!/bin/bash
# Confirm the merged build is live on the VM: both systems answer, tunnel up.
set -e
cd "$HOME/commander-os/hub"
K=$(grep '^HERMES_API_KEY=' .env | cut -d= -f2-)
U=https://pennsylvania-influences-strength-ebooks.trycloudflare.com

echo "== units =="
ssh commander-cloud3 'systemctl is-active commander-hub commander-tunnel nginx' | tr '\n' ' '; echo

echo "== deployed commit =="
ssh commander-cloud3 'cd ~/commander-os/hub 2>/dev/null && ls app/pipeline.py app/followup.py 2>&1 | tr "\n" " "'; echo

echo "== endpoints (both systems) =="
for p in /health /api/routines /api/pipeline /api/followups /api/sources; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 30 -H "X-Hermes-API-Key: $K" "$U$p")
  printf '  %-18s %s\n' "$p" "$code"
done

echo "== pipeline payload shape =="
curl -s -m 30 -H "X-Hermes-API-Key: $K" "$U/api/pipeline" -o /tmp/pl.json
python3 - <<'PY'
import json
j = json.load(open("/tmp/pl.json"))
print("  keys:", sorted(j)[:6])
print("  trees:", len(j.get("routines", [])), "| stats:", j.get("stats"))
PY

echo "== scheduled routines still intact =="
curl -s -m 30 -H "X-Hermes-API-Key: $K" "$U/api/routines" -o /tmp/rt.json
python3 - <<'PY'
import json
j = json.load(open("/tmp/rt.json"))
for r in j["routines"]:
    print(f"  #{r['id']} {r['frequency']} {r['time']} seats={r['seats']} enabled={r['enabled']}")
print("  scheduler_alive:", j.get("scheduler_alive"), "| now:", j.get("now_local"))
PY
