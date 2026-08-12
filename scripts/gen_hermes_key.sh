#!/bin/bash
# Generate HERMES_API_KEY (43 url-safe chars from os.urandom) into hub/.env.
# Prints the key ONCE so it can be copied; never echoes it again afterwards.
set -e
cd "$HOME/commander-os/hub"
unset PYTHONPATH
KEY=$(.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(32))")
if grep -q '^HERMES_API_KEY=' .env; then
  sed -i '' "s|^HERMES_API_KEY=.*|HERMES_API_KEY=$KEY|" .env
else
  printf '\n# Hermes / machine access to the hub API\nHERMES_API_KEY=%s\n' "$KEY" >> .env
fi
chmod 600 .env
echo "HERMES_API_KEY (${#KEY} chars) written to hub/.env:"
echo "$KEY"
