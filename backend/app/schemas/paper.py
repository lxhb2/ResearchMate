from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class PaperBase(BaseModel):
    title: Optional[str] = None
    authors: Optional[list[str]] = None
    year: Optional[int] = None
    doi: Optional[str] = None
    abstract: Optional[str] = None
    status: str = "processing"


class PaperOut(PaperBase):
    id: str
    user_id: str
    source: str
    file_path: Optional[str] = None
    tags: Optional[list[str]] = None
    # AI 语义分析进度（pending / done / failed），与 status 解耦
    analysis_status: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class PaperUpdate(BaseModel):
    title: Optional[str] = None
    authors: Optional[list[str]] = None
    year: Optional[int] = None
    doi: Optional[str] = None
    abstract: Optional[str] = None
    tags: Optional[list[str]] = None


class PaperDetail(PaperOut):
    full_text: Optional[str] = None
    # AI 全文总结缓存（长期记忆：重开界面直接恢复）
    summary: Optional[str] = None
    # 上次阅读页码（长期记忆：重开阅读器自动恢复位置）
    last_page: Optional[int] = None


class PaperList(BaseModel):
    items: list[PaperOut]
    total: int
    page: int
    limit: int
