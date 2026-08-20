#!/usr/bin/env python3
"""Correct a node on the live hub and prove the next run answers for it."""
import json
import os
import re

import httpx

HUB = "http://localhost:8100"
ENV = os.path.expanduser("~/commander-os/hub/.env")
KEY = next(l.split("=", 1)[1].strip() for l in open(ENV)
           if l.startswith("HERMES_API_KEY="))
H = {"X-Hermes-API-Key": KEY, "Content-Type": "application/json"}

rid = httpx.get(f"{HUB}/api/routines", headers=H, timeout=60).json()["routines"][0]["id"]
j = httpx.get(f"{HUB}/api/pipeline/routines/{rid}", headers=H, timeout=60).json()
run = j["runs"][0]
dept = next(d for d, r in run["results"].items() if r.get("trace"))
trace = run["results"][dept]["trace"]

print(f"routine #{rid} · run #{run['id']} · seat {dept}")
print("nodes available:", ", ".join(sorted(j["nodes"])))
print(f"\nBEFORE — steps[0]: {trace['steps'][0]['step'][:90]}")

should = "ก่อนอย่างอื่น ให้ระบุก่อนว่าต้องได้ข้อมูล 3 ตัวนี้จาก API Connector: ยอดขายรายวัน, ต้นทุนต่อตู้, จำนวนตู้ที่เปิดขาย"
print(f"\nCEO fixes steps[0] -> {should[:70]}…")
r = httpx.post(f"{HUB}/api/pipeline/routines/{rid}/fix", headers=H, timeout=900,
               json={"run": run["id"], "dept": dept, "node": "steps[0]",
                     "should": should, "rerun": True})
print("fix status:", r.status_code)
if r.status_code != 200:
    print(r.text[:300]); raise SystemExit(1)

j2 = httpx.get(f"{HUB}/api/pipeline/routines/{rid}", headers=H, timeout=60).json()
newest = j2["runs"][0]
t2 = newest["results"][dept].get("trace")
print(f"\nAFTER  — new run #{newest['id']}")
if not t2:
    print("  no trace in the corrected run"); raise SystemExit(1)
print(f"  steps[0]: {t2['steps'][0]['step'][:110]}")
print(f"  changed_from_last: {(t2.get('changed_from_last') or '(ว่าง)')[:160]}")
for fr in t2.get("fix_responses") or []:
    print(f"  fix_response @{fr['node']}: {fr['what_i_did'][:120]}")

corrected = next((r for r in j2["runs"] if r["id"] == run["id"]), None)
fixes = corrected["results"][dept]["fixes"] if corrected else []
print(f"\n  correction stored on run #{run['id']}: {len(fixes)}")
if fixes:
    print(f"    was: {fixes[0]['was'][:80]}")
    print(f"    answered_by run: {fixes[0]['answered_by']}")
print("  open fixes now:", len(j2["open_fixes"]))
