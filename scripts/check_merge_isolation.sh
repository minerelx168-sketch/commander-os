#!/bin/bash
# After the merge: do the scheduled-Routine system and the Pipeline work-tree
# system both work, without reading each other's records?
set -e
cd "$HOME/commander-os/hub"
unset PYTHONPATH
.venv/bin/python - <<'PY'
import json, tempfile, pathlib
from unittest.mock import patch as mp
from fastapi.testclient import TestClient

tmp = pathlib.Path(tempfile.mkdtemp())
from app import config, store, sources, docs
store._FILE = tmp / "hub_store.json"
sources._FILE = tmp / "sources.json"
docs.LOCAL_DIR = tmp
docs._META = tmp / "_meta.json"
config.MEMORY_DIR = tmp

from app.main import app
c = TestClient(app)
# The hub is key-protected; a local check must authenticate like any caller.
if config.HERMES_API_KEY:
    c.headers.update({"X-Hermes-API-Key": config.HERMES_API_KEY})

# 1) a scheduled routine (my system)
r = c.post("/api/routines", json={"task": "สรุปยอดขายรายวัน", "frequency": "daily",
                                  "time": "09:00", "seats": ["cfo"]}).json()
print("routine   :", r["id"], r["task"][:28], "| next:", r["next_at"][:16])

# 2) a pipeline work tree (Claude's system)
docs.create_project("MergeCheck")
t = c.post("/api/pipeline/routines", json={"name": "ลดหนี้เสีย", "project": "MergeCheck",
                                           "owner": "COO", "dept": "coo"}).json()
print("tree      :", t["id"], t["name"], "| tree:", t["tree"])

# 3) neither list contains the other's record
routines = c.get("/api/routines").json()["routines"]
trees = c.get("/api/pipeline").json()["routines"]
assert [x["id"] for x in routines] == [r["id"]] and "task" in routines[0]
assert [x["id"] for x in trees] == [t["id"]] and "tasks" in trees[0]
assert "tasks" not in routines[0] and "task" not in trees[0]
print("isolation : routines =", len(routines), "| trees =", len(trees), "— no bleed")

# 4) the store keeps them under separate keys
data = json.loads(store._FILE.read_text())
assert len(data["routines"]) == 1 and len(data["trees"]) == 1
print("store keys: routines / trees held apart")

# 5) a task under the tree still runs and appends
task = c.post(f"/api/pipeline/routines/{t['id']}/tasks",
              json={"title": "ตรวจ FPD", "brief": "ดูกลุ่มดาวน์ 0%"}).json()
with mp("app.llm.chat", return_value={"text": "พบว่ากลุ่มดาวน์ 0% ดัน FPD",
                                      "provider": "p", "model": "m", "ok": True,
                                      "truncated": False}):
    out = c.post(f"/api/pipeline/routines/{t['id']}/tasks/{task['id']}/run",
                 json={"directive": ""}).json()
run = out["routine"]["tasks"][0]
print("tree run  : status =", run.get("status"), "| runs =", len(run.get("runs", [])))
assert run.get("runs"), out

# 6) the scheduled routine still runs and delivers
with mp("app.llm.chat", return_value={"text": "ยอดขายทรงตัว", "provider": "p",
                                      "model": "m", "ok": True, "truncated": False}), \
     mp("app.telegram.send", return_value={"ok": True, "sent": 1, "message_ids": [1]}):
    out = c.post(f"/api/routines/{r['id']}/run").json()
print("routine run: seats =", list(out["results"]), "| telegram =", out["delivery"])
assert out["delivery"]["ok"]

print("\nBOTH SYSTEMS LIVE AND ISOLATED")
PY
