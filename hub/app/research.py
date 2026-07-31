"""Web research layer — the board is grounded in the open internet, not only
the CEO's own document library.

Search runs on **paid, keyed indexes only**. Every configured backend is tried
in order, so one API having a bad minute costs latency rather than evidence:

    TAVILY_API_KEY  -> Tavily     (LLM-oriented, returns extracted content)
    SERPAPI_API_KEY -> SerpApi    (Google index, Thai locale)
    BRAVE_API_KEY   -> Brave      (independent index)
    SERPER_API_KEY  -> serper.dev (Google, cheaper)

There is deliberately no keyless fallback. Scraping DuckDuckGo/Mojeek looked
free but returned bot-check pages that parsed as zero results, which the board
then reported as "ไม่พบหลักฐาน" — indistinguishable from a subject the web
genuinely has nothing on. A board that cannot search must say so loudly, not
quietly hand the CEO an evidence-free brief.

Raw results are never fed to the advisors directly. `depts.run_research`
sends them through an analyst pass that screens for relevance, credibility
and contradictions, and every claim carries a numbered source.
"""
import html
import logging
import re

import httpx

from . import config

log = logging.getLogger("hub.research")

TIMEOUT = 20.0
UA = "Mozilla/5.0 (compatible; CommanderHub/1.0; +strategic-advisory)"

# Priority order: Tavily first because it returns extracted page bodies (no
# per-source re-fetch), then Google indexes, then Brave.
_PRIORITY = (
    ("tavily", "TAVILY_API_KEY", "_tavily", "Tavily"),
    ("serpapi", "SERPAPI_API_KEY", "_serpapi", "SerpApi (Google)"),
    ("brave", "BRAVE_API_KEY", "_brave", "Brave Search"),
    ("serper", "SERPER_API_KEY", "_serper", "Serper (Google)"),
)


def configured() -> list[tuple[str, str, str]]:
    """(name, caller, label) for every backend that actually has a key."""
    return [(name, fn, label) for name, env, fn, label in _PRIORITY
            if getattr(config, env, "")]


def backend() -> str:
    """The backend a search will try first, or "none" when no key is set."""
    live = configured()
    return live[0][0] if live else "none"


def backend_label() -> str:
    live = configured()
    if not live:
        return "ยังไม่ได้ตั้งค่า API key สำหรับค้นหา"
    label = live[0][2]
    return label if len(live) == 1 else f"{label} (+{len(live) - 1} สำรอง)"


# ── search backends: each returns [{title, url, snippet, content?}] ──

def _tavily(query: str, k: int) -> list[dict]:
    """Tavily authenticates with a Bearer header, and only returns page bodies
    when asked — without include_raw_content every source came back with an
    empty body and had to be re-fetched one page at a time, which is the slow
    path Tavily exists to replace."""
    r = httpx.post("https://api.tavily.com/search",
                   headers={"Authorization": f"Bearer {config.TAVILY_API_KEY}",
                            "Content-Type": "application/json"},
                   json={"query": query, "max_results": k,
                         "search_depth": "advanced", "include_answer": False,
                         "include_raw_content": True},
                   timeout=TIMEOUT)
    r.raise_for_status()
    return [{"title": x.get("title", ""), "url": x.get("url", ""),
             "snippet": (x.get("content") or "")[:1200], "content": x.get("raw_content")}
            for x in r.json().get("results", [])]


def _brave(query: str, k: int) -> list[dict]:
    r = httpx.get("https://api.search.brave.com/res/v1/web/search",
                  headers={"X-Subscription-Token": config.BRAVE_API_KEY,
                           "Accept": "application/json"},
                  params={"q": query, "count": k}, timeout=TIMEOUT)
    r.raise_for_status()
    return [{"title": x.get("title", ""), "url": x.get("url", ""),
             "snippet": _strip_html(x.get("description", ""))}
            for x in r.json().get("web", {}).get("results", [])]


def _serpapi(query: str, k: int) -> list[dict]:
    """SerpApi — Google results via GET, with num capped at 20 per docs."""
    r = httpx.get("https://serpapi.com/search",
                  params={"engine": "google", "q": query,
                          "num": min(k, 20), "api_key": config.SERPAPI_API_KEY,
                          # Thai defaults so a query in Thai lands on Thai SERPs
                          "hl": "th", "gl": "th"},
                  timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    # SerpApi surfaces plan/quota issues in the payload with 200 OK — read it,
    # or a rate-limited key looks like an empty search.
    if data.get("error"):
        raise RuntimeError(data["error"])
    return [{"title": x.get("title", ""), "url": x.get("link", ""),
             "snippet": x.get("snippet", "")}
            for x in data.get("organic_results", []) if x.get("link")]


def _serper(query: str, k: int) -> list[dict]:
    r = httpx.post("https://google.serper.dev/search",
                   headers={"X-API-KEY": config.SERPER_API_KEY},
                   json={"q": query, "num": k}, timeout=TIMEOUT)
    r.raise_for_status()
    return [{"title": x.get("title", ""), "url": x.get("link", ""),
             "snippet": x.get("snippet", "")}
            for x in r.json().get("organic", [])]


class BlockedError(RuntimeError):
    """The engine answered, but with a bot check or an empty page."""




def _reason(exc: Exception) -> str:
    """A failure the CEO can act on, not a stack trace."""
    if isinstance(exc, BlockedError):
        return str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (403, 429, 202):
            return (f"ถูกบล็อก/จำกัดอัตราการค้น (HTTP {code}) — "
                    "เครื่องมือค้นแบบไม่ใช้ key ปฏิเสธคำขออัตโนมัติ")
        return f"เซิร์ฟเวอร์ค้นหาตอบ HTTP {code}"
    if isinstance(exc, httpx.TimeoutException):
        return "ค้นหาหมดเวลา (timeout) — เครือข่ายช้าหรือถูกบล็อก"
    if isinstance(exc, httpx.RequestError):
        return f"ต่อเครื่องมือค้นหาไม่ได้: {type(exc).__name__}"
    return f"{type(exc).__name__}: {str(exc)[:120]}"


def search_detail(query: str, k: int = 5) -> dict:
    """One search, with the reason it came back empty.

    Every configured backend is tried in priority order, so Tavily rate-limiting
    for a minute costs a second of latency instead of the board's evidence.
    `search()` used to swallow every failure into an empty list, which made a
    blocked search indistinguishable from a subject the web has nothing on —
    and the board reported "ไม่พบหลักฐาน" for both.
    """
    live = configured()
    if not live:
        return {"results": [], "engine": None,
                "error": ("ยังไม่ได้ตั้งค่า API key สำหรับค้นหา — ใส่ TAVILY_API_KEY "
                          "หรือ SERPAPI_API_KEY ใน hub/.env แล้วรีสตาร์ท hub "
                          "(ระบบไม่ใช้เครื่องมือค้นแบบไม่มี key แล้ว เพราะมันคืนหน้าตรวจบอท "
                          "ที่อ่านได้เป็น 'ไม่พบข้อมูล')")}
    errors = []
    for name, fn, _label in live:
        try:
            results = globals()[fn](query, k)
        except Exception as e:  # noqa: BLE001 — a dead engine must not kill the consult
            log.warning("search %s failed for %r: %s", name, query, e)
            errors.append(f"{name}: {_reason(e)}")
            continue
        if results:
            if errors:  # a fallback saved the search — worth knowing about
                log.info("search %s served %r after %s", name, query, "; ".join(errors))
            return {"results": results, "error": None, "engine": name}
        errors.append(f"{name}: ไม่พบผลลัพธ์")
    return {"results": [], "error": " · ".join(errors), "engine": None}


def search(query: str, k: int = 5) -> list[dict]:
    """Results only. Prefer `search_detail` when the caller should be able to
    tell "blocked" from "genuinely nothing there"."""
    return search_detail(query, k)["results"]


def diagnose() -> dict:
    """Run one canary query so the CEO can tell a blocked search from a quiet
    one without reading server logs."""
    out = search_detail("ตลาดร้านอาหาร กรุงเทพ 2026", 3)
    live = configured()
    return {"backend": backend(), "label": backend_label(),
            "keyed": bool(live), "backends": [n for n, _f, _l in live],
            "ok": bool(out["results"]), "engine": out["engine"],
            "found": len(out["results"]), "error": out["error"],
            "sample": [{"title": s.get("title", ""), "url": s.get("url", "")}
                       for s in out["results"][:3]]}


# ── page fetching (only when the backend gave no usable body text) ──

_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)
_WS = re.compile(r"\s+")


def _strip_html(raw: str) -> str:
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", raw or ""))).strip()


def fetch_text(url: str, max_chars: int = 4000) -> str:
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT,
                      follow_redirects=True)
        r.raise_for_status()
        if "html" not in r.headers.get("content-type", "") and not r.text:
            return ""
        return _strip_html(r.text)[:max_chars]
    except Exception as e:  # noqa: BLE001
        log.debug("fetch %s failed: %s", url, e)
        return ""


def gather(queries: list[str], per_query: int = 4, max_sources: int = 8,
           cancel=None) -> dict:
    """Run every query, de-duplicate by URL, and make sure each surviving
    source carries enough body text for the analyst to screen it.

    Returns {sources, errors} — the errors matter as much as the sources,
    because a caller that only sees an empty list cannot tell whether the web
    had nothing or the search never ran.
    """
    seen: dict[str, dict] = {}
    errors: list[str] = []
    for q in queries:
        if cancel is not None and cancel():
            break
        out = search_detail(q, per_query)
        if out["error"] and not out["results"]:
            errors.append(f"«{q}» → {out['error']}")
        for hit in out["results"]:
            url = (hit.get("url") or "").strip()
            if not url or url in seen:
                continue
            hit["query"] = q
            seen[url] = hit
    sources = list(seen.values())[:max_sources]
    for s in sources:
        if cancel is not None and cancel():
            break
        body = (s.get("content") or "").strip()
        if len(body) < 400:
            body = fetch_text(s["url"]) or s.get("snippet", "")
        s["body"] = body[:4000]
    return {"sources": sources, "errors": errors}


def as_prompt(sources: list[dict], max_chars: int = 9000) -> str:
    """Numbered dossier the analyst screens; numbers become the citations."""
    parts = []
    for i, s in enumerate(sources, 1):
        parts.append(f"[{i}] {s.get('title', '(ไม่มีชื่อเรื่อง)')}\nURL: {s.get('url', '')}\n"
                     f"เนื้อหา: {s.get('body') or s.get('snippet', '')}")
    return "\n\n".join(parts)[:max_chars]
