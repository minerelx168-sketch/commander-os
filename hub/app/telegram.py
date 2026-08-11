"""Telegram delivery — how routine results reach the CEO when he is not at the desk.

Kept deliberately thin: one sender, honest about whether it is configured.
Failures are reported, never swallowed, so a silent bot cannot masquerade as
a working one.
"""
import logging
import os

import httpx

log = logging.getLogger("hub.telegram")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
MOCK = os.getenv("TELEGRAM_MOCK", "0") not in ("0", "false", "False", "")

# Telegram hard-caps a message at 4096 chars; split rather than truncate so a
# long brief arrives whole.
LIMIT = 3900


def ready() -> bool:
    return bool(BOT_TOKEN and CHAT_ID) or MOCK


def _chunks(text: str) -> list[str]:
    out, buf = [], ""
    for para in text.split("\n"):
        if len(buf) + len(para) + 1 > LIMIT:
            out.append(buf.rstrip())
            buf = ""
        buf += para + "\n"
    if buf.strip():
        out.append(buf.rstrip())
    return out or [text[:LIMIT]]


def send(text: str) -> dict:
    """Deliver a message. Returns {ok, sent, error} — never raises."""
    if MOCK:
        log.info("[telegram-mock] %s", text[:200])
        return {"ok": True, "sent": 1, "mock": True}
    if not (BOT_TOKEN and CHAT_ID):
        return {"ok": False, "sent": 0,
                "error": "ยังไม่ได้ตั้ง TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID ใน hub/.env"}
    sent = 0
    for chunk in _chunks(text):
        try:
            r = httpx.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                           json={"chat_id": CHAT_ID, "text": chunk,
                                 "disable_web_page_preview": True},
                           timeout=30)
            r.raise_for_status()
            sent += 1
        except Exception as e:  # noqa: BLE001 — delivery failure must be visible, not fatal
            log.warning("telegram send failed: %s", e)
            return {"ok": False, "sent": sent, "error": f"{type(e).__name__}: {str(e)[:160]}"}
    return {"ok": True, "sent": sent}
