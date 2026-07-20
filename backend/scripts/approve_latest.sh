#!/bin/bash
# Approve the latest PENDING approval for task 23 and report final status
PEND=$(curl -s http://localhost:8100/api/approvals)
echo "$PEND" | head -c 600
echo
AID=$(echo "$PEND" | grep -o '"id":[0-9]*' | tail -1 | cut -d: -f2)
echo "approving id=$AID"
curl -s -X POST "http://localhost:8100/api/approvals/$AID/approve" | head -c 300
echo
sleep 20
curl -s http://localhost:8100/api/tasks | head -c 400
