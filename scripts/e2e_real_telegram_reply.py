#!/usr/bin/env python3
"""End-to-end with a REAL Telegram message: post a question to the chat as if
the CEO sent it, feed that genuine update to the hub, and confirm the answer
arrives threaded under it."""
import os
import time

import httpx

HUB = "https://pennsylvania-influences-strength-ebooks.trycloudflare.com"
ENV = os.path.expanduser("~/commander-os/hub/.env")


def env(key: str) -> str:
    for line in open(ENV, encoding="utf-8"):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return ""


K, T, CHAT = env("HERMES_API_KEY"), env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
QUESTION = ("ถ้าบังคับดาวน์ขั้นต่ำ 15% จะกระทบยอดปล่อยต่อวันประมาณเท่าไหร่ "
            "ตอบเป็นตัวเลขสั้นๆ")

runs = httpx.get(f"{HUB}/api/routines/1/runs?limit=1",
                 headers={"X-Hermes-API-Key": K}, timeout=40).json()["runs"]
report_mid = (runs[0].get("message_ids") or [0])[0]
print("report message_id:", report_mid)

# Put a real message in the chat, threaded under the report — this is exactly
# what the CEO's own reply looks like to Telegram.
posted = httpx.post(f"https://api.telegram.org/bot{T}/sendMessage",
                    json={"chat_id": CHAT, "text": QUESTION,
                          "reply_to_message_id": report_mid}, timeout=30).json()
assert posted.get("ok"), posted
question_mid = posted["result"]["message_id"]
print("question message_id:", question_mid, "(real, exists in the chat)")

update = {"update_id": int(time.time()), "message": {
    "message_id": question_mid, "chat": {"id": int(CHAT)}, "text": QUESTION,
    "reply_to_message": {"message_id": report_mid}}}

r = httpx.post(f"{HUB}/api/telegram/webhook", json=update, timeout=600).json()
print("\nhandled:", r.get("handled"), "| seat:", r.get("dept"),
      "| linked_run:", r.get("linked_run"), "| exact_reply:", r.get("exact_reply"))
print("delivery:", r.get("delivery"))

fu = httpx.get(f"{HUB}/api/followups?limit=1", headers={"X-Hermes-API-Key": K},
               timeout=40).json()["followups"][0]
print(f"\nQ: {fu['question']}")
print(f"A ({fu['dept']}): {fu['answer'][:700]}")
