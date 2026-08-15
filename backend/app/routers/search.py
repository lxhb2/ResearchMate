from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.search import SearchRequest, SearchResult
from app.services import search_service

router = APIRouter(prefix="/search", tags=["search"])


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
