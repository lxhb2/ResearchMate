from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey

from app.database import Base
from app.models.types import GUID, JSONType, uuid_str


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(GUID, primary_key=True, default=uuid_str)
    user_id = Column(GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255))
    messages = Column(JSONType, default=list)  # [{role, content}]
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)