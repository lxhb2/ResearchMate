from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey

from app.database import Base
from app.models.types import GUID, JSONType, uuid_str


class Project(Base):
    __tablename__ = "projects"

    id = Column(GUID, primary_key=True, default=uuid_str)
    user_id = Column(GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255))
    outline = Column(JSONType)  # { sections: [...] }
    content = Column(Text)   # Markdown full content
    references = Column(JSONType)  # [{paper_id, ...}]
    step = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)