from fastapi import APIRouter, Depends
import json
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.conversation import ConversationOut, ChatRequest
from app.models.conversation import Conversation
from app.services import settings_service

from app.agent.llm_adapter import LLMAdapter
from app.agent.top_agent import TopAgent

router = APIRouter(tags=["chat"])


def _build_llm(db: Session, user_id) -> LLMAdapter:
    """从用户设置构造 LLM 适配器，供顶层 Agent / 专用 Agent 复用。"""
    try:
        cfg = settings_service.get_llm_config(db, str(user_id))
        return LLMAdapter.from_config(cfg)
    except Exception:  # noqa: BLE001
        return LLMAdapter.mock()


def _get_or_create_conv(db: Session, user_id, body: ChatRequest) -> Conversation:
    if body.conversation_id:
        conv = db.get(Conversation, body.conversation_id)
        if not conv or conv.user_id != user_id:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Conversation not found")
        return conv
    conv = Conversation(user_id=user_id, title=body.message[:50], messages=[])
    db.add(conv)
    db.flush()
    return conv


def _maybe_enqueue_summary(db: Session, user_id, messages: list[dict]) -> None:
    """长对话自动压缩为会话摘要，写入长期记忆（后台任务，不阻塞回复）。"""
    if len(messages) < 8:
        return
    from app.services import task_queue
    recent = [
        {"role": m.get("role"), "content": str(m.get("content") or "")[:1200]}
        for m in messages[-12:]
        if m.get("content")
    ]
    if recent:
        task_queue.enqueue(db, user_id, "conversation_summary", {"messages": recent})


@router.post("/chat")
def chat(body: ChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """全局权限 Agent 对话：记忆注入 + 工具调用 + 智能推荐 + 路由。"""
    conv = _get_or_create_conv(db, user.id, body)
    messages = list(conv.messages or [])
    messages.append({"role": "user", "content": body.message})

    # 统一走全局权限 Agent（科研 skill / 专用 Agent / 全局工具循环）
    agent = TopAgent(db, user.id, llm=_build_llm(db, user.id))
    out = agent.handle(
        body.message,
        use_library=body.use_library,
        web_search=body.web_search,
        contexts=body.contexts,
        history=messages[:-1],
    )
    answer = out.get("answer", "")
    route_meta = {
        "intent": out.get("path", "chat"),
        "route_label": out.get("route_label", "智能问答"),
        "artifact_path": out.get("artifact_path"),
        "recommendation": out.get("recommendation"),
        "tool_trace": out.get("tool_trace"),
    }

    messages.append({"role": "assistant", "content": answer})
    conv.messages = messages
    db.commit()
    db.refresh(conv)
    _maybe_enqueue_summary(db, user.id, messages)
    return {
        "answer": answer,
        "conversation_id": conv.id,
        "conversation": ConversationOut.model_validate(conv),
        "route": route_meta,
    }


@router.post("/chat/stream")
def chat_stream(body: ChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """流式问答：全局 Agent 决策后分块流出最终回答（含工具调用结果与记忆）。"""
    conv = _get_or_create_conv(db, user.id, body)
    messages = list(conv.messages or [])
    messages.append({"role": "user", "content": body.message})

    agent = TopAgent(db, user.id, llm=_build_llm(db, user.id))

    def gen():
        full = ""
        try:
            for chunk in agent.stream(
                body.message,
                use_library=body.use_library,
                web_search=body.web_search,
                contexts=body.contexts,
                history=messages[:-1],
            ):
                full += chunk
                yield f"data: {json.dumps({'delta': chunk})}\n\n"
            # 流结束后持久化到数据库
            messages.append({"role": "assistant", "content": full})
            conv.messages = messages
            db.commit()
            _maybe_enqueue_summary(db, user.id, messages)
        except Exception as exc:  # noqa: BLE001
            # 流中异常：把真实错误作为 delta 输出，避免连接中断后前端只显示
            # 笼统的 "An unexpected error occurred"
            err = f"处理失败：{exc}"
            full += f"\n\n⚠️ {err}"
            yield f"data: {json.dumps({'delta': f'\n\n⚠️ {err}'})}\n\n"
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
        yield f"data: {json.dumps({'conversation_id': conv.id})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/chat/events")
def chat_events(body: ChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """实时事件流对话：先落库用户消息，再推送 thinking / tool_start / tool_result / answer。"""
    conv = _get_or_create_conv(db, user.id, body)
    messages = list(conv.messages or [])
    messages.append({"role": "user", "content": body.message})
    conv.messages = messages
    db.commit()

    agent = TopAgent(db, user.id, llm=_build_llm(db, user.id))

    def gen():
        yield f"data: {json.dumps({'conversation_id': conv.id})}\n\n"
        try:
            for ev in agent.event_stream(
                body.message,
                use_library=body.use_library,
                web_search=body.web_search,
                contexts=body.contexts,
                history=messages[:-1],
            ):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                if ev.get("type") == "answer":
                    messages.append({"role": "assistant", "content": ev.get("answer", "")})
                    conv.messages = messages
                    db.commit()
                    _maybe_enqueue_summary(db, user.id, messages)
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
        yield f"data: {json.dumps({'conversation_id': conv.id})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
