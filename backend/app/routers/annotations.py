from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.annotation import Annotation
from app.schemas.annotation import AnnotationCreate, AnnotationOut

router = APIRouter(prefix="/annotations", tags=["annotations"])


@router.post("", response_model=AnnotationOut, status_code=201)
def create_annotation(
    body: AnnotationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ann = Annotation(
        user_id=user.id,
        paper_id=body.paper_id,
        type=body.type,
        content=body.content,
        page_number=body.page_number,
        position=body.position,
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)
    return ann


@router.get("", response_model=list[AnnotationOut])
def list_annotations(
    paper_id: str = Query(None),
    type: str = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Annotation).filter(Annotation.user_id == user.id)
    if paper_id:
        q = q.filter(Annotation.paper_id == paper_id)
    if type:
        q = q.filter(Annotation.type == type)
    return q.order_by(Annotation.created_at.desc()).all()


@router.delete("/{annotation_id}", status_code=204)
def delete_annotation(
    annotation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ann = db.get(Annotation, annotation_id)
    if not ann or ann.user_id != user.id:
        raise HTTPException(status_code=404, detail="Annotation not found")
    db.delete(ann)
    db.commit()
