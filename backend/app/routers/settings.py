"""设置路由：获取/更新 LLM API 与主题配置，并支持测试连接。"""
from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAI
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services import settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsOut(BaseModel):
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    embedding_model: str
    embedding_dim: int
    theme_color: str


class SettingsUpdate(BaseModel):
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None
    theme_color: str | None = None


class TestConnectionRequest(BaseModel):
    api_key: str
    base_url: str
    model: str


@router.get("", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cfg = settings_service.get_all(db, str(user.id))
    # 出于安全考虑，API key 做脱敏展示（仅保留首尾）
    key = cfg.get("llm_api_key") or ""
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
    )


@router.put("", response_model=SettingsOut)
def update_settings(
    body: SettingsUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    payload = body.model_dump(exclude_none=True)
    # 接受全掩码的 api_key 时跳过更新（用户未修改）
    if "llm_api_key" in payload:
        k = payload["llm_api_key"] or ""
        if set(k) == {"*"} or k.endswith("***") and len(k) < 40 and "*" in k:
            payload.pop("llm_api_key", None)
    cfg = settings_service.update_many(db, str(user.id), payload)
    masked = ""
    key = cfg.get("llm_api_key") or ""
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
    )


@router.post("/test-connection")
def test_connection(
    body: TestConnectionRequest,
    user: User = Depends(get_current_user),
):
    """用提供的凭据发起一次最小化 chat 请求，验证可用性。"""
    try:
        client = OpenAI(api_key=body.api_key, base_url=body.base_url)
        resp = client.chat.completions.create(
            model=body.model,
            messages=[{"role": "user", "content": "ping，请回复：pong"}],
            max_tokens=16,
        )
        reply = (resp.choices[0].message.content or "").strip()
        return {"ok": True, "reply": reply[:80]}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"连接失败：{e}")
