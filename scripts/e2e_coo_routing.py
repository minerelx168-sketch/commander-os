#!/usr/bin/env python3
"""Re-run the CEO's exact two questions and confirm COO now answers."""
import os
import time

import httpx

HUB = "https://pennsylvania-influences-strength-ebooks.trycloudflare.com"
ENV = os.path.expanduser("~/commander-os/hub/.env")


def env(key):
    for line in open(ENV, encoding="utf-8"):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return ""


K, T, CHAT = env("HERMES_API_KEY"), env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
h = {"X-Hermes-API-Key": K}

runs = httpx.get(f"{HUB}/api/routines/1/runs?limit=1", headers=h, timeout=40).json()["runs"]
report_mid = runs[0]["message_ids"][0]

QUESTIONS = [
    "เรียก COO\n\nขอรายชื่อ ลูกค้าที่ FPD 7 วันล่าสุด",
    "ขอให้ COO ช่วยดึง case สรุปมาให้ฉันเป็นไฟล์ .xlsx",
]

for q in QUESTIONS:
    before = len(httpx.get(f"{HUB}/api/followups", headers=h, timeout=40).json()["followups"])
    posted = httpx.post(f"https://api.telegram.org/bot{T}/sendMessage", timeout=30,
                        json={"chat_id": CHAT, "text": q,
                              "reply_to_message_id": report_mid}).json()
    assert posted["ok"], posted
    qid = posted["result"]["message_id"]

    r = httpx.post(f"{HUB}/api/telegram/webhook", timeout=40, json={
        "update_id": int(time.time() * 1000) % 10**9,
        "message": {"message_id": qid, "chat": {"id": int(CHAT)}, "text": q,
                    "reply_to_message": {"message_id": report_mid}}}).json()
    assert r.get("queued"), r

    for _ in range(90):
        time.sleep(2)
        fus = httpx.get(f"{HUB}/api/followups", headers=h, timeout=40).json()["followups"]
        if len(fus) > before:
            break
    else:
        raise SystemExit("no answer recorded")

    fu = fus[0]
    mark = "OK" if fu["dept"] == "coo" else "WRONG SEAT"
    print(f"\n[{mark}] answered by: {fu['dept']}  (was cfo before the fix)")
    print(f"  Q: {q[:70]}")
    print(f"  A: {fu['answer'][:420]}")
