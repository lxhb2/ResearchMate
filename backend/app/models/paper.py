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
    # 文献标签（JSON list[str]，用于文献管理筛选）
    tags = Column(JSONType)
    # full text extracted by PyMuPDF, used for paper-level chat
    full_text = Column(Text)
    # AI 全文总结（生成后缓存，重开界面直接显示，不必重复生成）
    summary = Column(Text)
    # 上次阅读到的页码（长期记忆：重开阅读器自动恢复阅读位置）
    last_page = Column(Integer)
    # status：processing（刚上传/本地解析中）→ ready（可阅读/问答）| error
    status = Column(String(20), default="processing", nullable=False, index=True)
    # AI 语义分析（LLM 六维拆分 + 向量化）进度：pending → done | failed。
    # 与 status 解耦：本地 PyMuPDF 解析完成后即可阅读，AI 分析在后台慢慢跑。
    analysis_status = Column(String(20), default="pending", nullable=False)
    # 结构感知拆分结果：检测到的章节树、维度依据、拆分统计（JSON）
    analysis_meta = Column(JSONType, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    chunks = relationship("PaperChunk", back_populates="paper", cascade="all, delete-orphan")
    annotations = relationship("Annotation", back_populates="paper", cascade="all, delete-orphan")
