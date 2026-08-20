"""翻译引擎配置与产物挑选的轻量回归测试（不依赖外部网络）。"""


def test_pdf2zh_engine_defaults_to_free(monkeypatch):
    from app.services import pdf2zh_service

    monkeypatch.delenv("PDF2ZH_ENGINE", raising=False)
    monkeypatch.delenv("PDF2ZH_SILICONFLOW_API_KEY", raising=False)
    cfg = pdf2zh_service._engine_config({"api_key": "sk-xxx"})
    assert cfg["engine"] == "siliconflowfree"


def test_pdf2zh_engine_uses_configured_llm(monkeypatch):
    from app.services import pdf2zh_service

    monkeypatch.delenv("PDF2ZH_ENGINE", raising=False)
    monkeypatch.delenv("PDF2ZH_SILICONFLOW_API_KEY", raising=False)
    cfg = pdf2zh_service._engine_config(
        {
            "api_key": "sk-real-key",
            "base_url": "https://api.example.com/v1",
            "model": "fast-model",
        }
    )
    assert cfg["engine"] == "openai"
    assert cfg["model"] == "fast-model"


def test_pdf2zh_pick_prefers_dual():
    from app.services import pdf2zh_service

    files = ["paper.zh.mono.pdf", "paper.zh.dual.pdf"]
    assert pdf2zh_service.pick_translated_pdf(files) == "paper.zh.dual.pdf"


def test_free_translate_can_be_disabled(monkeypatch):
    from app.services import free_translate_service

    monkeypatch.setenv("TRANSLATION_FREE_SERVICE", "0")
    assert free_translate_service.enabled() is False
    monkeypatch.setenv("TRANSLATION_FREE_SERVICE", "1")
    assert free_translate_service.enabled() is True
