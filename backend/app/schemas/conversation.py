from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel


class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    message: str
    use_library: bool = False
    web_search: bool = False


class MessageOut(BaseModel):
    role: str
    content: str


class ConversationOut(BaseModel):
    id: str
    title: Optional[str] = None
    messages: list[dict[str, Any]] = []
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}