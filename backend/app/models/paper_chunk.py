from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship

from app.config import settings
from app.database import Base
from app.models.types import GUID, VectorJson, uuid_str


class PaperChunk(Base):
    __tablename__ = "paper_chunks"

    id = Column(GUID, primary_key=True, default=uuid_str)
    paper_id = Column(GUID, ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    dimension = Column(String(30), nullable=False, index=True)  # background|method|result|conclusion
    content = Column(Text, nullable=False)
    # 轻量化：向量存为 JSON 文本，检索时在内存中计算余弦（不再依赖 pgvector）
    embedding = Column(VectorJson, nullable=True)
    page_number = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    paper = relationship("Paper", back_populates="chunks")