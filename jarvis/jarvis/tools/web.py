"""Web tools (§6, §12) — search the web and read pages.

  * WebSearch — free web search via DuckDuckGo (no API key). Backend is pluggable so tests
    inject fake results and never hit the network.
  * web_fetch — fetch a URL and return readable text (tags stripped). Fetcher is injectable.

These are the tools that let agents do real research instead of answering from memory.
Reads are reversible (no approval needed); they run on the user's own machine (legitimate).
"""
from __future__ import annotations

import re
from typing import Callable, Optional

from .base import ToolResult


# ---- web search backends -------------------------------------------------

def _ddg_backend(query: str, max_results: int) -> list[dict]:
    """DuckDuckGo search backend (no API key). Lazily imports the ddgs library."""
    try:
        from ddgs import DDGS  # newer package name
    except ImportError:
        from duckduckgo_search import DDGS  # older name
    out = []
    with DDGS() as d:
        for r in d.text(query, max_results=max_results):
            out.append({
                "title": r.get("title", ""),
                "url": r.get("href") or r.get("url", ""),
                "snippet": r.get("body", ""),
            })
    return out


def make_tavily_backend(api_key: str) -> Callable[[str, int], list[dict]]:
    """Tavily search backend (AI-agent grade, returns extracted content).

    Raises on quota/limit/errors so WebSearch falls back to DuckDuckGo automatically.
    """
    def backend(query: str, max_results: int) -> list[dict]:
        import json
        import urllib.request

        payload = json.dumps({
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "api_key": api_key,  # body auth (classic)
        }).encode()
        req = urllib.request.Request(
            "https://api.tavily.com/search", data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"},  # header auth (current)
        )
        with urllib.request.urlopen(req, timeout=15) as r:  # HTTPError on quota → fallback
            data = json.loads(r.read().decode())
        return [{"title": it.get("title", ""), "url": it.get("url", ""),
                 "snippet": it.get("content", "")} for it in data.get("results", [])]
    return backend


class WebSearch:
    """Tries each backend in order; first one that returns results wins.

    Default order: Tavily (if a key is given) → DuckDuckGo. So it uses Tavily's better
    results while it works, and falls back to free DDG on any error/limit.
    """

    def __init__(
        self,
        tavily_api_key: Optional[str] = None,
        *,
        backend: Optional[Callable[[str, int], list[dict]]] = None,
        fallback: Optional[Callable[[str, int], list[dict]]] = None,
    ):
        # backends are (name, fn) so we can report which one actually served the query.
        if backend is not None:
            self.backends = [("custom", backend)]
            if fallback is not None:
                self.backends.append(("fallback", fallback))
        else:
            self.backends = []
            if tavily_api_key:
                self.backends.append(("tavily", make_tavily_backend(tavily_api_key)))
            self.backends.append(("duckduckgo", _ddg_backend))
        self.last_source: Optional[str] = None

    def search(self, query: str, max_results: int = 5) -> ToolResult:
        if not query or not query.strip():
            return ToolResult.failure("empty query")
        last_error: Optional[str] = None
        got_any_response = False
        for name, b in self.backends:
            try:
                results = b(query, max_results)
            except ImportError:
                last_error = "web search needs the 'ddgs' package: pip install ddgs"
                continue
            except Exception as e:
                last_error = f"{name}: {e}"
                continue  # this backend failed/limited → try the next
            got_any_response = True
            if results:
                self.last_source = name
                lines = [f"[search via {name}]"]
                lines += [f"{i+1}. {r['title']}\n   {r['url']}\n   {r['snippet']}"
                          for i, r in enumerate(results)]
                return ToolResult.success("\n".join(lines))
        if not got_any_response and last_error:
            return ToolResult.failure(f"search failed ({last_error})")
        return ToolResult.success(f"No results for {query!r}.")


# ---- web fetch (read a page) ---------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_WS_RE = re.compile(r"[ \t]*\n[ \t]*")


def html_to_text(html: str) -> str:
    """Very small HTML → readable text: drop scripts/styles/tags, collapse whitespace."""
    if not html:
        return ""
    html = _SCRIPT_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", html)
    # unescape a few common entities
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'"),
                 ("&nbsp;", " ")):
        text = text.replace(a, b)
    text = _WS_RE.sub("\n", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _urllib_fetch(url: str, timeout: float = 15.0) -> str:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Jarvis)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        charset = r.headers.get_content_charset() or "utf-8"
        return r.read().decode(charset, errors="replace")


def web_fetch(url: str, *, fetcher: Optional[Callable[[str], str]] = None,
              max_chars: int = 4000) -> ToolResult:
    if not url or not url.startswith(("http://", "https://")):
        return ToolResult.failure("provide a full http(s) URL")
    fetcher = fetcher or _urllib_fetch
    try:
        html = fetcher(url)
    except Exception as e:
        return ToolResult.failure(f"couldn't fetch: {e}")
    text = html_to_text(html)
    if len(text) > max_chars:
        text = text[:max_chars] + " …(truncated)"
    return ToolResult.success(text or "(page had no readable text)")
