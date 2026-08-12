#!/usr/bin/env python3
"""Why did the follow-up reply fail with 400? Ask Telegram directly."""
import os

import httpx

ENV = os.path.expanduser("~/commander-os/hub/.env")


def env(key: str) -> str:
    for line in open(ENV, encoding="utf-8"):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return ""


T, CHAT = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")

# 1) plain send — does the bot work at all?
r = httpx.post(f"https://api.telegram.org/bot{T}/sendMessage",
               json={"chat_id": CHAT, "text": "probe: plain"}, timeout=30).json()
print("plain send:", r.get("ok"), r.get("description", ""))
mid = (r.get("result") or {}).get("message_id")

# 2) reply to a message that exists
if mid:
    r2 = httpx.post(f"https://api.telegram.org/bot{T}/sendMessage",
                    json={"chat_id": CHAT, "text": "probe: reply to real",
                          "reply_to_message_id": mid}, timeout=30).json()
    print("reply to real msg:", r2.get("ok"), r2.get("description", ""))

# 3) reply to a message id that does NOT exist (what the simulator did)
r3 = httpx.post(f"https://api.telegram.org/bot{T}/sendMessage",
                json={"chat_id": CHAT, "text": "probe: reply to fake",
                      "reply_to_message_id": 90100}, timeout=30).json()
print("reply to fake msg:", r3.get("ok"), r3.get("description", ""))
