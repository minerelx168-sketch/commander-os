#!/bin/bash
# E2E smoke test — full loop against a running backend (MOCK mode)
# Usage: bash scripts/smoke.sh [base_url]
set -e
BASE="${1:-http://localhost:8100}"

echo "1) health check..."
curl -sf "$BASE/health" | python3 -m json.tool

echo "2) send command..."
TASK=$(curl -sf -X POST "$BASE/api/command" -H 'Content-Type: application/json' \
  -d '{"text": "วิเคราะห์แคมเปญวันนี้ มีอะไรต้องปรับไหม"}')
echo "$TASK"
TASK_ID=$(echo "$TASK" | python3 -c 'import sys,json; print(json.load(sys.stdin)["task_id"])')

sleep 3
echo "3) task status (expect waiting_approval)..."
curl -sf "$BASE/api/tasks/$TASK_ID" | python3 -m json.tool

echo "4) pending approvals..."
APPROVALS=$(curl -sf "$BASE/api/approvals")
echo "$APPROVALS" | python3 -m json.tool
APPROVAL_ID=$(echo "$APPROVALS" | python3 -c 'import sys,json; print(json.load(sys.stdin)[0]["id"])')

echo "5) approve #$APPROVAL_ID..."
curl -sf -X POST "$BASE/api/approvals/$APPROVAL_ID/decide" \
  -H 'Content-Type: application/json' -d '{"decision": "approve"}' | python3 -m json.tool

sleep 3
echo "6) task status (expect done + report)..."
curl -sf "$BASE/api/tasks/$TASK_ID" | python3 -m json.tool

echo "7) daily report..."
curl -sf "$BASE/api/report/daily" | python3 -m json.tool

echo
echo "✅ SMOKE TEST PASSED"
