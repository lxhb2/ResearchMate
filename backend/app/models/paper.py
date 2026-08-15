from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.types import GUID, JSONType, uuid_str


class Paper(Base):
    __tablename__ = "papers"

    id = Column(GUID, primary_key=True, default=uuid_str)
    user_id = Column(GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(Text)
    authors = Column(JSONType)  # list[str]（跨库：SQLite 存为 JSON 文本）
    year = Column(Integer)
    doi = Column(String(255), unique=True, index=True)
    abstract = Column(Text)
    source = Column(String(50), default="upload")
    file_path = Column(Text)
    # full text extracted by PyMuPDF, used for paper-level chat
    full_text = Column(Text)
    status = Column(String(20), default="processing", nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    chunks = relationship("PaperChunk", back_populates="paper", cascade="all, delete-orphan")
    annotations = relationship("Annotation", back_populates="paper", cascade="all, delete-orphan")