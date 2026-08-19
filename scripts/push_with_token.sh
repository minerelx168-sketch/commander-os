#!/bin/bash
# Store the GitHub PAT in the macOS keychain (via git-credential-osxkeychain)
# and push. The token arrives through env GH_PAT and is never echoed.
set -e
cd "$HOME/commander-os"
[ -n "${GH_PAT:-}" ] || { echo "GH_PAT not set"; exit 1; }

printf 'protocol=https\nhost=github.com\nusername=minerelx168-sketch\npassword=%s\n\n' "$GH_PAT" \
  | git credential-osxkeychain store

echo "credential stored; pushing $(git rev-list --count origin/main..HEAD) commits"
git push origin main 2>&1 | tail -3
echo "--- after ---"
git status -sb | head -2
