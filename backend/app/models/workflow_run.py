"""工作流运行记录模型（轻量化：SQLite JSON 字段，无需额外迁移脚本）。"""
from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey

from app.database import Base
from app.models.types import GUID, JSONType, uuid_str


class WorkflowRun(Base):
    """一次工作流执行的持久化记录，供 GET /workflow/{run_id} 查询状态。"""
    __tablename__ = "workflow_runs"

    id = Column(GUID, primary_key=True, default=uuid_str)
    user_id = Column(GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_id = Column(String(64), default="", index=True)
    status = Column(String(20), default="running", nullable=False, index=True)  # running/success/failed/awaiting_confirm
    workflow_json = Column(JSONType, default=dict)   # 提交的工作流定义
    logs = Column(JSONType, default=list)            # 节点执行日志
    results = Column(JSONType, default=dict)         # 中间结果
    final_output = Column(JSONType, default=None)    # 最终输出
    state_json = Column(JSONType, default=dict)      # 暂停时的全局状态（供恢复/迭代）
    current_node = Column(String(64), default=None)  # 暂停时所在节点（供恢复）
    error = Column(Text, default=None)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)