"""用户自定义工作流模板模型（轻量化：SQLite JSON 字段，无需迁移脚本）。

用户通过「自然语言生成」或后续的「白板式拖拽」创建的工作流，保存为
「我的自定义模板」，此后可如同内建固定模板一样被选中并进入对话式执行。
"""
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text

from app.database import Base
from app.models.types import GUID, JSONType, uuid_str


class WorkflowTemplate(Base):
    """一个用户自定义的工作流模板。"""
    __tablename__ = "workflow_templates"

    id = Column(GUID, primary_key=True, default=uuid_str)
    user_id = Column(GUID, index=True, nullable=False)
    name = Column(String(128), nullable=False, default="")
    description = Column(Text, default="")
    workflow_id = Column(String(64), default="", index=True)
    workflow_json = Column(JSONType, default=dict)  # 完整工作流定义（Workflow 可校验）
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)