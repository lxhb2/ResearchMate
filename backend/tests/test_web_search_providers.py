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
