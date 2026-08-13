#!/usr/bin/env python3
"""Why did CFO answer a question addressed to COO?"""
import os
import sys

import httpx

sys.path.insert(0, os.path.expanduser("~/commander-os/hub"))
HUB = "https://pennsylvania-influences-strength-ebooks.trycloudflare.com"
ENV = os.path.expanduser("~/commander-os/hub/.env")


def env(key):
    for line in open(ENV, encoding="utf-8"):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return ""


h = {"X-Hermes-API-Key": env("HERMES_API_KEY")}

print("=== run #1: which seats are candidates? ===")
runs = httpx.get(f"{HUB}/api/routines/1/runs?limit=3", headers=h, timeout=40).json()["runs"]
for r in runs:
    print(f"  run #{r['id']} {r['at_local']}")
    for k, v in r["results"].items():
        print(f"     {k:<9} ok={v['ok']} len={len(v['text'])}")

print("\n=== _seat_of routing, offline ===")
from app import followup  # noqa: E402

run = runs[0]
for q in ["เรียก COO \n\nขอรายชื่อ ลูกค้าที่ FPD 7 วันล่าสุด",
          "ขอให้ COO ช่วยดึง case สรุปมาให้ฉันเป็นไฟล์ .xlsx",
          "COO ช่วยดูหน่อย",
          "ถามเฉยๆ ไม่ระบุคน"]:
    print(f"  {followup._seat_of(run, q):<9} <- {q[:55]!r}")
