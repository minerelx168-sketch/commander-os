#!/bin/bash
# Rotate the Telegram bot token in hub/.env (token via env TG, never logged)
set -e
ENVF="$HOME/commander-os/hub/.env"
sed -i '' "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=$TG|" "$ENVF"
sed -i '' "s|^TELEGRAM_MOCK=.*|TELEGRAM_MOCK=0|" "$ENVF"
grep -q '^TELEGRAM_MOCK=' "$ENVF" || printf 'TELEGRAM_MOCK=0\n' >> "$ENVF"
echo "token rotated; TELEGRAM lines: $(grep -c '^TELEGRAM' "$ENVF")"
