#!/bin/bash
# Install cloudflared (Apple Silicon binary from official GitHub release)
set -e
mkdir -p "$HOME/bin"
cd "$HOME/bin"
curl -sL -o cf.tgz https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz
tar xzf cf.tgz
chmod +x cloudflared
./cloudflared --version
