import os

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.paper import Paper
from app.models.paper_chunk import PaperChunk
from app.models.annotation import Annotation
from app.schemas.paper import PaperOut, PaperDetail, PaperList
from app.services import paper_service, llm_service, search_service

router = APIRouter(prefix="/papers", tags=["papers"])


@router.post("/upload", response_model=PaperOut, status_code=201)
def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    os.makedirs(settings.PDF_DIR, exist_ok=True)
    # Use a unique filename to avoid collisions
    safe_name = file.filename.replace("/", "_")
    stored_name = f"{os.urandom(6).hex()}_{safe_name}"
    dest = os.path.join(settings.PDF_DIR, stored_name)
    with open(dest, "wb") as f:
        f.write(file.file.read())

    paper = Paper(
        user_id=user.id,
        title=file.filename.rsplit(".", 1)[0],
        source="upload",
        file_path=f"/pdfs/{stored_name}",
        status="processing",
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)

    # Run processing in background (uses a fresh session inside the task)
    background_tasks.add_task(_run_processing, str(paper.id))
    return paper


def _run_processing(paper_id: str):
    """Open a dedicated DB session for the background task."""
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        paper_service.process_paper(paper_id, db)
    finally:
        db.close()


@router.get("", response_model=PaperList)
def list_papers(
    search: str = "",
    status: str = "",
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Paper).filter(Paper.user_id == user.id)
    if search:
        like = f"%{search}%"
        q = q.filter(Paper.title.ilike(like))
    if status:
        q = q.filter(Paper.status == status)
    total = q.count()
    items = q.order_by(Paper.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
    return PaperList(items=items, total=total, page=page, limit=limit)


@router.get("/{paper_id}", response_model=PaperDetail)
def get_paper(paper_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    paper = db.get(Paper, paper_id)
    if not paper or paper.user_id != user.id:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@router.delete("/{paper_id}", status_code=204)
def delete_paper(paper_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    paper = db.get(Paper, paper_id)
    if not paper or paper.user_id != user.id:
        raise HTTPException(status_code=404, detail="Paper not found")
    # delete file on disk
    if paper.file_path:
        fp = os.path.join(settings.PDF_DIR, os.path.basename(paper.file_path))
        if os.path.exists(fp):
            try:
                os.remove(fp)
            except OSError:
                pass
    db.delete(paper)
    db.commit()


@router.get("/{paper_id}/file")
def get_paper_file(paper_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    paper = db.get(Paper, paper_id)
    if not paper or paper.user_id != user.id:
        raise HTTPException(status_code=404, detail="Paper not found")
    if not paper.file_path:
        raise HTTPException(status_code=404, detail="No file attached")
    fp = os.path.join(settings.PDF_DIR, os.path.basename(paper.file_path))
    if not os.path.exists(fp):
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(fp, media_type="application/pdf", filename=os.path.basename(fp))


@router.post("/{paper_id}/chat")
def chat_paper(
    paper_id: str,
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    paper = db.get(Paper, paper_id)
    if not paper or paper.user_id != user.id:
        raise HTTPException(status_code=404, detail="Paper not found")
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    context = paper.full_text or paper.abstract or ""
    if not context.strip():
        raise HTTPException(status_code=400, detail="Paper text is not available yet")
    system = (
        "You are a research assistant. You have the full text of a paper. "
        "Answer the user's question based solely on this paper. "
        "If the answer is not contained in the paper, say so."
    )
    messages = [
        {"role": "system", "content": f"{system}\n\nPaper content:\n{context[:12000]}"},
        {"role": "user", "content": message},
    ]
    answer = llm_service.chat(db, user.id, messages, temperature=0.3, max_tokens=1500)
    return {"answer": answer}


@router.post("/{paper_id}/summary")
def summarize_paper(
    paper_id: str,
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    paper = db.get(Paper, paper_id)
    if not paper or paper.user_id != user.id:
        raise HTTPException(status_code=404, detail="Paper not found")

    summary_type = body.get("type", "full")
    context = paper.full_text or paper.abstract or ""
    if not context.strip():
        raise HTTPException(status_code=400, detail="Paper text is not available yet")

    if summary_type == "chapter":
        chapter = body.get("chapter", "")
        system = (
            "You are a research assistant. Summarize the requested section of the paper concisely. "
            "If the section is not clearly identifiable, summarize the most relevant content."
        )
        user_msg = f"Summarize the section: '{chapter}'\n\nPaper:\n{context[:12000]}"
    else:
        system = (
            "You are a research assistant. Provide a structured summary of the paper with key points, "
            "methods, main results, and conclusions. Use Markdown headings and bullet points."
        )
        user_msg = f"Paper:\n{context[:12000]}"

    messages = llm_service.system_user(system, user_msg)
    summary = llm_service.chat(db, user.id, messages, temperature=0.3, max_tokens=1500)
    return {"summary": summary}


@router.get("/{paper_id}/analysis")
def get_paper_analysis(
    paper_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回一篇论文的完整分析 = AI 拆分的 6 个语义维度 + 用户阅读笔记。

    这是「AI 拆分维度 + 用户笔记合并」的统一出口：把 paper_chunks 中的
    语义维度片段与用户在阅读时留下的批注/笔记（annotation）整合到一份，
    方便用户把 AI 总结与个人思考放在一起，作为这篇论文的完整分析。
    """
    paper = db.get(Paper, paper_id)
    if not paper or paper.user_id != user.id:
        raise HTTPException(status_code=404, detail="Paper not found")

    # 1) AI 拆分的 6 个语义维度（保持 DIMENSIONS 顺序）
    chunks = (
        db.query(PaperChunk)
        .filter(PaperChunk.paper_id == paper.id)
        .order_by(PaperChunk.created_at.asc())
        .all()
    )
    dim_label = search_service.DIMENSION_LABELS
    dimensions = []
    for c in chunks:
        dimensions.append(
            {
                "dimension": c.dimension,
                "label": dim_label.get(c.dimension, c.dimension),
                "content": c.content,
                "page_number": c.page_number,
            }
        )
    # 补齐尚未拆分的维度占位（如处理中/失败）
    present = {d["dimension"] for d in dimensions}
    for d in search_service.DIMENSIONS:
        if d not in present:
            dimensions.append(
                {"dimension": d, "label": dim_label.get(d, d), "content": "", "page_number": None}
            )

    # 2) 用户阅读笔记（note / summary / highlight）
    notes = (
        db.query(Annotation)
        .filter(Annotation.paper_id == paper.id, Annotation.user_id == user.id)
        .order_by(Annotation.created_at.desc())
        .all()
    )
    user_notes = [
        {
            "id": str(n.id),
            "type": n.type,
            "content": n.content,
            "page_number": n.page_number,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notes
    ]

    return {
        "paper_id": str(paper.id),
        "title": paper.title,
        "status": paper.status,
        "dimensions": dimensions,
        "user_notes": user_notes,
    }
