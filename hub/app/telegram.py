"""Telegram — how routine results reach the CEO, and how he answers back.

Two directions:
  * out — routine reports, split at Telegram's 4096-char cap
  * in  — the CEO replies to a report and asks a follow-up. The reply carries
    the original message id, so the hub knows which run he is pointing at and
    hands the advisor that context. One question, one answer: a follow-up is
    not a routine and not a board session.

Failures are reported, never swallowed, so a silent bot cannot masquerade as
a working one.
"""
import hashlib
import hmac
import logging
import os

import httpx

log = logging.getLogger("hub.telegram")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
MOCK = os.getenv("TELEGRAM_MOCK", "0") not in ("0", "false", "False", "")
# Telegram signs nothing, so the webhook path carries a secret instead.
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")

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


def send(text: str, reply_to: int | None = None) -> dict:
    """Deliver a message. Returns {ok, sent, message_ids, error} — never raises.

    `message_ids` is what makes replies work: the caller records them so an
    incoming reply can be traced back to the run it answers.
    """
    if MOCK:
        log.info("[telegram-mock] %s", text[:200])
        return {"ok": True, "sent": 1, "mock": True, "message_ids": []}
    if not (BOT_TOKEN and CHAT_ID):
        return {"ok": False, "sent": 0, "message_ids": [],
                "error": "ยังไม่ได้ตั้ง TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID ใน hub/.env"}
    sent, ids = 0, []
    for i, chunk in enumerate(_chunks(text)):
        body = {"chat_id": CHAT_ID, "text": chunk, "disable_web_page_preview": True}
        if reply_to and i == 0:
            body["reply_to_message_id"] = reply_to
        try:
            r = httpx.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                           json=body, timeout=30)
            # Threading is a nicety; delivery is not. If the message being
            # replied to is gone (deleted, or from another chat), send it
            # standalone rather than losing the answer entirely.
            if r.status_code == 400 and "reply_to_message_id" in body:
                body.pop("reply_to_message_id")
                r = httpx.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                               json=body, timeout=30)
            r.raise_for_status()
            sent += 1
            mid = r.json().get("result", {}).get("message_id")
            if mid:
                ids.append(mid)
        except Exception as e:  # noqa: BLE001 — delivery failure must be visible, not fatal
            log.warning("telegram send failed: %s", e)
            return {"ok": False, "sent": sent, "message_ids": ids,
                    "error": f"{type(e).__name__}: {str(e)[:160]}"}
    return {"ok": True, "sent": sent, "message_ids": ids}


# ── inbound ──

def valid_secret(presented: str) -> bool:
    """Telegram echoes the secret we registered with setWebhook."""
    if not WEBHOOK_SECRET:
        return True                       # not configured = not enforced
    return hmac.compare_digest(presented or "", WEBHOOK_SECRET)


def from_owner(update: dict) -> bool:
    """Only the configured chat may drive the board. Anyone who finds the bot
    can message it; without this, a stranger could spend the CEO's tokens."""
    msg = update.get("message") or update.get("edited_message") or {}
    chat_id = str((msg.get("chat") or {}).get("id", ""))
    return not CHAT_ID or chat_id == str(CHAT_ID)


def parse_reply(update: dict) -> dict | None:
    """Extract {text, reply_to, chat_id, message_id} from an incoming update."""
    msg = update.get("message") or update.get("edited_message")
    if not msg or not (msg.get("text") or "").strip():
        return None
    return {
        "text": msg["text"].strip(),
        "reply_to": (msg.get("reply_to_message") or {}).get("message_id"),
        "chat_id": (msg.get("chat") or {}).get("id"),
        "message_id": msg.get("message_id"),
    }


def set_webhook(url: str) -> dict:
    """Point Telegram at our endpoint. Returns the API's own verdict."""
    if not BOT_TOKEN:
        return {"ok": False, "error": "no TELEGRAM_BOT_TOKEN"}
    body = {"url": url, "allowed_updates": ["message"]}
    if WEBHOOK_SECRET:
        body["secret_token"] = WEBHOOK_SECRET
    try:
        r = httpx.post(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
                       json=body, timeout=30)
        return r.json()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}


def webhook_info() -> dict:
    if not BOT_TOKEN:
        return {"ok": False, "error": "no TELEGRAM_BOT_TOKEN"}
    try:
        return httpx.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo",
                         timeout=30).json()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}


def token_fingerprint() -> str:
    """Short, non-reversible id for logs — never print the token itself."""
    return hashlib.sha256(BOT_TOKEN.encode()).hexdigest()[:8] if BOT_TOKEN else ""
