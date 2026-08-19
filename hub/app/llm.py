"""Multi-provider LLM adapter — each board seat can run on a different AI agent.

Providers: anthropic (Claude Opus), anthropic_fable (Claude Fable), gemini
(Google), manus (task API), zai (GLM), deepseek, mock. All calls are synchronous
httpx with a deterministic mock fallback so the hub never dies when a key is
missing, and transient upstream failures are retried before giving up.

Two rules this module enforces on every provider, because breaking either is how
a board answer comes back subtly wrong rather than obviously broken:

1. **An empty answer is a failure, not an answer.** Reasoning models put their
   chain of thought in a separate field; read only the visible-answer field and a
   thinking-heavy reply arrives as `""` with `ok: True`, and every caller
   downstream renders a blank section as if the advisor had nothing to say.
   `EmptyReply` makes that a retryable error instead.
2. **A cut-off answer must say it was cut off.** Every provider signals the token
   ceiling differently (`stop_reason`, `finish_reason`, `finishReason`); none of
   them were being read, so a reply that stopped mid-sentence was indistinguishable
   from one that finished. `Truncated` carries the partial text up to `chat()`,
   which flags it, and `chat_json()` re-asks on a bigger budget.
"""
import logging
import time

import httpx

from . import config, jsonx

log = logging.getLogger("hub.llm")
TIMEOUT = 120.0

# Nobody's budget doubles past this — beyond it the reply is not truncated, the
# prompt is wrong.
MAX_TOKENS_CEILING = 32768


class Truncated(RuntimeError):
    """The provider stopped because it hit the output ceiling. Carries whatever
    was written before the cut so a partial document can still be salvaged."""

    def __init__(self, text: str, provider: str = ""):
        super().__init__(f"{provider or 'provider'} hit its output ceiling")
        self.text = text or ""


class EmptyReply(RuntimeError):
    """The call succeeded and returned nothing usable — a blank answer rendered
    as an advisor's opinion is worse than an error the CEO can see."""


# A larger max_tokens means a proportionally longer generation, so the read
# timeout has to scale with it — otherwise raising the token ceiling silently
# converts a slow-but-fine reply into a timeout (which is exactly what the
# 8192-token Thai financial model hit against the flat 120s budget).
_SECONDS_PER_1K_TOKENS = 30.0


def _timeout_for(max_tokens: int | None) -> float:
    if not max_tokens or max_tokens <= 2048:
        return TIMEOUT
    return max(TIMEOUT, max_tokens / 1000 * _SECONDS_PER_1K_TOKENS)


def _extract_anthropic_text(content) -> str:
    """Claude Fable/Sonnet 5 return a list of blocks (thinking first) — join text blocks only."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text").strip()


def _claude(provider: str, system: str, user: str, max_tokens: int | None) -> str:
    """Shared Anthropic transport — Opus and Fable differ only by model id."""
    r = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": config.ANTHROPIC_API_KEY,
                 "anthropic-version": "2023-06-01"},
        json={"model": config.PROVIDERS[provider]["model"],
              "max_tokens": max_tokens or 2048,
              "system": system, "messages": [{"role": "user", "content": user}]},
        timeout=_timeout_for(max_tokens),
    )
    r.raise_for_status()
    payload = r.json()
    text = _extract_anthropic_text(payload.get("content"))
    # A reply made entirely of thinking blocks is not an answer; so is a refusal
    # that came back as a bare stop. Either way, do not hand "" to the board.
    if payload.get("stop_reason") == "max_tokens":
        raise Truncated(text, provider)
    if not text.strip():
        raise EmptyReply(f"{provider} returned no text block "
                         f"(stop_reason={payload.get('stop_reason')})")
    return text


def _anthropic(system: str, user: str, cancel=None, max_tokens: int | None = None) -> str:
    return _claude("anthropic", system, user, max_tokens)


def _anthropic_fable(system: str, user: str, cancel=None, max_tokens: int | None = None) -> str:
    return _claude("anthropic_fable", system, user, max_tokens)


def _anthropic_sonnet(system: str, user: str, cancel=None, max_tokens: int | None = None) -> str:
    return _claude("anthropic_sonnet", system, user, max_tokens)


def _openai_text(payload: dict, provider: str) -> str:
    """Read an OpenAI-shaped completion (DeepSeek, Z.AI and anything else that
    speaks /chat/completions).

    Reasoning models split the reply: the chain of thought goes to
    `reasoning_content` and the answer to `content`. When the thinking eats the
    whole budget, `content` comes back empty — which used to reach the board as a
    confident blank. `finish_reason: "length"` is the same event announced
    properly, so treat it as the cut it is.
    """
    choices = payload.get("choices") or []
    if not choices:
        raise EmptyReply(f"{provider} returned no choices")
    message = choices[0].get("message") or {}
    text = (message.get("content") or "").strip()
    if choices[0].get("finish_reason") == "length":
        raise Truncated(text, provider)
    if not text:
        raise EmptyReply(
            f"{provider} returned an empty content field "
            f"(finish_reason={choices[0].get('finish_reason')}, "
            f"reasoning_only={bool(message.get('reasoning_content'))})")
    return text


def _deepseek(system: str, user: str, cancel=None, max_tokens: int | None = None) -> str:
    """DeepSeek — OpenAI-compatible chat completions.

    It is a reasoning model: part of the budget goes to thinking, so a long
    prompt with a small ceiling can burn the whole allowance and return an
    empty `content` with finish_reason=length. Raise the floor and say so out
    loud rather than handing the board a blank seat.
    """
    r = httpx.post(
        config.DEEPSEEK_API_URL,
        headers={"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}"},
        json={"model": config.PROVIDERS["deepseek"]["model"],
              "max_tokens": max_tokens or 4096,
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}]},
        timeout=_timeout_for(max_tokens or 4096),
    )
    r.raise_for_status()
    return _openai_text(r.json(), "deepseek")


def _gemini(system: str, user: str, cancel=None, max_tokens: int | None = None) -> str:
    """Google Gemini.

    Reading `parts[0].text` is what a Gemini reply looks like only when the model
    does not think. Gemini 3 returns the reasoning as its own part flagged
    `thought: true`, usually *first* — so `parts[0]` hands the board the model's
    scratchpad instead of its answer, and any answer split across several parts
    loses everything after the first. Join the answer parts, drop the thoughts.
    """
    model = config.PROVIDERS["gemini"]["model"]
    body = {"system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}]}
    if max_tokens:
        body["generationConfig"] = {"maxOutputTokens": max_tokens}
    r = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": config.GOOGLE_API_KEY},
        json=body,
        timeout=_timeout_for(max_tokens),
    )
    r.raise_for_status()
    payload = r.json()

    blocked = (payload.get("promptFeedback") or {}).get("blockReason")
    if blocked:
        raise RuntimeError(f"gemini blocked the prompt ({blocked})")
    candidates = payload.get("candidates") or []
    if not candidates:
        raise EmptyReply("gemini returned no candidates")

    parts = ((candidates[0].get("content") or {}).get("parts")) or []
    text = "\n".join(p["text"] for p in parts
                     if isinstance(p, dict) and p.get("text") and not p.get("thought")).strip()
    finish = candidates[0].get("finishReason")
    if finish == "MAX_TOKENS":
        raise Truncated(text, "gemini")
    if not text:
        if finish in ("SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"):
            # A refusal answers the same way every time; retrying is pure delay.
            raise RuntimeError(f"gemini refused to answer ({finish})")
        raise EmptyReply(f"gemini returned no answer text (finishReason={finish})")
    return text


def _manus(system: str, user: str, cancel=None) -> str:
    """Manus native task API: create task -> poll until completed -> collect text.

    Manus is agent/task-oriented (POST /v1/tasks, header API_KEY) rather than
    an OpenAI-style chat endpoint. Fast mode keeps advisory latency tolerable.
    The poll loop honours `cancel` so a CEO STOP does not wait out the deadline.
    """
    base = config.MANUS_API_URL
    headers = {"API_KEY": config.MANUS_API_KEY}
    r = httpx.post(f"{base}/tasks", headers=headers,
                   json={"prompt": f"{system}\n\n---\n\n{user}", "mode": "fast"},
                   timeout=TIMEOUT)
    r.raise_for_status()
    task_id = r.json()["task_id"]

    deadline = time.monotonic() + 280
    while time.monotonic() < deadline:
        time.sleep(6)
        if cancel is not None and cancel():
            raise RuntimeError("CEO สั่งหยุดระหว่าง Manus กำลังทำงาน")
        t = httpx.get(f"{base}/tasks/{task_id}", headers=headers, timeout=30).json()
        status = t.get("status")
        if status in ("completed", "failed", "stopped"):
            texts = [c.get("text", "")
                     for m in t.get("output", []) if m.get("role") != "user"
                     for c in m.get("content", []) if c.get("type") == "output_text"]
            out = "\n".join(x for x in texts if x).strip()
            if status != "completed" and not out:
                raise RuntimeError(f"manus task {status}")
            return out or f"(Manus task {status} — ดูรายละเอียด: {t.get('metadata', {}).get('task_url', '')})"
    raise TimeoutError("manus task still running after 280s")


def _zai(system: str, user: str, cancel=None, max_tokens: int | None = None) -> str:
    """Z.AI (GLM) — OpenAI-compatible chat completions (thinking disabled for latency)."""
    body = {"model": config.PROVIDERS["zai"]["model"],
            "thinking": {"type": "disabled"},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}]}
    if max_tokens:
        body["max_tokens"] = max_tokens
    r = httpx.post(
        config.ZAI_API_URL,
        headers={"Authorization": f"Bearer {config.ZAI_API_KEY}"},
        json=body,
        timeout=_timeout_for(max_tokens),
    )
    r.raise_for_status()
    return _openai_text(r.json(), "zai")


def _mock(system: str, user: str, cancel=None) -> str:
    return ("[mock] ยังไม่ได้เชื่อม AI provider สำหรับแผนกนี้ — ไปที่หน้า Agents "
            "เพื่อเลือก provider ที่มี API key แล้วถามใหม่อีกครั้ง\n"
            f"(คำถามที่ได้รับ: {user[:120]})")


_CALLERS = {"anthropic": _anthropic, "anthropic_fable": _anthropic_fable,
            "anthropic_sonnet": _anthropic_sonnet,
            "gemini": _gemini, "manus": _manus, "zai": _zai,
            "deepseek": _deepseek, "mock": _mock}

# Only these accept a max_tokens hint; the rest use their own server-side default.
_ACCEPTS_MAX_TOKENS = {"anthropic", "anthropic_fable", "anthropic_sonnet", "deepseek",
                       "gemini", "zai"}

_HAS_KEY = {
    "anthropic": lambda: bool(config.ANTHROPIC_API_KEY),
    "anthropic_fable": lambda: bool(config.ANTHROPIC_API_KEY),
    "anthropic_sonnet": lambda: bool(config.ANTHROPIC_API_KEY),
    "deepseek": lambda: bool(config.DEEPSEEK_API_KEY),
    "gemini": lambda: bool(config.GOOGLE_API_KEY),
    "manus": lambda: bool(config.MANUS_API_KEY),
    "zai": lambda: bool(config.ZAI_API_KEY),
    "mock": lambda: True,
}


def provider_ready(provider: str) -> bool:
    return _HAS_KEY.get(provider, lambda: False)()


def _is_transient(exc: Exception) -> bool:
    """429/5xx and connection blips are the provider having a bad minute, not a
    bad request — retrying costs seconds, failing costs the CEO a document."""
    if isinstance(exc, Truncated):
        return False       # asking again on the same budget cuts at the same place
    if isinstance(exc, (EmptyReply, httpx.ConnectError, httpx.ReadTimeout,
                        httpx.RemoteProtocolError)):
        return True
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status in (408, 409, 425, 429, 500, 502, 503, 504, 529)


def chat(provider: str, system: str, user: str, cancel=None,
         max_tokens: int | None = None, attempts: int = 3) -> dict:
    """Returns {text, provider, model, ok}. Falls back to mock on any failure.

    `cancel` is an optional callable polled by long-running providers so the
    CEO's STOP takes effect without waiting out the provider deadline.

    `max_tokens` raises the output ceiling for callers that need a long,
    complete reply. Thai burns ~3x the tokens of English and reasoning models
    spend part of the budget thinking, so the 2048 default truncates structured
    JSON mid-object (stop_reason=max_tokens) and silently fails to parse.
    Providers that ignore the hint simply use their own default.

    Transient upstream failures (429/5xx, dropped connections) are retried with
    backoff — Anthropic answering 529 "overloaded" once should not cost a
    deliverable that took a minute of board debate to earn.
    """
    caller = _CALLERS.get(provider)
    if caller is None or not provider_ready(provider):
        return {"text": _mock(system, user), "provider": "mock", "model": "mock",
                "ok": False, "truncated": False}

    kwargs = {"max_tokens": max_tokens} if max_tokens and provider in _ACCEPTS_MAX_TOKENS else {}
    last: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        if cancel is not None and cancel():
            break
        try:
            text = caller(system, user, cancel, **kwargs)
            # A blank reply is a failure wearing a 200: the seat contributed
            # nothing, and reporting ok=True hides that from the board. The
            # OpenAI-shaped readers raise EmptyReply themselves; this catches
            # the providers that simply hand back "".
            if not (text or "").strip():
                raise EmptyReply(f"{provider} returned an empty reply")
            return {"text": text, "provider": provider,
                    "model": config.PROVIDERS[provider]["model"], "ok": True,
                    "truncated": False}
        except Truncated as e:
            # Partial but real: hand back what was written and say it was cut, so
            # the caller can salvage it or re-ask on a bigger budget. Silently
            # passing this off as a finished answer is the whole bug.
            log.warning("provider %s hit its output ceiling (max_tokens=%s, %s chars kept)",
                        provider, max_tokens or "default", len(e.text))
            return {"text": e.text, "provider": provider,
                    "model": config.PROVIDERS[provider]["model"],
                    "ok": bool(e.text.strip()), "truncated": True}
        except Exception as e:  # noqa: BLE001 — a consult must never 500 the whole board
            last = e
            if attempt < attempts and _is_transient(e):
                wait = 2 ** attempt
                log.warning("provider %s attempt %s/%s failed (%s) — retrying in %ss",
                            provider, attempt, attempts, e, wait)
                time.sleep(wait)
                continue
            break

    log.warning("provider %s failed: %s", provider, last)
    return {"text": f"⚠️ {provider} ล้มเหลว: {str(last)[:200]}", "provider": provider,
            "model": config.PROVIDERS[provider]["model"], "ok": False, "truncated": False}


# ── JSON round-trip: ask for a schema and come back with one ───────────────

_REPAIR_RULES = (
    "กติกาการตอบรอบนี้ (ระบบอ่านอัตโนมัติ ผิดข้อเดียวคือใช้ไม่ได้ทั้งก้อน):\n"
    "- ตอบเป็น JSON object ล้วน เริ่มด้วย { และจบด้วย } เท่านั้น\n"
    "- ห้ามมีคำอธิบาย คำทักทาย หรือข้อความใดๆ นอกวงเล็บปีกกา และห้ามครอบด้วย ```\n"
    "- ใช้เครื่องหมายคำพูดตรง \" เท่านั้น ห้ามใช้ “ ” และห้ามใส่คอมเมนต์ // หรือ /* */\n"
    "- ห้ามมีเครื่องหมายจุลภาคค้างท้ายรายการสุดท้าย\n"
    "- ใช้ key ตาม schema เดิมทุกตัว ห้ามเปลี่ยนชื่อ ห้ามแปล key เป็นภาษาไทย\n"
    "- ตัวเลขต้องเป็นตัวเลขล้วน (เช่น 0.03 ไม่ใช่ \"3%\") ห้ามใส่หน่วยหรือจุลภาคในตัวเลข"
)


def _repair_prompt(user: str, broken: str, reason: str, keep: int = 1200) -> str:
    """Re-ask, showing the model exactly how its last reply failed. A model that
    is told 'that was not JSON' fixes it far more often than one asked again from
    scratch — and re-asking blind costs the same tokens for a worse hit rate."""
    tail = (broken or "").strip()
    excerpt = tail[:keep] + (" …[ตัดท้าย]" if len(tail) > keep else "")
    return (f"{user}\n\n"
            f"[ระบบอ่านคำตอบก่อนหน้าของคุณไม่สำเร็จ: {reason}]\n"
            f"คำตอบก่อนหน้า (ยกมาบางส่วน):\n---\n{excerpt}\n---\n"
            f"{_REPAIR_RULES}\n"
            "ถ้าเนื้อหายาวเกินไปจนตอบไม่จบ ให้ย่อข้อความในแต่ละช่องให้สั้นลง "
            "แต่ต้องมี key ครบทุกตัวและปิด JSON ให้สมบูรณ์")


def chat_json(provider: str, system: str, user: str, cancel=None,
              max_tokens: int | None = None, required=(), attempts: int = 3,
              repairs: int = 1) -> dict:
    """`chat()` for callers that asked the model for a schema, not for prose.

    Every JSON stage in the hub used to be one shot: call, `_parse_json`, and on
    anything unexpected fall back to a degraded page — a framing that convened
    the whole board because the moderator wrapped its JSON in a sentence, an
    empty options section because the reply was cut two keys from the end. The
    reply is usually *nearly* right, and the model will fix it if told what broke.

    So: read the reply, and when it is unusable say why and ask again —
    quoting the broken output, restating the format rules, and doubling the token
    budget when the cut was the cause. `required` names the keys that make the
    answer worth having; an object missing them counts as unusable, because a
    parse that succeeds into a hole is the failure that reaches the CEO looking
    like an answer.

    Returns `{data, text, provider, model, ok, truncated, calls, error}` where
    `data` is the parsed object or None. It never raises and never invents.
    """
    budget, asked, round_ = max_tokens, user, 0
    best, best_gaps, error = None, None, ""
    out = {"text": "", "provider": provider, "model": "mock", "ok": False, "truncated": False}

    for round_ in range(max(1, repairs + 1)):
        # `truncated` defaulted in, not assumed: chat() always sets it, but this
        # function is also the seam every test and every future transport stubs.
        out = {"truncated": False,
               **chat(provider, system, asked, cancel=cancel, max_tokens=budget,
                      attempts=attempts)}
        if not out["ok"]:
            # A dead provider or a missing key is not a formatting problem;
            # re-asking it just makes the CEO wait for the same error twice.
            error = error or out["text"][:200]
            break

        data = jsonx.extract(out["text"])
        gaps = jsonx.missing(data, required) if data is not None else list(required)
        if data is not None and (best is None or len(gaps) < len(best_gaps)):
            best, best_gaps = data, gaps      # keep the most complete read so far

        if data is None:
            error = "คำตอบไม่ใช่ JSON ที่อ่านได้"
        elif gaps:
            error = "JSON ขาด key ที่จำเป็น: " + ", ".join(gaps)
        elif out["truncated"]:
            error = "คำตอบถูกตัดกลางคัน (เกินเพดาน token)"
        else:
            return {"data": data, **out, "calls": round_ + 1, "error": ""}

        if round_ >= repairs or (cancel is not None and cancel()):
            break
        if out["truncated"]:
            if (budget or 2048) >= MAX_TOKENS_CEILING:
                break                          # more budget is not the problem
            budget = min(MAX_TOKENS_CEILING, (budget or 2048) * 2)
            log.warning("%s reply was cut — re-asking on a %s-token budget",
                        provider, budget)
        else:
            log.warning("%s reply unusable (%s) — asking it to fix the format",
                        provider, error)
        asked = _repair_prompt(user, out["text"], error)

    return {"data": best, **out, "calls": round_ + 1, "error": error}
