#!/bin/bash
# Install cloudflared on the VM and run it as a systemd service pointing at nginx:80.
# Interim public access until the GCP firewall opens port 80.
set -euo pipefail
HOST=commander-cloud3

ssh "$HOST" 'set -e
if ! command -v cloudflared >/dev/null; then
  curl -sL -o /tmp/cf.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
  sudo dpkg -i /tmp/cf.deb >/dev/null
fi
cloudflared --version
sudo tee /etc/systemd/system/commander-tunnel.service >/dev/null <<UNIT
[Unit]
Description=Cloudflare quick tunnel for Commander Hub
After=network-online.target nginx.service

[Service]
User=ubuntu
ExecStart=/usr/bin/cloudflared tunnel --url http://127.0.0.1:80 --no-autoupdate
Restart=always
RestartSec=5
StandardOutput=append:/home/ubuntu/tunnel.log
StandardError=append:/home/ubuntu/tunnel.log

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now commander-tunnel
sleep 12
grep -o "https://[a-z0-9-]*\.trycloudflare\.com" /home/ubuntu/tunnel.log | tail -1'
