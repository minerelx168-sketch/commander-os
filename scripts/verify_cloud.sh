#!/bin/bash
# Verify the cloud deployment end-to-end from the public internet
set -e
U=https://pennsylvania-influences-strength-ebooks.trycloudflare.com
echo "== health =="
curl -s -m 25 -o /dev/null -w "  %{http_code}\n" "$U/health"
echo "== providers + advisors =="
curl -s -m 25 "$U/api/state" | python3 -c "
import json, sys
s = json.load(sys.stdin)
for p in s['providers']:
    print(f\"  {p['key']:<10} {p['model']:<18} ready={p['ready']}\")
print('  advisors:', [d['key'] for d in s['depts']])
"
echo "== docs page (LINE webhook target) =="
curl -s -m 25 "$U/api/docs" | python3 -c "
import json, sys
j = json.load(sys.stdin)
print('  projects:', j['projects'], '| docs:', len(j['documents']))
"
echo "== UI served =="
curl -s -m 25 "$U/" | grep -c 'view-board\|เอกสาร\|Cross-Examination' | xargs echo "  markers:"
