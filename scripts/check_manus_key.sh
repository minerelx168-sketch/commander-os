#!/bin/bash
# Verify the Manus key with a real chat completion call (key read from .env, never printed)
set -e
cd "$HOME/commander-os/hub"
unset PYTHONPATH
.venv/bin/python - <<'PY'
import os, httpx
from dotenv import load_dotenv
load_dotenv(".env")
key = os.environ["MANUS_API_KEY"]
url = os.environ.get("MANUS_API_URL", "https://api.manus.im/v1/chat/completions")
try:
    r = httpx.post(url, headers={"Authorization": f"Bearer {key}"},
                   json={"model": os.environ.get("MANUS_MODEL", "manus-1"),
                         "messages": [{"role": "user", "content": "ตอบคำว่า 'พร้อม' คำเดียว"}]},
                   timeout=60)
    print("status:", r.status_code)
    if r.status_code == 200:
        j = r.json()
        print("reply:", j["choices"][0]["message"]["content"][:100])
        print("model:", j.get("model"))
    else:
        print("body:", r.text[:300])
except Exception as e:
    print("error:", type(e).__name__, str(e)[:200])
PY
