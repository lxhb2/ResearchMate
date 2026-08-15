from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, ForeignKey, UniqueConstraint

from app.database import Base
from app.models.types import GUID, uuid_str


class AppSetting(Base):
    """单用户应用配置，key-value 存储。

    存放 LLM API 配置（api_key/base_url/model/embedding_model）和
    界面主题配置（theme_color 等）。
    """
    __tablename__ = "app_settings"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_user_setting_key"),)

    id = Column(GUID, primary_key=True, default=uuid_str)
    user_id = Column(GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(64), nullable=False)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)