import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.annotation import Annotation
from app.models.paper import Paper
from app.models.project import Project
from app.schemas.annotation import AnnotationCreate, AnnotationUpdate, AnnotationOut

router = APIRouter(prefix="/annotations", tags=["annotations"])


# ---- Pin 卡片笔记（Q1-1）----
# 语义：带笔记（comment 非空）的标注即「卡片笔记」——content 存原文 snippet，
# comment 存笔记正文，position.rects 存归一化矩形坐标，点击卡片可跳回原文位置。


def _card_order(ann: Annotation) -> float:
    """从 position JSON 读取卡片排序号（拖拽重排用）。"""
    pos = ann.position or {}
    try:
        return float(pos.get("cardOrder", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


@router.get("/pins")
def list_pin_cards(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """返回全部「卡片笔记」：带笔记的标注，并附文献元数据（作者/年份）供引用锚文本。

    按文献 + 卡片排序号排列；同时给出论文标题/作者/年份，前端渲染 (Author, Year, p. X)。
    """
    rows = (
        db.query(Annotation, Paper)
        .join(Paper, Annotation.paper_id == Paper.id)
        .filter(
            Annotation.user_id == user.id,
            Annotation.comment.isnot(None),
            Annotation.comment != "",
        )
        .order_by(Paper.title.asc(), Annotation.created_at.asc())
        .all()
    )
    # 组内按 cardOrder 排序（拖拽重排结果）
    grouped: dict[str, list] = {}
    for ann, paper in rows:
        grouped.setdefault(str(paper.id), []).append(ann)
    ordered: list[Annotation] = []
    for pid, anns in grouped.items():
        anns.sort(key=_card_order)
        ordered.extend(anns)
    return [
        {
            "id": str(a.id),
            "paper_id": str(a.paper_id),
            "paper_title": a.paper.title or "未命名",
            "authors": a.paper.authors or [],
            "year": a.paper.year,
            "type": a.type,
            "snippet": a.content or "",
            "note": a.comment or "",
            "color": (a.position or {}).get("color") if isinstance(a.position, dict) else a.color,
            "page": a.page_number,
            "anchor": _citation_anchor(a.paper, a.page_number),
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "card_order": _card_order(a),
        }
        for a in ordered
    ]


class ReorderRequest(BaseModel):
    items: list[dict]


@router.post("/reorder")
def reorder_cards(body: ReorderRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """拖拽重排：把每张卡片的排序号写进 position.cardOrder（无需新表）。"""
    n = 0
    for i, item in enumerate(body.items or []):
        aid = item.get("id")
        if not aid:
            continue
        ann = db.get(Annotation, aid)
        if not ann or ann.user_id != user.id:
            continue
        pos = dict(ann.position or {})
        pos["cardOrder"] = i
        ann.position = pos
        n += 1
    if n:
        db.commit()
    return {"ok": True, "updated": n}


class SendToWritingRequest(BaseModel):
    project_id: str


@router.post("/{annotation_id}/send-to-writing")
def send_card_to_writing(
    annotation_id: str,
    body: SendToWritingRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """把卡片笔记追加到写作项目末尾，自动带 (Author, Year, p. X) 引用锚文本。"""
    ann = db.get(Annotation, annotation_id)
    if not ann or ann.user_id != user.id:
        raise HTTPException(status_code=404, detail="Annotation not found")
    project = db.get(Project, body.project_id)
    if not project or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Project not found")

    paper = db.get(Paper, ann.paper_id)
    anchor = _citation_anchor(paper, ann.page_number)
    snippet = (ann.content or "").strip()
    note = (ann.comment or "").strip()
    line = f"- {note or snippet}（{snippet}，{anchor}）" if note and snippet else f"- {note or snippet}（{anchor}）"
    existing = project.content or ""
    project.content = (existing + "\n\n" + line).strip() if existing else line
    db.commit()
    return {"ok": True, "anchor": anchor, "content": project.content}


def _citation_anchor(paper: Paper | None, page: int | None) -> str:
    """生成 (Author, Year, p. X) 引用锚文本（中英文作者通用）。"""
    authors = (paper.authors if paper else None) or []
    author = authors[0] if authors else "佚名"
    if len(authors) > 1:
        author += "等" if any("\u4e00" <= c <= "\u9fff" for c in author) else " et al."
    year = paper.year if paper else None
    parts = []
    if author:
        parts.append(author)
    if year:
        parts.append(str(year))
    head = ", ".join(parts)
    if page:
        head += f", p. {page}"
    return f"({head})"


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
        color=body.color,
        comment=body.comment,
        tags=body.tags,
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


@router.patch("/{annotation_id}", response_model=AnnotationOut)
def update_annotation(
    annotation_id: str,
    body: AnnotationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ann = db.get(Annotation, annotation_id)
    if not ann or ann.user_id != user.id:
        raise HTTPException(status_code=404, detail="Annotation not found")
    dirty = False
    for field in ("content", "comment", "color", "tags", "position"):
        new_val = getattr(body, field)
        if new_val is not None:
            setattr(ann, field, new_val)
            dirty = True
    if dirty:
        db.commit()
        db.refresh(ann)
    return ann


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


@router.get("/export")
def export_annotations(
    paper_id: str = Query(None),
    format: str = Query("md"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导出当前用户（或单篇文献）的标注/笔记为 Markdown / JSON / Zotero RDF。"""
    fmt = format if format in ("md", "json", "rdf") else "md"
    from app.services import annotation_export
    content, filename, media_type = annotation_export.export_annotations(
        db,
        user.id,
        paper_id=paper_id or None,
        fmt=fmt,
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
