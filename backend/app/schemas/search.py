from typing import Optional, Any
from uuid import UUID
from pydantic import BaseModel


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    dimension: Optional[str] = None  # filter by dimension


class SearchResultItem(BaseModel):
    chunk_id: UUID
    paper_id: UUID
    paper_title: Optional[str] = None
    dimension: str
    content: str
    page_number: Optional[int] = None
    score: float


class SearchResult(BaseModel):
    query: str
    items: list[SearchResultItem]
