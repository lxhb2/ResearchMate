from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services import llm_service

router = APIRouter(prefix="/term", tags=["term"])


@router.post("/lookup")
def term_lookup(body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    text = body.get("text", "").strip()
    web_search = body.get("web_search", False)
    if not text:
        return {"explanation": ""}
    system = (
        "You are an academic glossary assistant. Explain the given term or phrase clearly and concisely "
        "for a researcher. Provide: a short definition, the field it belongs to, and an example usage if helpful. "
        "Respond in the same language as the term when possible; otherwise use English. "
        "Use Markdown for structure."
    )
    if web_search:
        system += " If you have web browsing tool capabilities, use them to enrich the explanation with the latest sources."
    user_msg = f"Term to explain: {text}"
    messages = llm_service.system_user(system, user_msg)
    explanation = llm_service.chat(db, user.id, messages, temperature=0.2, max_tokens=800)
    return {"explanation": explanation.strip()}
