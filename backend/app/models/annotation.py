from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.types import GUID, JSONType, uuid_str


class Annotation(Base):
    __tablename__ = "annotations"

    id = Column(GUID, primary_key=True, default=uuid_str)
    user_id = Column(GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    paper_id = Column(GUID, ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(20), nullable=False)  # highlight|underline|note|summary
    content = Column(Text)
    page_number = Column(Integer)
    position = Column(JSONType)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    paper = relationship("Paper", back_populates="annotations")