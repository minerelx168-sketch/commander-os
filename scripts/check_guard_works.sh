#!/bin/bash
# Does the secrets guard actually catch anything, or does it just always pass?
# Plant each credential shape in a tracked file, confirm it fails, then restore.
set -e
cd "$HOME/commander-os"
PROBE=hub/scripts/_probe_tmp.py
trap 'git rm -q --cached "$PROBE" 2>/dev/null || true; rm -f "$PROBE"' EXIT

fail() { echo "GUARD IS BLIND: $1"; exit 1; }

for shape in \
  'cx_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA' \
  'ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA' \
  'sk-ant-AAAAAAAAAAAAAAAAAAAAAAAA' \
  '1234567890:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
do
  printf 'KEY = "%s"\n' "$shape" > "$PROBE"
  git add -f "$PROBE"
  if hub/.venv/bin/python hub/scripts/check_secrets.py > /dev/null 2>&1; then
    fail "missed ${shape:0:10}…"
  fi
  echo "  caught ${shape:0:10}…"
  git rm -q --cached "$PROBE"
  rm -f "$PROBE"
done

echo
echo "== and a forbidden path =="
mkdir -p hub/memory
[ -f hub/memory/sources.json ] || echo '[]' > hub/memory/sources.json
git add -f hub/memory/sources.json
if hub/.venv/bin/python hub/scripts/check_secrets.py > /dev/null 2>&1; then
  git rm -q --cached hub/memory/sources.json
  fail "missed tracked sources.json"
fi
echo "  caught tracked hub/memory/sources.json"
git rm -q --cached hub/memory/sources.json

echo
echo "== clean tree still passes =="
hub/.venv/bin/python hub/scripts/check_secrets.py
