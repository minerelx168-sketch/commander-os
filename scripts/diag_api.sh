#!/usr/bin/env bash
# Diagnose Commander Hub API/provider connectivity
cd "$(dirname "$0")/.." || exit 1
echo "=== hub process ==="
pgrep -fl "hub.app.main|uvicorn" | cut -c1-140 || echo "(no hub process)"
echo
echo "=== .env presence ==="
for f in hub/.env .env; do
  if [ -f "$f" ]; then echo "FOUND $f"; grep -oE '^[A-Z_]+' "$f" | sed 's/^/  key: /'; fi
done
echo
echo "=== hub routes ==="
curl -s -m 5 http://localhost:8100/openapi.json -o /tmp/hub_openapi.json && \
  python3 -c "import json;d=json.load(open('/tmp/hub_openapi.json'));[print(' ',p)for p in d['paths']]" \
  || echo "  (hub not answering on :8100)"
echo
echo "=== dept services ==="
for p in 8201 8202 8203 8204; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 3 "http://localhost:$p/health")
  echo "  port $p -> $code"
done
