"""Embedding service，使用 OpenAI 兼容接口，带离线降级。

配置从 settings_service 动态读取。未配置有效 API Key 时，embedding 不可用，
调用方（search_service / paper_service）应降级为关键词检索 / 跳过向量化。
"""
from openai import OpenAI
from sqlalchemy.orm import Session

from app.services import settings_service

# 占位 key，视为「未配置」
_PLACEHOLDER_KEYS = {"", "sk-xxx", "sk-[YOUR_API_KEY]"}


def _config(db: Session, user_id):
    return settings_service.get_llm_config(db, str(user_id))


def is_available(db: Session, user_id) -> bool:
    """当前是否配置了可用的 Embedding API。"""
    try:
        cfg = _config(db, user_id)
        key = (cfg.get("api_key") or "").strip()
        return bool(key) and key not in _PLACEHOLDER_KEYS
    except Exception:  # noqa: BLE001
        return False


def embed(db: Session, user_id, text: str) -> list[float]:
    cfg = _config(db, user_id)
    client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
    resp = client.embeddings.create(model=cfg["embedding_model"], input=text)
    return list(resp.data[0].embedding)


def embed_many(db: Session, user_id, texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    cfg = _config(db, user_id)
    client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
    resp = client.embeddings.create(model=cfg["embedding_model"], input=texts)
    data = sorted(resp.data, key=lambda d: d.index)
    return [list(d.embedding) for d in data]