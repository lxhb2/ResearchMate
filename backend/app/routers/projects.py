import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.project import Project
from app.schemas.project import (
    ProjectCreate, ProjectOut, ProjectUpdate,
    GenerateTitleRequest, GenerateOutlineRequest, SearchMaterialsRequest,
    GenerateDraftRequest, GenerateAbstractRequest,
)
from app.services import writing_service, export_service, llm_service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = Project(
        user_id=user.id,
        title=body.title,
        outline=body.outline,
        content=body.content or "",
        step=1,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return (
        db.query(Project)
        .filter(Project.user_id == user.id)
        .order_by(Project.updated_at.desc())
        .all()
    )


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = db.get(Project, project_id)
    if not project or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.put("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    body: ProjectUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if not project or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Project not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(project, k, v)
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = db.get(Project, project_id)
    if not project or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Project not found")
    db.delete(project)
    db.commit()


@router.post("/{project_id}/generate-title")
def generate_title(
    project_id: str,
    body: GenerateTitleRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_project(db, project_id, user.id)
    titles = writing_service.generate_titles(db, user.id, body.direction)
    return {"titles": titles}


@router.post("/{project_id}/generate-outline")
def generate_outline(
    project_id: str,
    body: GenerateOutlineRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = _require_project(db, project_id, user.id)
    outline = writing_service.generate_outline(db, user.id, body.topic, body.notes)
    project.outline = outline
    if not project.title:
        project.title = body.topic
    db.commit()
    return {"outline": outline}


@router.post("/{project_id}/search-materials")
def search_materials(
    project_id: str,
    body: SearchMaterialsRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_project(db, project_id, user.id)
    materials = writing_service.search_materials(db, user.id, body.section_titles, body.top_k)
    return {"materials": materials}


@router.post("/{project_id}/generate-draft")
def generate_draft(
    project_id: str,
    body: GenerateDraftRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = _require_project(db, project_id, user.id)
    draft = writing_service.generate_draft(
        db, user.id, body.outline, body.material_chunk_ids, body.section
    )
    if body.section:
        # Append/merge a single section into existing content
        existing = project.content or ""
        project.content = (existing + "\n\n" + draft).strip() if existing else draft
    else:
        project.content = draft
    db.commit()
    return {"content": project.content}


@router.post("/{project_id}/generate-abstract")
def generate_abstract(
    project_id: str,
    body: GenerateAbstractRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = _require_project(db, project_id, user.id)
    content = project.content or ""
    if not content.strip():
        raise HTTPException(status_code=400, detail="No draft content to summarize")
    result = writing_service.generate_abstract(db, user.id, content)
    return result


@router.post("/{project_id}/export-word")
def export_word(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = _require_project(db, project_id, user.id)
    content = project.content or ""
    title = project.title or "Untitled"
    docx_bytes = export_service.md_to_docx_bytes(content, title)
    safe_title = "".join(c for c in title if c.isalnum() or c in " -_") or "paper"
    filename = f"{safe_title}.docx"
    return StreamingResponse(
        iter([docx_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _require_project(db: Session, project_id: str, user_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project or project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
