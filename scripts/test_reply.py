#!/usr/bin/env python3
"""Simulate the CEO replying to the latest report; print the advisor's answer."""
import json
import os
import subprocess
import sys

import httpx

HUB = "https://pennsylvania-influences-strength-ebooks.trycloudflare.com"
ENV = os.path.expanduser("~/commander-os/hub/.env")


def env(key: str) -> str:
    for line in open(ENV, encoding="utf-8"):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return ""


K, CHAT = env("HERMES_API_KEY"), env("TELEGRAM_CHAT_ID")
question = sys.argv[1] if len(sys.argv) > 1 else (
    "ถ้าบังคับดาวน์ขั้นต่ำ 15% จะกระทบยอดปล่อยต่อวันประมาณเท่าไหร่ ตอบเป็นตัวเลข")

runs = httpx.get(f"{HUB}/api/routines/1/runs?limit=1",
                 headers={"X-Hermes-API-Key": K}, timeout=40).json()["runs"]
mid = (runs[0].get("message_ids") or [0])[0]
print(f"replying to telegram message_id: {mid}")

update = {"update_id": 99, "message": {
    "message_id": 90100, "chat": {"id": int(CHAT)}, "text": question,
    "reply_to_message": {"message_id": mid}}}

r = httpx.post(f"{HUB}/api/telegram/webhook", json=update, timeout=600).json()
print("handled:", r.get("handled"), "| seat:", r.get("dept"),
      "| linked_run:", r.get("linked_run"), "| exact_reply:", r.get("exact_reply"))
print("delivery:", r.get("delivery"))

fu = httpx.get(f"{HUB}/api/followups?limit=1", headers={"X-Hermes-API-Key": K},
               timeout=40).json()["followups"][0]
print(f"\nQ: {fu['question']}")
print(f"A ({fu['dept']}): {fu['answer']}")
