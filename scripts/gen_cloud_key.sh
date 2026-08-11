#!/bin/bash
# Generate an SSH keypair for the Commander OS cloud host (GCP, ubuntu@34.75.96.28)
set -e
KEY="$HOME/.ssh/commander_cloud"
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
if [ -f "$KEY" ]; then
  echo "key already exists: $KEY"
else
  ssh-keygen -t ed25519 -f "$KEY" -N "" -C "commander-os@hermes"
fi
chmod 600 "$KEY"
cat >> "$HOME/.ssh/config" <<'CFG'

Host commander-cloud
  HostName 34.75.96.28
  User ubuntu
  Port 22
  IdentityFile ~/.ssh/commander_cloud
  StrictHostKeyChecking accept-new
  ServerAliveInterval 30
CFG
chmod 600 "$HOME/.ssh/config"
echo "--- PUBLIC KEY (add this to the server) ---"
cat "$KEY.pub"
