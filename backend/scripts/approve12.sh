#!/bin/bash
curl -s -X POST "http://localhost:8100/api/approvals/12/decide" \
  -H 'content-type: application/json' \
  -d '{"decision":"approve","decided_by":"boston"}' | head -c 300
echo
sleep 25
cd ~/commander-os/backend
unset PYTHONPATH && source .venv/bin/activate
python scripts/check_task23.py
echo "--- latest brief ---"
ls -t deliverables/ 2>/dev/null | head -3
