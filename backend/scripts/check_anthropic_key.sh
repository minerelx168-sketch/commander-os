#!/bin/bash
# Verify an Anthropic API key + list available models (key passed via env ANTH_KEY)
set -e
echo "== models list =="
curl -s https://api.anthropic.com/v1/models \
  -H "x-api-key: $ANTH_KEY" \
  -H "anthropic-version: 2023-06-01" | head -c 1200
echo
