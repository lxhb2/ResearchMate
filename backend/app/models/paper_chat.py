from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, ForeignKey

from app.database import Base
from app.models.types import GUID, uuid_str


class PaperChatMessage(Base):
    """论文级 AI 对话消息（长期记忆）。

    与通用 Conversation 分离：每篇论文一条独立对话流，进入阅读器即可
    恢复上次的问答记录；AI 回答时把最近若干条历史作为上下文带入，
    实现跨会话的连续对话能力。
    """

    __tablename__ = "paper_chat_messages"

    id = Column(GUID, primary_key=True, default=uuid_str)
    user_id = Column(GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    paper_id = Column(GUID, ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
