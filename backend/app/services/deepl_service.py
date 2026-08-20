"""DeepL 翻译 API 直连（可选加速，配置 DEEPL_API_KEY 后自动启用）。"""
import os

import httpx

from app.config import settings as app_settings


def api_key() -> str:
    return (os.environ.get("DEEPL_API_KEY") or app_settings.DEEPL_API_KEY or "").strip()


def available() -> bool:
    return bool(api_key())


def _lang_code(code: str) -> str:
    c = (code or "zh").lower()
    return {
        "zh": "ZH",
        "zh-cn": "ZH",
        "zh-hans": "ZH",
        "en": "EN-US",
        "ja": "JA",
        "ko": "KO",
        "fr": "FR",
        "de": "DE",
        "es": "ES",
        "ru": "RU",
    }.get(c, c.upper())


def translate(text: str, target_lang: str = "zh", source_lang: str = "", timeout: float = 20.0) -> str:
    url = os.environ.get("DEEPL_API_URL") or "https://api-free.deepl.com/v2/translate"
    data = {
        "auth_key": api_key(),
        "text": text,
        "target_lang": _lang_code(target_lang),
    }
    if source_lang:
        data["source_lang"] = _lang_code(source_lang)
    resp = httpx.post(url, data=data, timeout=timeout)
    resp.raise_for_status()
    items = resp.json().get("translations") or []
    return items[0].get("text", "") if items else ""
