#!/bin/bash
# Test Anthropic API key validity: list models, then a tiny message call
KEY="$1"
echo "== /v1/models =="
curl -s https://api.anthropic.com/v1/models \
  -H "x-api-key: $KEY" -H "anthropic-version: 2023-06-01" | head -c 1500
echo
echo "== tiny message call =="
curl -s https://api.anthropic.com/v1/messages \
  -H "x-api-key: $KEY" -H "anthropic-version: 2023-06-01" -H "content-type: application/json" \
  -d '{"model":"MODEL_PLACEHOLDER","max_tokens":16,"messages":[{"role":"user","content":"say ok"}]}' | head -c 800
echo
