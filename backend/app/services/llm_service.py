"""LLM service wrapping an OpenAI-compatible chat completions API。

配置（api_key/base_url/model）从 settings_service 动态读取，因此
用户可在设置页面实时切换 LLM 服务商（支持国内所有兼容 OpenAI 接口的大模型）。
"""
import json
from typing import Optional
from uuid import UUID

from openai import OpenAI
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.services import settings_service


def _client(db: Session, user_id) -> OpenAI:
    cfg = settings_service.get_llm_config(db, str(user_id))
    return OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])


def _model(db: Session, user_id) -> str:
    return settings_service.get_llm_config(db, str(user_id))["model"]


def chat(
    db: Session,
    user_id,
    messages: list[dict],
    temperature: float = 0.3,
    max_tokens: int = 2048,
    json_mode: bool = False,
) -> str:
    """同步 chat completion，返回助手文本。"""
    client = _client(db, user_id)
    model = _model(db, user_id)
    kwargs = dict(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def chat_stream(db: Session, user_id, messages: list[dict], temperature: float = 0.3, max_tokens: int = 2048):
    """流式 chat completion，逐 token 产出文本片段（生成器，用于 SSE）。"""
    client = _client(db, user_id)
    model = _model(db, user_id)
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    for chunk in stream:
        if chunk.choices:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content


def chat_json(db: Session, user_id, messages: list[dict], temperature: float = 0.3) -> dict:
    """chat completion 并把响应解析为 JSON。"""
    text = chat(db, user_id, messages, temperature=temperature, json_mode=True)
    text = text.strip()
    # 兼容代码块包裹的 JSON
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    return json.loads(text)


def system_user(system: str, user: str) -> list[dict]:
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
