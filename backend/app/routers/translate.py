from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.services import llm_service

router = APIRouter(tags=["translate"])


@router.post("/translate")
def translate(body: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    text = body.get("text", "").strip()
    target_lang = body.get("target_lang", "zh")
    if not text:
        return {"translation": ""}
    system = (
        "You are a professional academic translator. Translate the user's text into the target language. "
        "Preserve technical terms accurately. Return ONLY the translation, no explanations."
    )
    user_msg = f"Target language: {target_lang}\n\nText to translate:\n{text}"
    messages = llm_service.system_user(system, user_msg)
    translation = llm_service.chat(db, user.id, messages, temperature=0.2, max_tokens=1200)
    return {"translation": translation.strip()}
