#!/bin/bash
# Clone the template repos (shallow, read-only) into ~/commander-os/templates
set -e
mkdir -p "$HOME/commander-os/templates"
cd "$HOME/commander-os/templates"
for r in COO_command CMO_command CFO_command; do
  if [ -d "$r/.git" ]; then
    git -C "$r" pull --quiet 2>/dev/null || true
  else
    git clone --depth 1 "https://github.com/minerelx168-sketch/$r.git" 2>&1 | tail -1 || true
  fi
done
echo "--- tree ---"
find "$HOME/commander-os/templates" -maxdepth 3 -not -path '*/.git*' | sed "s|$HOME/commander-os/templates/||" | head -80
