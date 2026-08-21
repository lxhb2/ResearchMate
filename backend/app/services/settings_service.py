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
from app.utils import secrets as secret_utils

# 默认值：优先用环境变量，否则用内置默认
_DEFAULTS: dict[str, Any] = {
    "llm_api_key": app_settings.LLM_API_KEY,
    "llm_base_url": app_settings.LLM_BASE_URL,
    "llm_model": app_settings.LLM_MODEL,
    "embedding_model": app_settings.EMBEDDING_MODEL,
    "embedding_dim": app_settings.EMBEDDING_DIM,
    "theme_color": "#4f46e5",
    "anysearch_enabled": bool(app_settings.ANYSEARCH_ENABLED),
    "anysearch_api_key": app_settings.ANYSEARCH_API_KEY,
    "anysearch_base_url": app_settings.ANYSEARCH_BASE_URL,
    "searxng_url": app_settings.SEARXNG_URL,
}

# 落库时需要加密的敏感配置项
_SECRET_KEYS = {"llm_api_key", "anysearch_api_key"}

# 推荐模型预设：后端统一维护，前端可兜底也可动态拉取
# 结构说明：每个 preset 包含展示名、base_url、推荐的聊天模型列表、推荐 embedding 模型、说明
MODEL_PRESETS: list[dict[str, Any]] = [
    {
        "name": "通义千问 (DashScope)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-plus", "qwen-max", "qwen-turbo", "qwen2.5-72b-instruct", "qwen2.5-7b-instruct"],
        "embedding_model": "text-embedding-v3",
        "help": "阿里云百炼，兼容 OpenAI 协议，model 推荐用 qwen-plus / qwen-max",
    },
    {
        "name": "智谱 AI (BigModel)",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4-plus", "glm-4", "glm-4-air", "glm-4-flash", "glm-4-flashx"],
        "embedding_model": "embedding-3",
        "help": "智谱 GLM 系列，glm-4-flash 免费可用",
    },
    {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner", "deepseek-coder"],
        "embedding_model": "",
        "help": "DeepSeek 官方 API，价格友好，推理能力强（暂不提供 embedding）",
    },
    {
        "name": "Moonshot (Kimi)",
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k", "kimi-latest"],
        "embedding_model": "",
        "help": "Kimi 长上下文模型，128k 适合长文献",
    },
    {
        "name": "百度千帆 (兼容模式)",
        "base_url": "https://qianfan.baidubce.com/v2",
        "models": ["ernie-4.0-8k-latest", "ernie-3.5-8k", "ernie-speed-128k", "ernie-lite-8k"],
        "embedding_model": "embedding-v1",
        "help": "百度千帆 v2 OpenAI 兼容接口",
    },
    {
        "name": "讯飞星火",
        "base_url": "https://spark-api-open.xf-yun.com/v1",
        "models": ["generalv3.5", "general", "spark-v4"],
        "embedding_model": "",
        "help": "讯飞星火 OpenAI 兼容接口",
    },
    {
        "name": "MiniMax",
        "base_url": "https://api.minimax.chat/v1",
        "models": ["abab6.5s-chat", "abab6.5-chat", "abab6-chat"],
        "embedding_model": "",
        "help": "MiniMax 开放平台",
    },
    {
        "name": "字节豆包 (VolcEngine)",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "models": ["doubao-pro-32k", "doubao-pro-128k", "doubao-lite-32k"],
        "embedding_model": "",
        "help": "火山方舟，需在控制台创建接入点 ID 作为 model",
    },
    {
        "name": "零一万物 (01.AI)",
        "base_url": "https://api.lingyiwanwu.com/v1",
        "models": ["yi-large", "yi-medium", "yi-lightning", "yi-vision"],
        "embedding_model": "",
        "help": "零一万物 Yi 系列",
    },
    {
        "name": "阶跃星辰 (Step)",
        "base_url": "https://api.stepfun.com/v1",
        "models": ["step-1-8k", "step-1-32k", "step-1-128k", "step-2-16k"],
        "embedding_model": "",
        "help": "Step 系列模型",
    },
    {
        "name": "OpenAI / Azure OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "o1-mini"],
        "embedding_model": "text-embedding-3-small",
        "help": "官方 OpenAI 或自建代理",
    },
    {
        "name": "本地 / Ollama",
        "base_url": "http://localhost:11434/v1",
        "models": ["llama3.1", "qwen2.5", "deepseek-r1", "phi3"],
        "embedding_model": "nomic-embed-text",
        "help": "本地部署的 Ollama，无需 API Key 可填任意字符串",
    },
    {
        "name": "本地 / LM Studio",
        "base_url": "http://localhost:1234/v1",
        "models": ["local-model"],
        "embedding_model": "nomic-embed-text",
        "help": "LM Studio 本地服务器模式",
    },
    {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "models": ["openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet", "google/gemini-flash-1.5"],
        "embedding_model": "",
        "help": "OpenRouter 统一路由，一个 Key 访问多厂商",
    },
    {
        "name": "SiliconFlow",
        "base_url": "https://api.siliconflow.cn/v1",
        "models": ["deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct", "meta-llama/Meta-Llama-3.1-70B-Instruct"],
        "embedding_model": "BAAI/bge-large-zh-v1.5",
        "help": "SiliconFlow 国内低价聚合平台",
    },
]

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
        value = _to_value(row.value)
        if row.key in _SECRET_KEYS and isinstance(value, str):
            value = secret_utils.decrypt_secret(value)
        loaded[row.key] = value

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
            existing.value = _store_value(key, value)
        else:
            db.add(
                AppSetting(user_id=user_id, key=key, value=_store_value(key, value))
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


def get_search_config(db: Session, user_id: str) -> dict[str, Any]:
    """返回当前生效的联网搜索配置，供 web_search 工具读取。"""
    cfg = get_all(db, user_id)
    return {
        "enabled": bool(cfg.get("anysearch_enabled", app_settings.ANYSEARCH_ENABLED)),
        "api_key": str(cfg.get("anysearch_api_key") or app_settings.ANYSEARCH_API_KEY),
        "base_url": str(cfg.get("anysearch_base_url") or app_settings.ANYSEARCH_BASE_URL),
        "searxng_url": str(cfg.get("searxng_url") or app_settings.SEARXNG_URL),
    }


def _store_value(key: str, value: Any) -> str:
    """写入前加密敏感字段，其它字段保持原样。"""
    stored = _from_value(value)
    if key in _SECRET_KEYS and value not in (None, ""):
        stored = secret_utils.encrypt_secret(str(value))
    return stored
