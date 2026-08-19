#!/bin/bash
# Exercise the new node-correction path end to end — the code that referenced
# a function renamed during the merge, so tests alone are not proof.
set -e
cd "$HOME/commander-os/hub"
unset PYTHONPATH
.venv/bin/python - <<'PY'
import json, pathlib, tempfile
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
if config.HERMES_API_KEY:
    c.headers.update({"X-Hermes-API-Key": config.HERMES_API_KEY})

docs.create_project("FixCheck")
t = c.post("/api/pipeline/routines", json={"name": "ลดหนี้เสีย", "project": "FixCheck",
                                           "owner": "COO", "dept": "coo"}).json()
task = c.post(f"/api/pipeline/routines/{t['id']}/tasks",
              json={"title": "ตรวจ FPD", "brief": "ดูกลุ่มดาวน์ 0%"}).json()

REASONED = json.dumps({
    "understanding": "ประเมิน FPD ของกลุ่มดาวน์ 0%",
    "steps": [{"claim": "FPD สูงเพราะฤดูกาล", "why": "เดือนนี้ยอดตก"},
              {"claim": "ควรลดวงเงิน", "why": "ลดความเสี่ยง"}],
    "assumptions": ["ข้อมูล 4 วันเป็นตัวแทนได้"],
    "unknowns": ["ไม่มี cohort เทียบ"],
    "self_check": "อาจสรุปเร็วเกิน",
    "answer": "ลดวงเงินกลุ่มดาวน์ 0%",
    "next_actions": ["ขอ cohort จากทีม data"],
}, ensure_ascii=False)

with mp("app.llm.chat", return_value={"text": REASONED, "provider": "p", "model": "m",
                                      "ok": True, "truncated": False}):
    out = c.post(f"/api/pipeline/routines/{t['id']}/tasks/{task['id']}/run",
                 json={"directive": ""}).json()
tk = out["routine"]["tasks"][0]
print("run 1     : status =", tk["status"], "| runs =", len(tk["runs"]))

# --- the path that would have raised NameError ---
fix = c.post(f"/api/pipeline/routines/{t['id']}/tasks/{task['id']}/fix",
             json={"run": 1, "node": "steps[0]",
                   "should": "FPD สูงเพราะเกณฑ์คัดกรองหลวม ไม่ใช่ฤดูกาล",
                   "rerun": False})
assert fix.status_code == 200, (fix.status_code, fix.text[:300])
body = fix.json()
tk = body["routine"]["tasks"][0] if "routine" in body else body
fixes = tk.get("corrections") or []
print("correction:", len(fixes), "| node =", fixes[0]["node"], "| was captured =",
      bool(fixes[0].get("was")))
assert fixes and fixes[0]["node"] == "steps[0]"
assert fixes[0]["was"], "the rejected reasoning was not captured"

# --- branch_task, the second renamed call site ---
br = c.post(f"/api/pipeline/routines/{t['id']}/tasks/{task['id']}/branch",
            json={"run": 1, "title": "ทางเลือก B"})
assert br.status_code == 200, (br.status_code, br.text[:300])
tasks = c.get("/api/pipeline").json()["routines"][0]["tasks"]
branch = [x for x in tasks if x.get("branched_from")]
assert branch, tasks
print("branch    :", branch[0]["title"], "| carried corrections =",
      len(branch[0].get("corrections", [])))
assert branch[0].get("corrections"), "the branch forgot which road was closed"

print("\nNODE-CORRECTION AND BRANCH BOTH WORK (both touched renamed internals)")
PY
