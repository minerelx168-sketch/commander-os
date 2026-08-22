#!/bin/bash
# Trust nothing: dump every historical version of sources.json and show what
# secret-bearing fields it actually carried. A grep that finds nothing may mean
# "clean" or may mean "my pattern was wrong" — this prints the fields.
set -e
cd "$HOME/commander-os"

echo "== every version of hub/memory/sources.json in the pushed history =="
git log --all --format='%H %ad %s' --date=short -- hub/memory/sources.json \
  | while read -r sha date subject; do
      body=$(git show "$sha:hub/memory/sources.json" 2>/dev/null || echo "")
      [ -z "$body" ] && { echo "  $date ${sha:0:8}  (file absent)"; continue; }
      summary=$(printf '%s' "$body" | python3 -c "
import json, sys
try:
    rows = json.load(sys.stdin)
except Exception as e:
    print('unparseable:', e); raise SystemExit
if not rows:
    print('empty list')
    raise SystemExit
for r in rows:
    ing = r.get('ingest_key') or ''
    sec = r.get('secret') or ''
    print(f\"    id={r.get('id')} name={r.get('name','')[:24]!r} \"
          f\"ingest_key={'YES ' + ing[:12] + '…' if ing else 'none'} \"
          f\"outbound_secret={'YES' if sec else 'none'}\")
")
      echo "  $date ${sha:0:8}  ${subject:0:44}"
      printf '%s\n' "$summary"
    done

echo
echo "== is any historical key still accepted by the live server? =="
K=$(grep '^HERMES_API_KEY=' hub/.env | cut -d= -f2-)
U=https://pennsylvania-influences-strength-ebooks.trycloudflare.com
git log --all --format='%H' -- hub/memory/sources.json | while read -r sha; do
  git show "$sha:hub/memory/sources.json" 2>/dev/null || true
done | grep -oE '"ingest_key": *"[^"]+"' | sed 's/.*: *"//; s/"//' | sort -u > /tmp/hist_keys.txt

count=$(wc -l < /tmp/hist_keys.txt | tr -d ' ')
echo "  distinct historical ingest keys: $count"
if [ "$count" = "0" ]; then
  echo "  nothing to test"
else
  while read -r k; do
    [ -z "$k" ] && continue
    code=$(curl -s -o /dev/null -w '%{http_code}' -m 30 -X POST \
      -H "X-Source-Key: $k" -H 'Content-Type: application/json' \
      -d '[{"probe":1}]' "$U/api/ingest")
    if [ "$code" = "200" ]; then
      echo "  ${k:0:12}… -> $code  STILL LIVE — must rotate"
    else
      echo "  ${k:0:12}… -> $code  dead"
    fi
  done < /tmp/hist_keys.txt
fi
