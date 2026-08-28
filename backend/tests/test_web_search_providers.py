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


def test_agentsearch_items_maps_content_and_provenance():
    rows = web_search_providers._agentsearch_items(
        {
            "results": [
                {
                    "title": "AgentSearch",
                    "url": "https://example.com/a",
                    "snippet": "<p>clean snippet</p>",
                    "content": "<p>clean content</p>",
                    "engines": ["arxiv", "crossref"],
                }
            ]
        }
    )
    assert len(rows) == 1
    assert rows[0]["source"] == "agentsearch"
    assert rows[0]["snippet"] == "clean snippet"
    assert rows[0]["content"] == "clean content"
    assert rows[0]["engines"] == ["arxiv", "crossref"]


def test_agentsearch_configured_reads_config(monkeypatch):
    assert web_search_providers.agentsearch_configured({"agentsearch_url": "http://localhost:3939"}) is True
    monkeypatch.setattr(web_search_providers.settings, "AGENTSEARCH_URL", "")
    assert web_search_providers.agentsearch_configured() is False


def test_rank_results_keeps_extracted_content():
    ranked = web_search_providers.rank_results(
        [
            {
                "title": "Search",
                "url": "https://example.com/search",
                "snippet": "short",
                "content": "<p>full readable evidence</p>",
                "source": "agentsearch",
            }
        ],
        "search",
        limit=1,
    )
    assert ranked[0]["content"] == "full readable evidence"


def test_retry_provider_retries_then_succeeds(monkeypatch):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("timeout")
        return {"items": [{"title": "ok", "url": "https://example.com"}]}

    monkeypatch.setattr(web_search_providers.time, "sleep", lambda _seconds: None)
    assert web_search_providers._retry_provider(flaky)["items"]


def test_normalize_academic_sources_keeps_order_and_rejects_unknown():
    assert web_search_providers.normalize_academic_sources(
        ["crossref", "Europe-PMC", "unknown", "crossref"]
    ) == ["crossref", "europe_pmc"]
    assert web_search_providers.normalize_academic_sources("") == web_search_providers.DEFAULT_ACADEMIC_SOURCES


def test_deep_web_search_academic_mode_uses_selected_sources_only(monkeypatch):
    called: list[str] = []

    def fake_openalex(query, limit, timeout):
        called.append("openalex")
        return {
            "items": [
                {"title": "OpenAlex paper", "url": "https://doi.org/10.1000/a", "snippet": "paper", "source": "openalex", "academic": True}
                for _ in range(10)
            ]
        }

    def fake_crossref(query, limit, timeout):
        called.append("crossref")
        return {
            "items": [
                {"title": "Crossref paper", "url": "https://doi.org/10.1000/b", "snippet": "paper", "source": "crossref", "academic": True}
                for _ in range(10)
            ]
        }

    def fail_europepmc(query, limit, timeout):
        called.append("europe_pmc")
        raise AssertionError("unselected provider should not be called")

    monkeypatch.setattr(web_search_providers, "openalex_search", fake_openalex)
    monkeypatch.setattr(web_search_providers, "crossref_search", fake_crossref)
    monkeypatch.setattr(web_search_providers, "europepmc_search", fail_europepmc)
    result = web_search_providers.deep_web_search(
        "graph neural networks papers",
        limit=5,
        mode="academic",
        academic_sources=["openalex", "crossref"],
        read_pages=0,
    )
    assert called == ["openalex", "crossref"] or set(called) == {"openalex", "crossref"}
    assert result["mode"] == "academic"
    assert result["academic_sources"] == ["openalex", "crossref"]
    assert result["providers"] == ["crossref", "openalex"]
    assert {item["source"] for item in result["items"]} <= {"openalex", "crossref"}


def test_wikidata_search_maps_entities(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "search": [
                    {
                        "id": "Q42",
                        "label": "Douglas Adams",
                        "description": "English writer",
                        "concepturi": "https://www.wikidata.org/wiki/Q42",
                    }
                ]
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(web_search_providers.httpx, "Client", FakeClient)
    result = web_search_providers.wikidata_search("Douglas Adams")
    assert result["count"] == 1
    assert result["items"][0]["source"] == "wikidata"
    assert result["items"][0]["url"] == "https://www.wikidata.org/wiki/Q42"
