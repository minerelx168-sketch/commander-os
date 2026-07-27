#!/bin/bash
# Probe Manus task-based API (their native API is task-oriented, not chat completions)
set -e
cd "$HOME/commander-os/hub"
unset PYTHONPATH
.venv/bin/python - <<'PY'
import os, httpx
from dotenv import load_dotenv
load_dotenv(".env")
key = os.environ["MANUS_API_KEY"]
for h in ({"API_KEY": key}, {"Authorization": f"Bearer {key}"}, {"x-api-key": key}):
    hname = list(h.keys())[0]
    try:
        r = httpx.post("https://api.manus.im/v1/tasks", headers=h,
                       json={"prompt": "ตอบคำว่า พร้อม", "mode": "fast"}, timeout=30)
        print(f"POST /v1/tasks [{hname}] -> {r.status_code} {r.text[:200]!r}")
        if r.status_code == 200:
            break
    except Exception as e:
        print(f"POST /v1/tasks [{hname}] -> {type(e).__name__}: {str(e)[:80]}")
PY
