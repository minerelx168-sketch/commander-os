#!/bin/bash
set -e
cd ~/commander-os/backend
unset PYTHONPATH
if [ ! -d .venv ]; then
  /Users/boston/.hermes/hermes-agent/venv/bin/python3.11 -m venv .venv
fi
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "=== venv ready: $(python --version) ==="
