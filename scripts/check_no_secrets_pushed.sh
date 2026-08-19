#!/bin/bash
# After pushing 29 commits: is anything sensitive now public on GitHub?
set -e
cd "$HOME/commander-os"

echo "== files that must NOT be tracked =="
for f in hub/.env hub/memory/sources.json hub/memory/hub_store.json; do
  if git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
    echo "  TRACKED (bad): $f"
  else
    echo "  ok, untracked: $f"
  fi
done

echo "== scan the pushed tree for live credential shapes =="
# Patterns for the credentials this project actually holds.
git grep -nIE 'ghp_[A-Za-z0-9]{30,}|sk-ant-[A-Za-z0-9_-]{20,}|cx_[A-Za-z0-9_-]{30,}|[0-9]{9,10}:AA[A-Za-z0-9_-]{30,}' \
  HEAD -- . 2>/dev/null | grep -v '\.example' | head -20 || echo "  none found in HEAD"

echo "== the helper script must not contain the token =="
grep -qE 'ghp_[A-Za-z0-9]{30,}' scripts/push_with_token.sh && echo "  LEAK in helper" || echo "  helper takes it from env only"

echo "== keychain holds it instead =="
printf 'protocol=https\nhost=github.com\n\n' | git credential-osxkeychain get \
  | sed 's/^password=.*/password=***STORED***/'
