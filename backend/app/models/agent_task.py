from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey

from app.database import Base
from app.models.types import GUID, JSONType, uuid_str


class AgentTask(Base):
    """持久化后台任务：SQLite 队列，支持中断恢复与重试。"""

    __tablename__ = "agent_tasks"

    id = Column(GUID, primary_key=True, default=uuid_str)
    user_id = Column(GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    task_type = Column(String(64), nullable=False, index=True)
    payload = Column(JSONType, default=dict)
    status = Column(String(20), default="pending", nullable=False, index=True)  # pending/running/success/failed
    attempts = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=3, nullable=False)
    error = Column(Text)
    result = Column(JSONType, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
