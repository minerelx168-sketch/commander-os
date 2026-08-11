#!/bin/bash
# Verify the Telegram bot token + chat id, then send a real test message
set -e
cd "$HOME/commander-os/hub"
unset PYTHONPATH
.venv/bin/python - <<'PY'
import os
import httpx
from dotenv import load_dotenv
load_dotenv(".env", override=True)
t = os.environ["TELEGRAM_BOT_TOKEN"]
chat = os.environ.get("TELEGRAM_CHAT_ID", "")

me = httpx.get(f"https://api.telegram.org/bot{t}/getMe", timeout=20).json()
print("getMe:", me.get("ok"), "|", me.get("result", {}).get("username") or me.get("description"))
if not me.get("ok"):
    raise SystemExit("token invalid")

print("chat_id:", chat or "(missing)")
r = httpx.post(f"https://api.telegram.org/bot{t}/sendMessage",
               json={"chat_id": chat,
                     "text": "✅ Commander Hub เชื่อม Telegram สำเร็จ — Routine จะส่งรายงานมาที่นี่"},
               timeout=25).json()
print("sendMessage:", r.get("ok"), "|", r.get("description") or f"message_id={r.get('result',{}).get('message_id')}")
PY
