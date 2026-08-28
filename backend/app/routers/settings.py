"""设置路由：获取/更新 LLM API 与主题配置，并支持测试连接。"""
from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAI
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agent.llm_adapter import reset_breakers
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services import settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


_PLACEHOLDER_KEYS = {"sk-xxx", "sk-placeholder", "sk-sandbox-placeholder"}


def _is_placeholder_key(key: str) -> bool:
    key = (key or "").strip()
    return not key or key in _PLACEHOLDER_KEYS


class SettingsOut(BaseModel):
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    embedding_model: str
    embedding_dim: int
    theme_color: str
    anysearch_enabled: bool
    anysearch_api_key: str
    anysearch_base_url: str
    searxng_url: str
    agentsearch_url: str
    agentsearch_token: str
    agentsearch_mode: str
    academic_sources: list[str]


class SettingsUpdate(BaseModel):
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None
    theme_color: str | None = None
    anysearch_enabled: bool | None = None
    anysearch_api_key: str | None = None
    anysearch_base_url: str | None = None
    searxng_url: str | None = None
    agentsearch_url: str | None = None
    agentsearch_token: str | None = None
    agentsearch_mode: str | None = None
    academic_sources: list[str] | None = None


class TestConnectionRequest(BaseModel):
    api_key: str
    base_url: str
    model: str


class SearchTestRequest(BaseModel):
    provider: str = "auto"  # auto | anysearch | searxng | agentsearch
    anysearch_api_key: str = ""
    anysearch_base_url: str = ""
    searxng_url: str = ""
    agentsearch_url: str = ""
    agentsearch_token: str = ""
    agentsearch_mode: str = ""


class ModelPresetOut(BaseModel):
    name: str
    base_url: str
    models: list[str]
    embedding_model: str
    help: str


@router.get("/model-presets", response_model=list[ModelPresetOut])
def get_model_presets(user: User = Depends(get_current_user)):
    """返回推荐的 LLM 预设列表，供前端一键填充 base_url / model / embedding_model。"""
    return settings_service.MODEL_PRESETS


@router.get("", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cfg = settings_service.get_all(db, str(user.id))
    return _masked_out(cfg)


@router.put("", response_model=SettingsOut)
def update_settings(
    body: SettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    payload = body.model_dump(exclude_none=True)
    # 出于安全考虑，GET 返回的是脱敏 Key（含 *）。保存时：
    # 任何「包含 *」的 Key 都视为「用户未修改」，跳过更新，
    # 避免把脱敏串误当新 Key 存库导致原 Key 被覆盖损坏。
    if "llm_api_key" in payload:
        k = payload["llm_api_key"] or ""
        if "*" in k or not k.strip():
            payload.pop("llm_api_key", None)
    if "anysearch_api_key" in payload:
        k = payload["anysearch_api_key"] or ""
        if "*" in k or not k.strip():
            payload.pop("anysearch_api_key", None)
    if "agentsearch_token" in payload:
        k = payload["agentsearch_token"] or ""
        if "*" in k or not k.strip():
            payload.pop("agentsearch_token", None)
    cfg = settings_service.update_many(db, str(user.id), payload)
    # 清空 LLM 熔断状态：让新配置立即生效。
    # 否则旧的熔断记录会让「保存后立刻重试」的请求继续降级，
    # 用户误以为新配置无效（实际只是熔断窗口未过期）。
    reset_breakers()
    return _masked_out(cfg)


def _masked_out(cfg: dict) -> SettingsOut:
    """构造脱敏输出：Key 只保留首尾，避免明文回传前端。"""
    key = cfg.get("llm_api_key") or ""
    if _is_placeholder_key(key):
        key = ""
    masked = ""
    if len(key) > 8:
        masked = key[:4] + "*" * (len(key) - 8) + key[-4:]
    elif key:
        masked = "*" * len(key)
    return SettingsOut(
        llm_api_key=masked,
        llm_base_url=cfg.get("llm_base_url", ""),
        llm_model=cfg.get("llm_model", ""),
        embedding_model=cfg.get("embedding_model", ""),
        embedding_dim=int(cfg.get("embedding_dim") or 1536),
        theme_color=cfg.get("theme_color", "#4f46e5"),
        anysearch_enabled=bool(cfg.get("anysearch_enabled", True)),
        anysearch_api_key=_mask_key(cfg.get("anysearch_api_key") or ""),
        anysearch_base_url=cfg.get("anysearch_base_url", "https://api.anysearch.com"),
        searxng_url=cfg.get("searxng_url", ""),
        agentsearch_url=cfg.get("agentsearch_url", ""),
        agentsearch_token=_mask_key(cfg.get("agentsearch_token") or ""),
        agentsearch_mode=cfg.get("agentsearch_mode", "general"),
        academic_sources=settings_service.normalize_academic_sources(cfg.get("academic_sources")),
    )


def _mask_key(key: str) -> str:
    key = (key or "").strip()
    if not key:
        return ""
    if len(key) > 8:
        return key[:4] + "*" * (len(key) - 8) + key[-4:]
    return "*" * len(key)


@router.post("/search/test")
def test_search(
    body: SearchTestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """测试联网搜索提供方（AnySearch / SearXNG / AgentSearch）。"""
    from app.services import web_search_providers

    cfg = settings_service.get_search_config(db, str(user.id))
    if body.anysearch_api_key:
        cfg["api_key"] = body.anysearch_api_key
    if body.anysearch_base_url:
        cfg["base_url"] = body.anysearch_base_url
    if body.searxng_url:
        cfg["searxng_url"] = body.searxng_url
    if body.agentsearch_url:
        cfg["agentsearch_url"] = body.agentsearch_url
    if body.agentsearch_token:
        cfg["agentsearch_token"] = body.agentsearch_token
    if body.agentsearch_mode:
        cfg["agentsearch_mode"] = body.agentsearch_mode

    provider = (body.provider or "auto").strip().lower()
    if provider == "anysearch":
        cfg["enabled"] = True

    errors: list[str] = []
    if provider in ("auto", "searxng") and web_search_providers.searxng_configured(cfg):
        try:
            result = web_search_providers.searxng_search("ResearchMate", 1, timeout=20, config=cfg)
            return {"ok": True, "engine": "searxng", "count": result.get("count", 0)}
        except Exception as e:  # noqa: BLE001
            errors.append(f"SearXNG：{e}")

    if provider in ("auto", "agentsearch") and web_search_providers.agentsearch_configured(cfg):
        try:
            result = web_search_providers.agentsearch_search(
                "ResearchMate", 1, timeout=20, config=cfg,
                mode=cfg.get("agentsearch_mode") or "general",
            )
            return {"ok": True, "engine": "agentsearch", "count": result.get("count", 0)}
        except Exception as e:  # noqa: BLE001
            errors.append(f"AgentSearch：{e}")

    if provider in ("auto", "anysearch") and web_search_providers.anysearch_enabled(cfg):
        try:
            result = web_search_providers.anysearch_search(
                "ResearchMate", 1, timeout=20, config=cfg
            )
            return {"ok": True, "engine": "anysearch", "count": result.get("count", 0)}
        except Exception as e:  # noqa: BLE001
            errors.append(f"AnySearch：{e}")

    if provider == "searxng" and not web_search_providers.searxng_configured(cfg):
        errors.append("未配置 SearXNG URL")
    if provider == "anysearch" and not web_search_providers.anysearch_enabled(cfg):
        errors.append("AnySearch 未启用")
    if provider == "agentsearch" and not web_search_providers.agentsearch_configured(cfg):
        errors.append("未配置 AgentSearch URL")
    raise HTTPException(status_code=400, detail="；".join(errors) or "没有可测试的搜索提供方")


@router.post("/test-connection")
def test_connection(
    body: TestConnectionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """用提供的凭据发起一次最小化 chat 请求，验证可用性。

    api_key 留空时自动使用已保存的 Key（出于安全前端不回显 Key，
    用户改完地址/模型后无需重新输入 Key 即可测试）。
    """
    api_key = (body.api_key or "").strip()
    if not api_key:
        api_key = (settings_service.get_llm_config(db, str(user.id)).get("api_key") or "").strip()
    if api_key.lower().startswith("bearer "):
        api_key = api_key[7:].strip()
    if _is_placeholder_key(api_key):
        raise HTTPException(
            status_code=400,
            detail="当前使用的是默认占位 API Key（sk-xxx），请先填写真实 API Key 并保存后再测试连接",
        )
    try:
        client = OpenAI(api_key=api_key, base_url=body.base_url, timeout=20)
        resp = client.chat.completions.create(
            model=body.model,
            messages=[{"role": "user", "content": "ping，请回复：pong"}],
            max_tokens=16,
        )
        reply = (resp.choices[0].message.content or "").strip()
        return {"ok": True, "reply": reply[:80]}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"连接失败：{e}")
