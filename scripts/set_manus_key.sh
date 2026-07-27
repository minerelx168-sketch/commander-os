#!/bin/bash
# Set MANUS_API_KEY in hub/.env (key passed via env var MK, not logged)
set -e
ENVF="$HOME/commander-os/hub/.env"
grep -q '^MANUS_API_KEY=' "$ENVF" && sed -i '' "s|^MANUS_API_KEY=.*|MANUS_API_KEY=$MK|" "$ENVF" \
  || printf '\nMANUS_API_KEY=%s\nMANUS_API_URL=https://api.manus.im/v1/chat/completions\n' "$MK" >> "$ENVF"
grep -q '^MANUS_API_URL=' "$ENVF" || printf 'MANUS_API_URL=https://api.manus.im/v1/chat/completions\n' >> "$ENVF"
echo "MANUS_API_KEY set ($(grep -c '^MANUS' "$ENVF") MANUS lines in .env)"
