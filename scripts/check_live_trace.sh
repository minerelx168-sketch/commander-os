#!/bin/bash
# Do the real models actually return the trace schema? Run the CEO's routine
# locally and report, per seat, whether a correctable path came back.
set -e
cd "$HOME/commander-os/hub"
K=$(grep '^HERMES_API_KEY=' .env | cut -d= -f2-)
U=http://localhost:8100

RID=$(curl -s -m 30 -H "X-Hermes-API-Key: $K" "$U/api/routines" \
      | python3 -c "import json,sys; print(json.load(sys.stdin)['routines'][0]['id'])")
echo "running routine #$RID with live models…"
curl -s -m 900 -X POST -H "X-Hermes-API-Key: $K" "$U/api/routines/$RID/run" -o /tmp/live_flow.json

python3 - <<PY
import json
r = json.load(open("/tmp/live_flow.json"))
for dept, res in (r.get("results") or {}).items():
    t = res.get("trace")
    if not t:
        print(f"  {dept:9} [{res['provider']:16}] NO TRACE — prose only ({len(res['text'])} chars)")
        continue
    print(f"  {dept:9} [{res['provider']:16}] steps={len(t['steps'])} "
          f"assumptions={len(t['assumptions'])} unknowns={len(t['unknowns'])} "
          f"conf={t['confidence']}")
    print(f"      answer: {t['answer'][:90]}")
print("delivery:", r.get("delivery"))
PY
