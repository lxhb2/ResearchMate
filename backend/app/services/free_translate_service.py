"""SiliconFlow Free short-text translation proxy (fast, zero-config).

This is the same free service used by PDFMathTranslate-next's GUI.  It is
used as a low-latency fallback for selection translation when the user has
not configured DeepL; it can be disabled with ``TRANSLATION_FREE_SERVICE=0``.
"""

from __future__ import annotations

import os
import threading

import httpx

_ENDPOINTS = (
    "https://api1.pdf2zh-next.com/chatproxy",
    "https://api2.pdf2zh-next.com/chatproxy",
)
_lock = threading.Lock()
_selected: str | None = None


def enabled() -> bool:
    raw = os.environ.get("TRANSLATION_FREE_SERVICE", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _lang_name(code: str) -> str:
    return {
        "zh": "Chinese (Simplified)",
        "zh-cn": "Chinese (Simplified)",
        "zh-hans": "Chinese (Simplified)",
        "en": "English",
        "ja": "Japanese",
        "ko": "Korean",
        "fr": "French",
        "de": "German",
        "es": "Spanish",
        "ru": "Russian",
    }.get((code or "zh").lower(), code or "Chinese (Simplified)")


def translate(text: str, target_lang: str = "zh", timeout: float = 15.0) -> str:
    """Translate one short text through the free proxy."""
    global _selected

    prompt = (
        "You are a professional, authentic machine translation engine.\n\n"
        ";; Treat next line as plain text input and translate it into "
        f"{_lang_name(target_lang)}, output translation ONLY. "
        "If translation is unnecessary (e.g. proper nouns, codes, {{1}}, etc.), "
        "return the original text. NO explanations. NO notes.\n\n"
        f"{text}"
    )
    endpoints = [_selected] if _selected else list(_ENDPOINTS)
    if _selected is None:
        endpoints = list(_ENDPOINTS)

    last_error: Exception | None = None
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for endpoint in endpoints:
            for _attempt in range(2):
                try:
                    resp = client.post(endpoint, json={"text": prompt})
                    resp.raise_for_status()
                    payload = resp.json()
                    content = (payload.get("content") or "").strip()
                    if content:
                        with _lock:
                            if _selected is None:
                                _selected = endpoint
                        return content
                    last_error = RuntimeError("免费翻译服务返回空内容")
                except httpx.HTTPStatusError as exc:  # 400/5xx 一般不可重试
                    last_error = exc
                    break
                except Exception as exc:  # noqa: BLE001 - retry / try next endpoint
                    last_error = exc
                    continue
    raise RuntimeError(f"免费翻译服务不可用：{last_error}")
