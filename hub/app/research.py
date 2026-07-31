"""Web research layer — the board is grounded in the open internet, not only
the CEO's own document library.

Search backend is chosen by whichever key exists, best first, and degrades to
a keyless DuckDuckGo fallback so the feature works out of the box:

    TAVILY_API_KEY  -> Tavily   (LLM-oriented, returns extracted content)
    BRAVE_API_KEY   -> Brave Search API
    SERPER_API_KEY  -> serper.dev (Google index)
    (none)          -> DuckDuckGo lite HTML

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


def backend() -> str:
    if config.TAVILY_API_KEY:
        return "tavily"
    if config.BRAVE_API_KEY:
        return "brave"
    if config.SERPER_API_KEY:
        return "serper"
    return "duckduckgo"


def backend_label() -> str:
    return {"tavily": "Tavily", "brave": "Brave Search", "serper": "Serper (Google)",
            "duckduckgo": "DuckDuckGo (ไม่ต้องใช้ key)"}[backend()]


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


def _serper(query: str, k: int) -> list[dict]:
    r = httpx.post("https://google.serper.dev/search",
                   headers={"X-API-KEY": config.SERPER_API_KEY},
                   json={"q": query, "num": k}, timeout=TIMEOUT)
    r.raise_for_status()
    return [{"title": x.get("title", ""), "url": x.get("link", ""),
             "snippet": x.get("snippet", "")}
            for x in r.json().get("organic", [])]


# DuckDuckGo serves two different markups; support both so a layout change on
# one endpoint does not silently kill keyless research.
_DDG_PATTERNS = (
    # lite layout: <a rel=… href=… class="result-link">  (href comes before class)
    re.compile(r'<a(?P<attrs>[^>]*\bclass="result-link"[^>]*)>(?P<title>.*?)</a>'
               r'.*?class="result-snippet"[^>]*>(?P<snippet>.*?)</td>', re.S),
    # html layout: <a rel=… class="result__a" href=…>
    re.compile(r'<a(?P<attrs>[^>]*\bclass="result__a"[^>]*)>(?P<title>.*?)</a>'
               r'.*?class="result__snippet"[^>]*>(?P<snippet>.*?)</a>', re.S),
)
_HREF = re.compile(r'\bhref="([^"]+)"')
_DDG_ENDPOINTS = ("https://lite.duckduckgo.com/lite/", "https://html.duckduckgo.com/html/")
_DDG_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "th,en-US;q=0.9,en;q=0.8",
    "Referer": "https://duckduckgo.com/",
}


def _unwrap_ddg(url: str) -> str:
    """DDG wraps outbound links as //duckduckgo.com/l/?uddg=<encoded>."""
    url = html.unescape(url)
    if "uddg=" in url:
        from urllib.parse import parse_qs, unquote, urlparse
        target = parse_qs(urlparse(url if url.startswith("http") else "https:" + url).query).get("uddg")
        if target:
            return unquote(target[0])
    return url


class BlockedError(RuntimeError):
    """The engine answered, but with a bot check instead of results."""


def _parse_ddg(html_text: str, k: int) -> list[dict]:
    for pattern in _DDG_PATTERNS:
        out = []
        for m in pattern.finditer(html_text):
            href = _HREF.search(m.group("attrs"))
            if not href:
                continue
            out.append({"title": _strip_html(m.group("title")),
                        "url": _unwrap_ddg(href.group(1)),
                        "snippet": _strip_html(m.group("snippet"))})
            if len(out) >= k:
                break
        if out:
            return out
    return []


def _duckduckgo(query: str, k: int) -> list[dict]:
    """Keyless fallback. DuckDuckGo throttles automated traffic hard, so try
    GET before POST on both endpoints — a POST-only client is the first thing
    its bot check rejects."""
    last_error: Exception | None = None
    for endpoint in _DDG_ENDPOINTS:
        for method in ("GET", "POST"):
            try:
                if method == "GET":
                    r = httpx.get(endpoint, params={"q": query}, headers=_DDG_HEADERS,
                                  timeout=TIMEOUT, follow_redirects=True)
                else:
                    r = httpx.post(endpoint, data={"q": query}, headers=_DDG_HEADERS,
                                   timeout=TIMEOUT, follow_redirects=True)
                r.raise_for_status()
            except Exception as e:  # noqa: BLE001 — try the next shape
                last_error = e
                continue
            out = _parse_ddg(r.text, k)
            if out:
                return out
            # 200 with nothing parseable is DuckDuckGo's bot-check page, not an
            # empty index. Saying "no results" here is what makes a blocked
            # search look like a subject the internet has nothing on.
            last_error = BlockedError(
                "DuckDuckGo ตอบกลับมาแต่ไม่มีผลลัพธ์ที่อ่านได้ (น่าจะโดนหน้าตรวจบอท)")
    if last_error is not None:
        raise last_error
    return []


_MOJEEK_ROW = re.compile(
    r'<a[^>]*\bclass="ob"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>'
    r'.*?<p class="s">(?P<snippet>.*?)</p>', re.S)


def _mojeek(query: str, k: int) -> list[dict]:
    """A second keyless engine on an independent index. When DuckDuckGo blocks
    us there is otherwise nothing left, and the board silently loses the web."""
    r = httpx.get("https://www.mojeek.com/search", params={"q": query},
                  headers=_DDG_HEADERS, timeout=TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    out = []
    for m in _MOJEEK_ROW.finditer(r.text):
        url = html.unescape(m.group("url"))
        if not url.startswith("http"):
            continue
        out.append({"title": _strip_html(m.group("title")), "url": url,
                    "snippet": _strip_html(m.group("snippet"))})
        if len(out) >= k:
            break
    if not out:
        raise BlockedError("Mojeek ตอบกลับมาแต่ไม่มีผลลัพธ์ที่อ่านได้")
    return out


# Backends are resolved by NAME at call time, not bound at import time: binding
# the function objects here would freeze them into this dict, so patching
# app.research._duckduckgo (tests, hot-swaps) would silently keep hitting the
# real network instead of the replacement.
_BACKENDS = {"tavily": "_tavily", "brave": "_brave", "serper": "_serper",
             "duckduckgo": "_duckduckgo"}
# Tried in order when no key is configured, so one engine's bot check does not
# take the whole board's evidence with it.
_KEYLESS_CHAIN = ("_duckduckgo", "_mojeek")


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

    `search()` used to swallow every failure into an empty list, which made a
    blocked search indistinguishable from a subject the web has nothing on —
    and the board reported "ไม่พบหลักฐาน" for both.
    """
    name = backend()
    chain = _KEYLESS_CHAIN if name == "duckduckgo" else (_BACKENDS[name],)
    errors = []
    for fn in chain:
        try:
            results = globals()[fn](query, k)
        except Exception as e:  # noqa: BLE001 — a dead engine must not kill the consult
            log.warning("search %s failed for %r: %s", fn, query, e)
            errors.append(f"{fn.lstrip('_')}: {_reason(e)}")
            continue
        if results:
            return {"results": results, "error": None, "engine": fn.lstrip("_")}
        errors.append(f"{fn.lstrip('_')}: ไม่พบผลลัพธ์")
    return {"results": [], "error": " · ".join(errors) or "ไม่พบผลลัพธ์",
            "engine": None}


def search(query: str, k: int = 5) -> list[dict]:
    """Results only. Prefer `search_detail` when the caller should be able to
    tell "blocked" from "genuinely nothing there"."""
    return search_detail(query, k)["results"]


def diagnose() -> dict:
    """Run one canary query so the CEO can tell a blocked search from a quiet
    one without reading server logs."""
    out = search_detail("ตลาดร้านอาหาร กรุงเทพ 2026", 3)
    return {"backend": backend(), "label": backend_label(),
            "keyed": backend() != "duckduckgo",
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
