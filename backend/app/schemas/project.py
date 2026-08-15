from typing import Optional, Any
from datetime import datetime
from pydantic import BaseModel


class ProjectCreate(BaseModel):
    title: Optional[str] = None
    outline: Optional[dict[str, Any]] = None
    content: Optional[str] = None


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    outline: Optional[dict[str, Any]] = None
    content: Optional[str] = None
    references: Optional[list[dict[str, Any]]] = None
    step: Optional[int] = None


class ProjectOut(BaseModel):
    id: str
    user_id: str
    title: Optional[str] = None
    outline: Optional[dict[str, Any]] = None
    content: Optional[str] = None
    references: Optional[list[dict[str, Any]]] = None
    step: int
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class GenerateTitleRequest(BaseModel):
    direction: str


class GenerateOutlineRequest(BaseModel):
    topic: str
    notes: Optional[str] = None


class SearchMaterialsRequest(BaseModel):
    section_titles: list[str]
    top_k: int = 5


class GenerateDraftRequest(BaseModel):
    outline: dict[str, Any]
    material_chunk_ids: list[str] = []
    section: Optional[str] = None  # if provided, generate only this section


class GenerateAbstractRequest(BaseModel):
    pass  # uses project content
