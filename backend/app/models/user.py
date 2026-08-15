from datetime import datetime

from sqlalchemy import Column, String, DateTime

from app.database import Base
from app.models.types import GUID, uuid_str


class User(Base):
    __tablename__ = "users"

    id = Column(GUID, primary_key=True, default=uuid_str)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)