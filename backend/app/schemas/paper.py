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
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class PaperDetail(PaperOut):
    full_text: Optional[str] = None


class PaperList(BaseModel):
    items: list[PaperOut]
    total: int
    page: int
    limit: int
