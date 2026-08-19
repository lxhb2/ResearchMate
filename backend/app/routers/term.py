from fastapi import APIRouter, Depends
import json
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services import llm_service, settings_service
from app.agent.llm_adapter import LLMAdapter

router = APIRouter(prefix="/term", tags=["term"])


def _build_llm(db: Session, user_id) -> LLMAdapter:
    try:
        cfg = settings_service.get_llm_config(db, str(user_id))
        return LLMAdapter.from_config(cfg)
    except Exception:  # noqa: BLE001
        return LLMAdapter.mock()


def _system_prompt(web_search: bool) -> str:
    system = (
        "You are an academic glossary assistant. Explain the given term or phrase clearly and concisely "
        "for a researcher. Provide: a short definition, the field it belongs to, and an example usage if helpful. "
        "Respond in the same language as the term when possible; otherwise use English. "
        "Use Markdown for structure."
    )
    if web_search:
        system += " If you have web browsing tool capabilities, use them to enrich the explanation with the latest sources."
    return system


@router.post("/lookup")
def term_lookup(body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    text = body.get("text", "").strip()
    web_search = body.get("web_search", False)
    if not text:
        return {"explanation": ""}
    user_msg = f"Term to explain: {text}"
    messages = llm_service.system_user(_system_prompt(web_search), user_msg)
    # 统一走 LLMAdapter：连接失败自动降级为离线 mock（不抛 500）
    llm = _build_llm(db, user.id)
    explanation = llm.chat(messages, temperature=0.2, max_tokens=800)
    return {"explanation": explanation.strip()}


@router.post("/lookup/stream")
def term_lookup_stream(body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """流式术语解释：SSE 逐 token 返回。"""
    text = body.get("text", "").strip()
    web_search = body.get("web_search", False)
    if not text:
        return {"explanation": ""}
    user_msg = f"Term to explain: {text}"
    messages = llm_service.system_user(_system_prompt(web_search), user_msg)
    llm = _build_llm(db, user.id)

    def gen():
        # chat_stream 在 LLM 不可达时自动降级为离线 mock 流（含降级提示），不抛异常
        for tok in llm.chat_stream(messages, temperature=0.2, max_tokens=800):
            yield f"data: {json.dumps({'delta': tok})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
