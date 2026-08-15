"""应用设置服务：从数据库读取/更新用户配置，带进程内缓存。

支持 LLM API 配置（api_key/base_url/model/embedding_model/embedding_dim）
和界面主题配置（theme_color）。LLM 配置可在运行时通过设置页面修改，
llm_service / embedding_service 通过本服务获取当前生效配置。
"""
import json
import threading
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.models.app_setting import AppSetting

# 默认值：优先用环境变量，否则用内置默认
_DEFAULTS: dict[str, Any] = {
    "llm_api_key": app_settings.LLM_API_KEY,
    "llm_base_url": app_settings.LLM_BASE_URL,
    "llm_model": app_settings.LLM_MODEL,
    "embedding_model": app_settings.EMBEDDING_MODEL,
    "embedding_dim": app_settings.EMBEDDING_DIM,
    "theme_color": "#4f46e5",
}

# 进程内缓存：user_id -> {key: value}
_cache: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _to_value(raw: Optional[str]) -> Any:
    """存储的 value 是文本；尝试还原 JSON 类型，否则返回原始字符串。"""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw


def _from_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, bool, int, float)):
        return json.dumps(value)
    return str(value)


def get_all(db: Session, user_id: str) -> dict[str, Any]:
    """读取某用户的全部设置（合并默认值）。"""
    with _lock:
        cached = _cache.get(user_id)

    if cached is not None:
        # 缓存命中，但仍然补齐默认值
        result = dict(_DEFAULTS)
        result.update(cached)
        return result

    rows = db.query(AppSetting).filter(AppSetting.user_id == user_id).all()
    loaded: dict[str, Any] = {}
    for row in rows:
        loaded[row.key] = _to_value(row.value)

    with _lock:
        _cache[user_id] = loaded

    result = dict(_DEFAULTS)
    result.update(loaded)
    return result


def get(db: Session, user_id: str, key: str) -> Any:
    return get_all(db, user_id).get(key)


def update_many(db: Session, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """批量更新设置，并刷新缓存。"""
    for key, value in payload.items():
        if key not in _DEFAULTS:
            # 忽略未知键，避免污染配置
            continue
        existing = (
            db.query(AppSetting)
            .filter(AppSetting.user_id == user_id, AppSetting.key == key)
            .first()
        )
        if existing:
            existing.value = _from_value(value)
        else:
            db.add(
                AppSetting(user_id=user_id, key=key, value=_from_value(value))
            )
    db.commit()

    # 刷新缓存
    with _lock:
        _cache.pop(user_id, None)
    return get_all(db, user_id)


def invalidate(user_id: str) -> None:
    with _lock:
        _cache.pop(user_id, None)


def get_llm_config(db: Session, user_id: str) -> dict[str, Any]:
    """返回当前生效的 LLM 配置，供 llm_service / embedding_service 使用。"""
    cfg = get_all(db, user_id)
    return {
        "api_key": cfg.get("llm_api_key") or app_settings.LLM_API_KEY,
        "base_url": cfg.get("llm_base_url") or app_settings.LLM_BASE_URL,
        "model": cfg.get("llm_model") or app_settings.LLM_MODEL,
        "embedding_model": cfg.get("embedding_model") or app_settings.EMBEDDING_MODEL,
        "embedding_dim": int(cfg.get("embedding_dim") or app_settings.EMBEDDING_DIM),
    }
