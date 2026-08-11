#!/bin/bash
# Generate the hermes_cloud3 keypair for ubuntu@34.75.96.28 and print the public key
set -e
KEY="$HOME/.ssh/hermes_cloud3"
mkdir -p "$HOME/.ssh"; chmod 700 "$HOME/.ssh"
[ -f "$KEY" ] || ssh-keygen -t ed25519 -f "$KEY" -N "" -C "hermes-to-cloud3"
chmod 600 "$KEY"
grep -q 'Host commander-cloud3' "$HOME/.ssh/config" 2>/dev/null || cat >> "$HOME/.ssh/config" <<'CFG'

Host commander-cloud3
  HostName 34.75.96.28
  User ubuntu
  Port 22
  IdentityFile ~/.ssh/hermes_cloud3
  StrictHostKeyChecking accept-new
  ServerAliveInterval 30
CFG
chmod 600 "$HOME/.ssh/config"
echo "--- PUBLIC KEY hermes_cloud3 ---"
cat "$KEY.pub"
