from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel


class AnnotationCreate(BaseModel):
    paper_id: str
    type: str  # highlight|underline|note|summary
    content: Optional[str] = None
    page_number: Optional[int] = None
    position: Optional[dict[str, Any]] = None


class AnnotationOut(AnnotationCreate):
    id: str
    user_id: str
    created_at: datetime
    model_config = {"from_attributes": True}