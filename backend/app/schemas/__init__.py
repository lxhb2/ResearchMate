from app.schemas.user import UserCreate, UserOut, Token
from app.schemas.paper import PaperOut, PaperDetail, PaperList
from app.schemas.annotation import AnnotationCreate, AnnotationOut
from app.schemas.conversation import ConversationOut, ChatRequest
from app.schemas.project import (
    ProjectCreate, ProjectOut, ProjectUpdate,
    GenerateTitleRequest, GenerateOutlineRequest, SearchMaterialsRequest,
    GenerateDraftRequest, GenerateAbstractRequest,
)
from app.schemas.search import SearchRequest, SearchResult

__all__ = [
    "UserCreate", "UserOut", "Token",
    "PaperOut", "PaperDetail", "PaperList",
    "AnnotationCreate", "AnnotationOut",
    "ConversationOut", "ChatRequest",
    "ProjectCreate", "ProjectOut", "ProjectUpdate",
    "GenerateTitleRequest", "GenerateOutlineRequest", "SearchMaterialsRequest",
    "GenerateDraftRequest", "GenerateAbstractRequest",
    "SearchRequest", "SearchResult",
]
