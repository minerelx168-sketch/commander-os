#!/bin/bash
# Probe how to fetch a Manus task result
set -e
cd "$HOME/commander-os/hub"
unset PYTHONPATH
.venv/bin/python - <<'PY'
import os, time, httpx
from dotenv import load_dotenv
load_dotenv(".env")
h = {"API_KEY": os.environ["MANUS_API_KEY"]}
tid = "YwgzVHQJPyUgYKecwXw4Wb"
for path in (f"/v1/tasks/{tid}", f"/v1/task/{tid}", f"/v1/tasks/{tid}/result"):
    try:
        r = httpx.get("https://api.manus.im" + path, headers=h, timeout=30)
        print(f"GET {path} -> {r.status_code} {r.text[:400]!r}")
    except Exception as e:
        print(f"GET {path} -> {type(e).__name__}: {str(e)[:80]}")
PY
