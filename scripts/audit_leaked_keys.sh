#!/bin/bash
# sources.json was tracked before commit af7c44b. Its ingest keys are therefore
# in the pushed history even though the file is untracked now. Report exactly
# which keys are exposed so they can be rotated.
set -e
cd "$HOME/commander-os"

echo "== is the file in the pushed history? =="
n=$(git log --oneline --all -- hub/memory/sources.json | wc -l | tr -d ' ')
echo "  commits touching it: $n"

echo "== which ingest keys leaked =="
git log --all --format='%H' -- hub/memory/sources.json | while read -r sha; do
  git show "$sha:hub/memory/sources.json" 2>/dev/null
done | grep -oE 'cx_[A-Za-z0-9_-]{20,}' | sort -u | while read -r k; do
  echo "  ${k:0:10}… (${#k} chars)"
done

echo "== which of those are still live on the server =="
K=$(grep '^HERMES_API_KEY=' hub/.env | cut -d= -f2-)
U=https://pennsylvania-influences-strength-ebooks.trycloudflare.com
curl -s -m 30 -H "X-Hermes-API-Key: $K" "$U/api/sources" -o /tmp/live_src.json
python3 - <<'PY'
import json, subprocess, pathlib
live = {s["ingest_key"]: s for s in json.load(open("/tmp/live_src.json"))["sources"]}
leaked = set(subprocess.run(
    "cd ~/commander-os && git log --all --format=%H -- hub/memory/sources.json | "
    "while read s; do git show $s:hub/memory/sources.json 2>/dev/null; done | "
    "grep -oE 'cx_[A-Za-z0-9_-]{20,}' | sort -u",
    shell=True, capture_output=True, text=True).stdout.split())
for key, s in live.items():
    state = "EXPOSED — rotate" if key in leaked else "safe (minted after the fix)"
    print(f"  #{s['id']} {s['name']}: {state}")
PY
