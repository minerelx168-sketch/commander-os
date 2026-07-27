#!/bin/bash
# Probe candidate Manus API base URLs / paths (key from .env, never printed)
set -e
cd "$HOME/commander-os/hub"
unset PYTHONPATH
.venv/bin/python - <<'PY'
import os, httpx
from dotenv import load_dotenv
load_dotenv(".env")
key = os.environ["MANUS_API_KEY"]
h = {"Authorization": f"Bearer {key}"}
body = {"model": "manus-1", "messages": [{"role": "user", "content": "hi"}]}
candidates = [
    "https://api.manus.im/v1/chat/completions",
    "https://api.manus.im/chat/completions",
    "https://api.manus.ai/v1/chat/completions",
    "https://api.manus.im/openai/v1/chat/completions",
    "https://manus.im/api/v1/chat/completions",
]
for url in candidates:
    try:
        r = httpx.post(url, headers=h, json=body, timeout=25)
        print(f"{url} -> {r.status_code} {r.text[:120]!r}")
    except Exception as e:
        print(f"{url} -> {type(e).__name__}: {str(e)[:80]}")
# also probe models listing
for url in ["https://api.manus.im/v1/models", "https://api.manus.ai/v1/models"]:
    try:
        r = httpx.get(url, headers=h, timeout=25)
        print(f"GET {url} -> {r.status_code} {r.text[:150]!r}")
    except Exception as e:
        print(f"GET {url} -> {type(e).__name__}: {str(e)[:80]}")
PY
