from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.conversation import ConversationOut, ChatRequest
from app.models.conversation import Conversation
from app.services import search_service, settings_service

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


@router.post("/chat")
def chat(body: ChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # Load or create conversation
    conv = None
    if body.conversation_id:
        conv = db.get(Conversation, body.conversation_id)
        if not conv or conv.user_id != user.id:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conv = Conversation(
            user_id=user.id,
            title=body.message[:50],
            messages=[],
        )
        db.add(conv)
        db.flush()

    messages = list(conv.messages or [])
    messages.append({"role": "user", "content": body.message})

    # ---- 顶层 Agent 意图路由（科研 skill / 专用 Agent / 兜底走原对话）----
    route = None
    route_meta = {}
    if not body.use_library:  # 仅当未强制走检索增强时，先尝试顶层路由
        try:
            agent = TopAgent(db, user.id, llm=_build_llm(db, user.id))
            route = agent.execute(body.message)
        except Exception:  # noqa: BLE001
            route = None

    if route and route.get("path") not in ("chat", None):
        answer = route.get("answer", "")
        route_meta = {
            "intent": route.get("path"),
            "route_label": route.get("route_label", ""),
            "artifact_path": route.get("artifact_path"),
        }
    else:
        # ---- 原对话链路（检索增强 + LLM）----
        system_parts = ["You are a helpful research assistant."]
        context_text = ""

        if body.use_library:
            hits = search_service.semantic_search(db, query=body.message, top_k=5, user_id=user.id)
            if hits:
                ctx = "\n\n".join(
                    f"[{h['dimension']}] (from: {h['paper_title']}) {h['content']}" for h in hits
                )
                system_parts.append(
                    "The following are relevant excerpts retrieved from the user's personal library. "
                    "Use them to ground your answer when relevant, and cite by paper title."
                )
                context_text = ctx

        if body.web_search:
            system_parts.append(
                "If you have web browsing tool capabilities, use them to find up-to-date information. "
                "Otherwise, rely on your own knowledge."
            )

        system = "\n".join(system_parts)
        if context_text:
            system += f"\n\nLibrary context:\n{context_text}"

        llm_messages = [{"role": "system", "content": system}] + [
            m for m in messages if m.get("role") in ("user", "assistant")
        ]

        # 统一走 LLMAdapter：有 key 时用 litellm，无 key 时自动降级为 mock，避免 500
        llm = _build_llm(db, user.id)
        try:
            answer = llm.chat(llm_messages, temperature=0.4, max_tokens=1500)
        except Exception:  # noqa: BLE001
            answer = LLMAdapter.mock().chat(llm_messages, temperature=0.4, max_tokens=1500)
        route_meta = {"intent": "chat", "route_label": "智能问答"}

    messages.append({"role": "assistant", "content": answer})
    conv.messages = messages
    db.commit()
    db.refresh(conv)
    return {
        "answer": answer,
        "conversation_id": conv.id,
        "conversation": ConversationOut.model_validate(conv),
        "route": route_meta,
    }
