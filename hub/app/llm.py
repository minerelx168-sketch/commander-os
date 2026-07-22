"""Multi-provider LLM adapter — each C-level can run on a different AI agent.

Providers: anthropic (Claude), gemini (Google), manus (OpenAI-compatible), mock.
All calls are synchronous httpx with a deterministic mock fallback so the hub
never dies when a key is missing.
"""
import logging

import httpx

from . import config

log = logging.getLogger("hub.llm")
TIMEOUT = 120.0


def _extract_anthropic_text(content) -> str:
    """Claude Fable/Sonnet 5 return a list of blocks (thinking first) — join text blocks only."""
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text").strip()


def _anthropic(system: str, user: str) -> str:
    r = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": config.ANTHROPIC_API_KEY,
                 "anthropic-version": "2023-06-01"},
        json={"model": config.PROVIDERS["anthropic"]["model"], "max_tokens": 2048,
              "system": system, "messages": [{"role": "user", "content": user}]},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return _extract_anthropic_text(r.json()["content"])


def _gemini(system: str, user: str) -> str:
    model = config.PROVIDERS["gemini"]["model"]
    r = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": config.GOOGLE_API_KEY},
        json={"system_instruction": {"parts": [{"text": system}]},
              "contents": [{"parts": [{"text": user}]}]},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _manus(system: str, user: str) -> str:
    r = httpx.post(
        config.MANUS_API_URL,
        headers={"Authorization": f"Bearer {config.MANUS_API_KEY}"},
        json={"model": config.PROVIDERS["manus"]["model"],
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}]},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _mock(system: str, user: str) -> str:
    return ("[mock] ยังไม่ได้เชื่อม AI provider สำหรับแผนกนี้ — ไปที่หน้า Agents "
            "เพื่อเลือก provider ที่มี API key แล้วถามใหม่อีกครั้ง\n"
            f"(คำถามที่ได้รับ: {user[:120]})")


_CALLERS = {"anthropic": _anthropic, "gemini": _gemini, "manus": _manus, "mock": _mock}

_HAS_KEY = {
    "anthropic": lambda: bool(config.ANTHROPIC_API_KEY),
    "gemini": lambda: bool(config.GOOGLE_API_KEY),
    "manus": lambda: bool(config.MANUS_API_KEY),
    "mock": lambda: True,
}


def provider_ready(provider: str) -> bool:
    return _HAS_KEY.get(provider, lambda: False)()


def chat(provider: str, system: str, user: str) -> dict:
    """Returns {text, provider, model, ok}. Falls back to mock on any failure."""
    caller = _CALLERS.get(provider)
    if caller is None or not provider_ready(provider):
        return {"text": _mock(system, user), "provider": "mock", "model": "mock", "ok": False}
    try:
        return {"text": caller(system, user), "provider": provider,
                "model": config.PROVIDERS[provider]["model"], "ok": True}
    except Exception as e:  # noqa: BLE001 — a consult must never 500 the whole board
        log.warning("provider %s failed: %s", provider, e)
        return {"text": f"⚠️ {provider} ล้มเหลว: {str(e)[:200]}", "provider": provider,
                "model": config.PROVIDERS[provider]["model"], "ok": False}
