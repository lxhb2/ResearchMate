from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.search import SearchRequest, SearchResult
from app.services import search_service

router = APIRouter(prefix="/search", tags=["search"])


class FullTextSearchRequest(BaseModel):
    query: str
    limit: int = 20
    offset: int = 0


@router.post("/semantic", response_model=SearchResult)
def semantic_search(
    body: SearchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items = search_service.semantic_search(
        db, query=body.query, top_k=body.top_k, dimension=body.dimension, user_id=user.id
    )
    return SearchResult(query=body.query, items=items)


@router.post("/fulltext")
def fulltext_search(
    body: FullTextSearchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """FTS5 全文检索：标题/作者/摘要/全文，返回带高亮摘要的论文列表。"""
    return search_service.fulltext_search(
        db,
        body.query,
        top_k=body.limit,
        offset=body.offset,
        user_id=user.id,
    )
