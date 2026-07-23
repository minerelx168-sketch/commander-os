#!/bin/bash
# Check the new public tunnel serves the hub
set -e
U=https://earthquake-grass-inputs-apps.trycloudflare.com
curl -s -m 25 -o /dev/null -w "public /health: %{http_code}\n" "$U/health"
curl -s -m 25 "$U/api/docs" | python3 -c "
import json, sys
j = json.load(sys.stdin)
print('projects:', j['projects'], '| docs:', len(j['documents']))
"
