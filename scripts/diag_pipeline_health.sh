#!/bin/bash
# Why does the second run still read "done"? Print what the store actually holds.
set -e
cd "$HOME/commander-os/hub"
unset PYTHONPATH
.venv/bin/python - <<'PY'
import pathlib, tempfile
from unittest.mock import patch as mp
from fastapi.testclient import TestClient

tmp = pathlib.Path(tempfile.mkdtemp())
from app import config, store, sources, docs, routines
store._FILE = tmp / "hub_store.json"
sources._FILE = tmp / "sources.json"
docs.LOCAL_DIR = tmp; docs._META = tmp / "_meta.json"
config.MEMORY_DIR = tmp
routines._LIVE.clear()

from app.main import app
c = TestClient(app)
if config.HERMES_API_KEY:
    c.headers.update({"X-Hermes-API-Key": config.HERMES_API_KEY})

r = c.post("/api/routines", json={"task": "t", "frequency": "daily",
                                  "time": "09:00", "seats": ["cfo", "coo"]}).json()

with mp("app.llm.chat", return_value={"text": "รายงาน", "provider": "p", "model": "m", "ok": True}), \
     mp("app.telegram.send", return_value={"ok": True, "sent": 1, "message_ids": [1]}):
    c.post(f"/api/routines/{r['id']}/run")

def half(provider, system, user, **kw):
    silent = "COO" in system
    return {"text": "" if silent else "รายงาน", "provider": provider,
            "model": "m", "ok": not silent}

with mp("app.llm.chat", side_effect=half), \
     mp("app.telegram.send", return_value={"ok": True, "sent": 1, "message_ids": [2]}):
    c.post(f"/api/routines/{r['id']}/run")

runs = store.get_routine_runs(limit=50)
print("runs stored:", len(runs))
for run in runs:
    print(f"  run #{run['id']} results:")
    for k, v in run["results"].items():
        print(f"     {k}: ok={v['ok']} text={v['text']!r}")

v = c.get("/api/pipeline").json()["routines"][0]
print("\nview health:", v["health"])
print("last_run id:", (v.get("last_run") or {}).get("id"))
print("seat cards:", [(x["key"], x["reported"], x["ok"]) for x in v["seat_cards"]])
PY
