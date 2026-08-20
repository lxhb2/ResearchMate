"""本地翻译缓存：重复的短句/术语秒回，减少 LLM/API 调用。"""
import hashlib
import json
import os
import threading

from app.config import settings as app_settings

_MAX_ENTRIES = 2000
_lock = threading.Lock()
_memory: dict[str, str] = {}


def _path() -> str:
    d = os.path.join(app_settings.STORAGE_DIR, "agent")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "translation_cache.json")


def _key(lang_in: str, lang_out: str, text: str) -> str:
    return hashlib.sha256(f"{lang_in}|{lang_out}|{text}".encode("utf-8")).hexdigest()[:40]


def get(lang_in: str, lang_out: str, text: str) -> str | None:
    k = _key(lang_in, lang_out, text)
    with _lock:
        if k in _memory:
            return _memory[k]
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
        val = data.get(k)
        if val is not None:
            with _lock:
                _memory[k] = val
        return val
    except (OSError, ValueError):
        return None


def set(lang_in: str, lang_out: str, text: str, translation: str) -> None:
    k = _key(lang_in, lang_out, text)
    with _lock:
        _memory[k] = translation
        if len(_memory) > _MAX_ENTRIES * 2:
            _memory.clear()
    try:
        data = {}
        if os.path.isfile(_path()):
            try:
                with open(_path(), encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                data = {}
        data[k] = translation
        if len(data) > _MAX_ENTRIES:
            data = dict(list(data.items())[-_MAX_ENTRIES:])
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError:
        pass
