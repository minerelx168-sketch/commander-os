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
    r = httpx.post("https://api.tavily.com/search",
                   json={"api_key": config.TAVILY_API_KEY, "query": query,
                         "max_results": k, "search_depth": "advanced",
                         "include_answer": False},
                   timeout=TIMEOUT)
    r.raise_for_status()
    return [{"title": x.get("title", ""), "url": x.get("url", ""),
             "snippet": x.get("content", "")[:1200], "content": x.get("raw_content")}
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


def _duckduckgo(query: str, k: int) -> list[dict]:
    last_error: Exception | None = None
    for endpoint in _DDG_ENDPOINTS:
        try:
            r = httpx.post(endpoint, data={"q": query}, headers=_DDG_HEADERS,
                           timeout=TIMEOUT, follow_redirects=True)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001 — try the next endpoint
            last_error = e
            continue
        for pattern in _DDG_PATTERNS:
            out = []
            for m in pattern.finditer(r.text):
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
    if last_error is not None:
        raise last_error
    return []


# Backends are resolved by NAME at call time, not bound at import time: binding
# the function objects here would freeze them into this dict, so patching
# app.research._duckduckgo (tests, hot-swaps) would silently keep hitting the
# real network instead of the replacement.
_BACKENDS = {"tavily": "_tavily", "brave": "_brave", "serper": "_serper",
             "duckduckgo": "_duckduckgo"}


def search(query: str, k: int = 5) -> list[dict]:
    """One search against the active backend. Never raises — a dead backend
    must not take the whole consult down with it."""
    try:
        return globals()[_BACKENDS[backend()]](query, k)
    except Exception as e:  # noqa: BLE001
        log.warning("search backend %s failed for %r: %s", backend(), query, e)
        return []


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
           cancel=None) -> list[dict]:
    """Run every query, de-duplicate by URL, and make sure each surviving
    source carries enough body text for the analyst to screen it."""
    seen: dict[str, dict] = {}
    for q in queries:
        if cancel is not None and cancel():
            break
        for hit in search(q, per_query):
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
    return sources


def as_prompt(sources: list[dict], max_chars: int = 9000) -> str:
    """Numbered dossier the analyst screens; numbers become the citations."""
    parts = []
    for i, s in enumerate(sources, 1):
        parts.append(f"[{i}] {s.get('title', '(ไม่มีชื่อเรื่อง)')}\nURL: {s.get('url', '')}\n"
                     f"เนื้อหา: {s.get('body') or s.get('snippet', '')}")
    return "\n\n".join(parts)[:max_chars]
