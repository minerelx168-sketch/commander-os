"""Telegram bot — command intake, approval cards, report delivery.

TELEGRAM_MOCK=1 logs messages instead of sending. The bot runs long-polling in a
background thread started from FastAPI startup (only in live mode).
"""
import json
import logging

import httpx

from ..config import get_settings

log = logging.getLogger("commander.telegram")

MOCK_OUTBOX: list[dict] = []  # inspected by tests


def _send(method: str, payload: dict) -> None:
    s = get_settings()
    if s.telegram_mock:
        MOCK_OUTBOX.append({"method": method, "payload": payload})
        log.info("TELEGRAM_MOCK %s: %s", method, json.dumps(payload, ensure_ascii=False)[:300])
        return
    url = f"https://api.telegram.org/bot{s.telegram_bot_token}/{method}"
    r = httpx.post(url, json=payload, timeout=30)
    r.raise_for_status()


def send_text(text: str) -> None:
    s = get_settings()
    _send("sendMessage", {"chat_id": s.telegram_chat_id, "text": text})


def notify_approval(intr: dict) -> None:
    """Send an approval card with inline buttons."""
    s = get_settings()
    approval_id = intr.get("approval_id")
    text = (
        "📋 มีรายการรออนุมัติ\n"
        f"#{approval_id} — {intr.get('action')}\n"
        f"เป้าหมาย: {intr.get('target')}\n"
        f"เหตุผล: {intr.get('reason')}"
    )
    _send(
        "sendMessage",
        {
            "chat_id": s.telegram_chat_id,
            "text": text,
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {"text": "✅ อนุมัติ", "callback_data": f"approve:{approval_id}"},
                        {"text": "❌ ปฏิเสธ", "callback_data": f"reject:{approval_id}"},
                    ]
                ]
            },
        },
    )


def notify_report(report: str) -> None:
    if report:
        send_text(report)


# ---------- live-mode long polling (runs in background thread) ----------

def _handle_update(update: dict) -> None:
    """Process one Telegram update: text command or button callback."""
    import httpx as _httpx

    base = "http://localhost:8100/api"

    if "callback_query" in update:
        cq = update["callback_query"]
        data = cq.get("data", "")
        if ":" in data:
            decision, approval_id = data.split(":", 1)
            try:
                _httpx.post(
                    f"{base}/approvals/{approval_id}/decide",
                    json={"decision": decision, "decided_by": "owner:telegram"},
                    timeout=30,
                )
                send_text(f"รับทราบ — {('✅ อนุมัติ' if decision == 'approve' else '❌ ปฏิเสธ')} รายการ #{approval_id} แล้ว กำลังดำเนินการต่อ...")
            except Exception as e:  # noqa: BLE001
                send_text(f"⚠️ เกิดข้อผิดพลาด: {e}")
        _send("answerCallbackQuery", {"callback_query_id": cq["id"]})
        return

    msg = update.get("message", {})
    text = (msg.get("text") or "").strip()
    chat_id = str(msg.get("chat", {}).get("id", ""))
    s = get_settings()
    if not text or chat_id != str(s.telegram_chat_id):
        return  # ignore strangers
    if text.startswith("/report"):
        _httpx_get_report(base)
        return
    if text.startswith("/start"):
        send_text("🧠 Commander OS พร้อมรับคำสั่งครับ พิมพ์สั่งงานได้เลย เช่น\n“วิเคราะห์แคมเปญวันนี้ มีอะไรต้องปรับไหม”")
        return
    try:
        _httpx.post(f"{base}/command", json={"text": text, "source": "telegram"}, timeout=30)
        send_text("🫡 รับคำสั่งแล้ว CEO กำลังแตกงานและมอบหมายแผนก...")
    except Exception as e:  # noqa: BLE001
        send_text(f"⚠️ ส่งคำสั่งไม่สำเร็จ: {e}")


def _httpx_get_report(base: str) -> None:
    import httpx as _httpx

    r = _httpx.get(f"{base}/report/daily", timeout=30)
    send_text(r.json().get("report", "ไม่มีข้อมูล"))


def start_polling_thread() -> None:
    """Start Telegram long-polling in a daemon thread (live mode only)."""
    s = get_settings()
    if s.telegram_mock or not s.telegram_bot_token:
        log.info("Telegram polling disabled (mock or no token)")
        return

    import threading
    import time

    def loop() -> None:
        offset = 0
        url = f"https://api.telegram.org/bot{s.telegram_bot_token}/getUpdates"
        while True:
            try:
                r = httpx.get(url, params={"timeout": 50, "offset": offset}, timeout=60)
                for upd in r.json().get("result", []):
                    offset = upd["update_id"] + 1
                    _handle_update(upd)
            except Exception as e:  # noqa: BLE001
                log.warning("telegram poll error: %s", e)
                time.sleep(5)

    threading.Thread(target=loop, daemon=True, name="telegram-poller").start()
    log.info("Telegram polling started")
