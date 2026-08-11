#!/bin/bash
# Deploy Commander Hub to the GCP host (ubuntu@34.75.96.28) as a systemd service
# behind nginx on port 80. Idempotent: safe to re-run for updates.
set -euo pipefail
HOST=commander-cloud3
REMOTE=/home/ubuntu/commander-os

echo "== 1) sanity: ssh reachable =="
ssh -o BatchMode=yes -o ConnectTimeout=10 "$HOST" 'echo ok' >/dev/null

echo "== 2) install system deps =="
ssh "$HOST" 'sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip nginx rsync >/dev/null && echo deps-ok'

echo "== 3) sync hub code (excluding venv/secrets-in-store) =="
ssh "$HOST" "mkdir -p $REMOTE/hub"
rsync -az --delete \
  --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' \
  --exclude 'docs_store' --exclude 'memory' \
  "$HOME/commander-os/hub/" "$HOST:$REMOTE/hub/"
rsync -az "$HOME/commander-os/hub/.env" "$HOST:$REMOTE/hub/.env"
ssh "$HOST" "chmod 600 $REMOTE/hub/.env && mkdir -p $REMOTE/hub/docs_store $REMOTE/hub/memory"

echo "== 4) python venv + deps =="
ssh "$HOST" "cd $REMOTE/hub && python3 -m venv .venv 2>/dev/null; .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt && echo venv-ok"

echo "== 5) systemd service =="
ssh "$HOST" "sudo tee /etc/systemd/system/commander-hub.service >/dev/null <<'UNIT'
[Unit]
Description=Commander Hub — C-Suite Advisory
After=network-online.target

[Service]
User=ubuntu
WorkingDirectory=$REMOTE/hub
EnvironmentFile=$REMOTE/hub/.env
ExecStart=$REMOTE/hub/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8100
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload && sudo systemctl enable commander-hub && sudo systemctl restart commander-hub && sleep 5 && systemctl is-active commander-hub"

echo "== 6) nginx reverse proxy on :80 =="
ssh "$HOST" "sudo tee /etc/nginx/sites-available/commander-hub >/dev/null <<'NGX'
server {
    listen 80 default_server;
    server_name _;
    client_max_body_size 25m;
    location / {
        proxy_pass http://127.0.0.1:8100;
        proxy_set_header Host \\\$host;
        proxy_set_header X-Real-IP \\\$remote_addr;
        proxy_set_header X-Forwarded-Proto \\\$scheme;
        proxy_read_timeout 600s;
    }
}
NGX
sudo ln -sf /etc/nginx/sites-available/commander-hub /etc/nginx/sites-enabled/commander-hub
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx && echo nginx-ok"

echo "== 7) verify from the internet =="
sleep 2
curl -s -m 20 -o /dev/null -w 'public http://34.75.96.28/health -> %{http_code}\n' http://34.75.96.28/health
curl -s -m 20 http://34.75.96.28/api/state | python3 -c "
import json,sys
s=json.load(sys.stdin)
print('providers:', [(p['key'], p['ready']) for p in s['providers']])
print('advisors :', [d['key'] for d in s['depts']])
"
echo "DEPLOY OK — Commander Hub: http://34.75.96.28/"
