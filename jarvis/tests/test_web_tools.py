"""Web tool tests (§6, §12) — search (stub backend), fetch (stub fetcher), html→text."""
from jarvis.tools import WebSearch, web_fetch, html_to_text
from jarvis.journal import StagingStore


# ---- web search ----------------------------------------------------------

def _fake_backend(query, max_results):
    return [
        {"title": "Pomodoro Technique", "url": "https://ex.com/pomodoro", "snippet": "25 min sprints"},
        {"title": "Deep Work", "url": "https://ex.com/deep", "snippet": "focus blocks"},
    ][:max_results]


def test_web_search_formats_results():
    ws = WebSearch(backend=_fake_backend)
    res = ws.search("focus techniques", max_results=2)
    assert res.ok
    assert "Pomodoro Technique" in res.output
    assert "https://ex.com/pomodoro" in res.output


def test_web_search_empty_query():
    assert WebSearch(backend=_fake_backend).search("").ok is False


def test_web_search_no_results():
    res = WebSearch(backend=lambda q, n: []).search("zzz")
    assert res.ok and "No results" in res.output


def test_web_search_backend_error_graceful():
    def boom(q, n):
        raise RuntimeError("network down")
    res = WebSearch(backend=boom).search("x")
    assert res.ok is False and "network down" in res.error


def test_tavily_used_first_then_fallback_to_ddg():
    # Primary (Tavily) raises (e.g. quota) → falls back to DDG.
    def tavily_over_quota(q, n):
        raise RuntimeError("432 quota exceeded")
    ws = WebSearch(backend=tavily_over_quota, fallback=_fake_backend)
    res = ws.search("focus techniques")
    assert res.ok
    assert "Pomodoro Technique" in res.output   # came from the DDG fallback


def test_tavily_used_when_it_works():
    def tavily_ok(q, n):
        return [{"title": "Tavily result", "url": "https://t.co/x", "snippet": "clean content"}]
    ws = WebSearch(backend=tavily_ok, fallback=_fake_backend)
    res = ws.search("x")
    assert "Tavily result" in res.output          # primary won, fallback not used


# ---- html → text ---------------------------------------------------------

def test_html_to_text_strips_tags_and_scripts():
    html = "<html><head><style>.x{}</style></head><body><h1>Hi</h1>" \
           "<script>evil()</script><p>Hello &amp; welcome</p></body></html>"
    text = html_to_text(html)
    assert "Hi" in text and "Hello & welcome" in text
    assert "evil()" not in text and "<h1>" not in text


# ---- web fetch -----------------------------------------------------------

def test_web_fetch_returns_clean_text():
    res = web_fetch("https://ex.com", fetcher=lambda u: "<p>Clean <b>text</b> here</p>")
    assert res.ok
    assert "Clean text here" in res.output


def test_web_fetch_rejects_bad_url():
    assert web_fetch("not-a-url").ok is False


def test_web_fetch_truncates():
    big = "<p>" + ("word " * 5000) + "</p>"
    res = web_fetch("https://ex.com", fetcher=lambda u: big, max_chars=100)
    assert res.ok and "truncated" in res.output


# ---- staging prune -------------------------------------------------------

def test_staging_prune_removes_old(tmp_path):
    import time
    s = StagingStore(tmp_path / "st")
    s.add("note", "old scratch", {})
    # Prune everything older than 0s in the future.
    removed = s.prune(older_than_seconds=0, now=time.time() + 10)
    assert removed == 1
    assert s.list() == []
