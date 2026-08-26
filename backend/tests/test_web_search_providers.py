"""联网搜索提供方配置与文本清洗的轻量测试（不依赖外部网络）。"""

from app.config import settings
from app.services import web_search_providers


def test_anysearch_enabled_env_override(monkeypatch):
    monkeypatch.setenv("ANYSEARCH_ENABLED", "0")
    assert web_search_providers.anysearch_enabled() is False
    monkeypatch.setenv("ANYSEARCH_ENABLED", "1")
    assert web_search_providers.anysearch_enabled() is True


def test_searxng_configured_uses_settings(monkeypatch):
    monkeypatch.setattr(settings, "SEARXNG_URL", "")
    assert web_search_providers.searxng_configured() is False
    monkeypatch.setattr(settings, "SEARXNG_URL", "http://localhost:8888")
    assert web_search_providers.searxng_configured() is True


def test_clean_text_strips_html():
    assert web_search_providers._clean_text("<p>Hello <b>world</b></p>") == "Hello world"


def test_normalize_url_removes_tracking_parameters():
    canonical, display = web_search_providers.normalize_url(
        "https://WWW.Example.com/path/?utm_source=x&q=ceramic"
    )
    assert canonical == "https://example.com/path?q=ceramic"
    assert display.startswith("https://example.com/path/")
    assert "utm_source" not in display


def test_rank_results_deduplicates_and_boosts_consensus():
    rows = [
        {"title": "Ceramic materials", "url": "https://arxiv.org/a", "snippet": "ceramic", "source": "bing"},
        {"title": "Ceramic materials", "url": "https://arxiv.org/a/", "snippet": "longer ceramic evidence", "source": "crossref"},
        {"title": "Unrelated page", "url": "https://example.com/b", "snippet": "", "source": "duckduckgo"},
    ]
    ranked = web_search_providers.rank_results(rows, "ceramic materials", limit=3)
    assert ranked[0]["url"] == "https://arxiv.org/a"
    assert ranked[0]["providers"] == ["bing", "crossref"]
    assert len(ranked) == 2
    assert ranked[0]["score"] > ranked[1]["score"]


def test_extract_html_text_prefers_article_and_removes_scripts():
    html = """
    <html><body><script>bad()</script><nav>menu</nav>
    <article><h1>Ceramics</h1><p>Zirconia is a technical ceramic used in dental applications.</p></article>
    </body></html>
    """
    text = web_search_providers.extract_html_text(html)
    assert "Zirconia is a technical ceramic" in text
    assert "bad()" not in text
    assert "menu" not in text
