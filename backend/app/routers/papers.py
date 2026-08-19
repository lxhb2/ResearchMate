import os
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, wait
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.paper import Paper
from app.models.paper_chunk import PaperChunk
from app.models.paper_chat import PaperChatMessage
from app.models.annotation import Annotation
from app.schemas.paper import PaperOut, PaperDetail, PaperList, PaperUpdate
from app.services import paper_service, llm_service, search_service, settings_service, import_service
from app.agent.llm_adapter import LLMAdapter

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
        # 流式写盘：大 PDF 不必一次性读入内存
        while chunk := file.file.read(1024 * 1024):
            f.write(chunk)

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
    tag: str = "",
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
    pages = q.order_by(Paper.created_at.desc()).all()
    if tag:
        # JSON 在 SQLite 中按 ASCII 转义存储，LIKE 对中文不可靠。
        # 个人文献库规模小，直接在 Python 里按标签过滤更稳妥。
        pages = [p for p in pages if tag in (p.tags or [])]
    total = len(pages)
    items = pages[(page - 1) * limit : page * limit]
    return PaperList(items=items, total=total, page=page, limit=limit)


@router.get("/tags")
def list_paper_tags(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回当前用户所有文献用到的标签（去重、按使用次数排序）。"""
    papers = db.query(Paper).filter(Paper.user_id == user.id).all()
    counter: dict[str, int] = {}
    for p in papers:
        for t in p.tags or []:
            counter[t] = counter.get(t, 0) + 1
    return {
        "tags": [{"name": name, "count": cnt} for name, cnt in sorted(counter.items(), key=lambda x: (-x[1], x[0]))]
    }


@router.get("/{paper_id}", response_model=PaperDetail)
def get_paper(paper_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    paper = db.get(Paper, paper_id)
    if not paper or paper.user_id != user.id:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@router.patch("/{paper_id}", response_model=PaperOut)
def update_paper(
    paper_id: str,
    body: PaperUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    paper = db.get(Paper, paper_id)
    if not paper or paper.user_id != user.id:
        raise HTTPException(status_code=404, detail="Paper not found")
    dirty = False
    for field in ("title", "authors", "year", "doi", "abstract", "tags"):
        new_val = getattr(body, field)
        if new_val is not None:
            setattr(paper, field, new_val)
            dirty = True
    if dirty:
        db.commit()
        db.refresh(paper)
    return paper


def _clean_doi(paper: Paper) -> str:
    """从 DOI 或标题中尽可能提取一个干净的 DOI 字符串用于引文。"""
    if paper.doi:
        return paper.doi.strip()
    return ""


class PaperExportRequest(BaseModel):
    ids: list[str]
    format: str = "bibtex"


@router.post("/export")
def export_papers(
    body: PaperExportRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """批量导出选中的文献为 BibTeX / RIS 文本（Zotero / LaTeX 可直接导入）。"""
    fmt = body.format if body.format in ("bibtex", "ris") else "bibtex"
    papers = (
        db.query(Paper)
        .filter(Paper.user_id == user.id, Paper.id.in_(body.ids))
        .order_by(Paper.created_at.desc())
        .all()
    )
    if not papers:
        raise HTTPException(status_code=400, detail="未选中任何文献")
    if fmt == "ris":
        lines = [import_service.paper_to_ris(p, i) for i, p in enumerate(papers)]
        filename = "researchmate_export.ris"
    else:
        lines = [import_service.paper_to_bibtex(p, i) for i, p in enumerate(papers)]
        filename = "researchmate_export.bib"
    return {"content": "\n\n".join(lines), "filename": filename, "format": fmt, "count": len(papers)}


@router.get("/{paper_id}/citation")
def export_citation(
    paper_id: str,
    format: str = "biblatex",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导出引文：支持 biblatex / bibtex / gb7714 三种格式。"""
    paper = db.get(Paper, paper_id)
    if not paper or paper.user_id != user.id:
        raise HTTPException(status_code=404, detail="Paper not found")

    title = paper.title or "Untitled"
    authors = paper.authors or []
    year = paper.year or ""
    doi = _clean_doi(paper)
    # 生成一个稳定的 citation key
    key = "".join(c for c in title.split() if c.isalnum())[:6] or "paper"
    if authors:
        key = "".join(c for c in authors[0].split()[0] if c.isalnum()) + str(year or "")
    key = key or "paper"

    if format in ("bibtex", "biblatex"):
        author_str = " and ".join(authors) if authors else "Anonymous"
        lines = [
            f"@article{{{key},",
            f"  title = {{{title}}},",
            f"  author = {{{author_str}}},",
        ]
        if year:
            lines.append(f"  year = {{{year}}},")
        if doi:
            lines.append(f"  doi = {{{doi}}},")
        lines.append("}")
        body = "\n".join(lines)
        ext = "bib"
    else:  # gb7714 中文国标格式
        authors_cn = "，".join(authors) if authors else "佚名"
        body = (
            f"{authors_cn}．{title}．"
            + (f"{year}．" if year else "")
            + (f"DOI: {doi}．" if doi else "")
        )
        ext = "txt"

    return {"citation": body, "format": format, "filename": f"{key}.{ext}"}


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
    # 持久化用户消息并带历史上下文（长期记忆）
    history = _chat_history(db, user.id, paper.id)
    _save_chat_message(db, user.id, paper.id, "user", message)
    system = (
        "You are a research assistant. You have the full text of a paper. "
        "Answer the user's question based solely on this paper. "
        "If the answer is not contained in the paper, say so."
    )
    messages = [
        {"role": "system", "content": f"{system}\n\nPaper content:\n{context[:12000]}"},
        *history,
        {"role": "user", "content": message},
    ]
    # 统一走 LLMAdapter：连接失败自动降级为离线 mock 回答（不抛 500）
    llm = LLMAdapter.from_config(settings_service.get_llm_config(db, str(user.id)))
    answer = llm.chat(messages, temperature=0.3, max_tokens=1500)
    _save_chat_message(db, user.id, paper.id, "assistant", answer)
    return {"answer": answer}


def _chat_history(db: Session, user_id: str, paper_id: str, limit: int = 20) -> list[dict]:
    """取该论文最近若干条对话作为上下文（跨会话长期记忆）。"""
    rows = (
        db.query(PaperChatMessage)
        .filter(PaperChatMessage.paper_id == paper_id, PaperChatMessage.user_id == user_id)
        .order_by(PaperChatMessage.created_at.desc(), PaperChatMessage.id.desc())
        .limit(limit)
        .all()
    )
    return [{"role": r.role, "content": r.content} for r in reversed(rows)]


def _save_chat_message(db: Session, user_id: str, paper_id: str, role: str, content: str) -> None:
    db.add(PaperChatMessage(user_id=user_id, paper_id=paper_id, role=role, content=content))
    db.commit()


@router.get("/{paper_id}/chat/messages")
def list_chat_messages(
    paper_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """恢复该论文的历史对话（进入阅读器时调用）。"""
    paper = db.get(Paper, paper_id)
    if not paper or paper.user_id != user.id:
        raise HTTPException(status_code=404, detail="Paper not found")
    rows = (
        db.query(PaperChatMessage)
        .filter(PaperChatMessage.paper_id == paper.id, PaperChatMessage.user_id == user.id)
        .order_by(PaperChatMessage.created_at.asc(), PaperChatMessage.id.asc())
        .all()
    )
    return {
        "messages": [
            {
                "id": str(r.id),
                "role": r.role,
                "content": r.content,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.post("/{paper_id}/chat/messages")
def append_chat_message(
    paper_id: str,
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """手动追加一条对话消息（用于「划词解释」等非 chat 通道产生的问答入档）。"""
    paper = db.get(Paper, paper_id)
    if not paper or paper.user_id != user.id:
        raise HTTPException(status_code=404, detail="Paper not found")
    role = body.get("role", "")
    content = (body.get("content") or "").strip()
    if role not in ("user", "assistant") or not content:
        raise HTTPException(status_code=400, detail="role must be user/assistant and content required")
    db.add(PaperChatMessage(user_id=user.id, paper_id=paper.id, role=role, content=content))
    db.commit()
    return {"ok": True}


@router.delete("/{paper_id}/chat/messages")
def clear_chat_messages(
    paper_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """清空该论文的全部对话记录。"""
    paper = db.get(Paper, paper_id)
    if not paper or paper.user_id != user.id:
        raise HTTPException(status_code=404, detail="Paper not found")
    db.query(PaperChatMessage).filter(
        PaperChatMessage.paper_id == paper.id, PaperChatMessage.user_id == user.id
    ).delete(synchronize_session=False)
    db.commit()
    return {"ok": True}


def _chat_sources(db: Session, user_id, paper_id: str, message: str, top_k: int = 4) -> list[dict]:
    """检索「这篇论文」内与问题最相关的片段（带页码），供 AI 引用溯源。

    复用 6 维语义检索：有 Embedding 走向量余弦，离线自动降级为关键词。
    只保留当前论文的片段，避免答案引用到别的文献。
    """
    try:
        results = search_service.semantic_search(db, message, top_k=top_k * 2, user_id=user_id)
    except Exception:  # noqa: BLE001
        return []
    return [r for r in results if r["paper_id"] == str(paper_id)][:top_k]


@router.post("/{paper_id}/chat/stream")
def chat_paper_stream(
    paper_id: str,
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """基于单篇论文的流式问答（SSE 逐 token 返回）。

    引用溯源：先检索论文内最相关片段（带页码）注入提示词，要求模型以 [pN] 标注出处；
    流结束后追加一个 citations 元事件（page + snippet），前端点击 [pN] 可跳 PDF 页码高亮。
    长期记忆：先落库用户消息，回答时把最近 20 条历史一并送入 LLM，
    流式结束后把完整回答落库——退出/重开界面后对话完整可恢复。
    """
    paper = db.get(Paper, paper_id)
    if not paper or paper.user_id != user.id:
        raise HTTPException(status_code=404, detail="Paper not found")
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    context = paper.full_text or paper.abstract or ""
    if not context.strip():
        raise HTTPException(status_code=400, detail="Paper text is not available yet")
    history = _chat_history(db, user.id, paper.id)
    _save_chat_message(db, user.id, paper.id, "user", message)
    # 引用溯源：检索论文内最相关片段
    sources = _chat_sources(db, user.id, str(paper.id), message)
    excerpts = "\n".join(
        f"[Page {s.get('page_number') or '?'}]\n{s['content']}" for s in sources
    )
    system = (
        "You are a research assistant. You have the full text of a paper. "
        "Answer the user's question based solely on this paper. "
        "If the answer is not contained in the paper, say so."
    )
    if sources:
        system += (
            " When you base an answer on a specific part of the paper, "
            "append the page marker [pN] (N = the page number shown in the excerpts) "
            "at the end of the relevant sentence so the reader can verify the source."
        )
    if excerpts.strip():
        system += f"\n\nRelevant excerpts from this paper:\n{excerpts}"
    messages = [
        {"role": "system", "content": f"{system}\n\nPaper content:\n{context[:12000]}"},
        *history,
        {"role": "user", "content": message},
    ]
    llm = LLMAdapter.from_config(settings_service.get_llm_config(db, str(user.id)))
    citations = [
        {"page": s.get("page_number"), "snippet": (s.get("content") or "")[:160]}
        for s in sources
        if s.get("page_number")
    ]

    def gen():
        answer_parts: list[str] = []
        # chat_stream 在 LLM 不可达时自动降级为离线 mock 流（含降级提示），不抛异常
        try:
            for tok in llm.chat_stream(messages, temperature=0.3, max_tokens=1500):
                answer_parts.append(tok)
                yield f"data: {json.dumps({'delta': tok})}\n\n"
        finally:
            # 完整回答落库（长期记忆：重开界面可恢复完整对话）
            if answer_parts:
                try:
                    _save_chat_message(db, user.id, paper.id, "assistant", "".join(answer_parts))
                except Exception:  # noqa: BLE001
                    pass
            # 引用溯源元事件：前端据此展示「引用来源」并可点击跳转页码
            if citations:
                yield f"data: {json.dumps({'citations': citations})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.put("/{paper_id}/progress")
def save_reading_progress(
    paper_id: str,
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """保存阅读进度（当前页码），重开阅读器时自动恢复。"""
    paper = db.get(Paper, paper_id)
    if not paper or paper.user_id != user.id:
        raise HTTPException(status_code=404, detail="Paper not found")
    try:
        page = int(body.get("page", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="page must be an integer")
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be >= 1")
    paper.last_page = page
    db.commit()
    return {"ok": True, "last_page": paper.last_page}


@router.post("/{paper_id}/summary")
def summarize_paper(
    paper_id: str,
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """生成全文/章节总结，并缓存到 paper.summary（长期记忆）。

    - type=full 且已有缓存：直接返回缓存，不重复调用 LLM；
      前端传 refresh=true 可强制重新生成。
    - 章节总结不缓存（随章节变化）。
    """
    paper = db.get(Paper, paper_id)
    if not paper or paper.user_id != user.id:
        raise HTTPException(status_code=404, detail="Paper not found")

    summary_type = body.get("type", "full")
    refresh = bool(body.get("refresh", False))
    context = paper.full_text or paper.abstract or ""
    if not context.strip():
        raise HTTPException(status_code=400, detail="Paper text is not available yet")

    if summary_type == "full" and paper.summary and not refresh:
        return {"summary": paper.summary, "cached": True}

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
    # 统一走 LLMAdapter：LLM 不可达时自动降级为离线 mock 总结（不抛 500）
    llm = LLMAdapter.from_config(settings_service.get_llm_config(db, str(user.id)))
    summary = llm.chat(messages, temperature=0.3, max_tokens=1500)
    degraded = summary.strip().startswith("> ⚠️")

    # 全文总结落库缓存（重开界面直接恢复）；降级文案不落库，
    # 配置好 LLM 后点「重新生成」即得正式 AI 总结
    if summary_type == "full" and summary.strip() and not degraded:
        paper.summary = summary
        db.commit()
    return {"summary": summary, "cached": False, "degraded": degraded}


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
        "analysis_status": paper.analysis_status or "done",
        "dimensions": dimensions,
        "user_notes": user_notes,
    }


# ===========================================================================
# Q1-2 多文档综述生成（带精确 in-text citation）
# ---------------------------------------------------------------------------
# 选中 N 篇文献 → 一句指令 → 逐段流式输出综述，每条 claim 都带精确引用。
# Step 1：每篇 paper 拉 chunk 并行做「mini 摘要」（50 篇不超时）；
# Step 2：N 个 mini 摘要 + topic 交给 LLM，要求每段输出附带 \citation{chunk_id,...}；
# Step 3：流式后处理 → 替换成 citation_style 要求的引用格式，
#         并在流结束追加 citations 元事件（与单篇 chat/stream 同构，前端复用）。
# ===========================================================================


class LiteratureReviewRequest(BaseModel):
    paper_ids: list[str]
    topic: str
    structure: str = "thematic"       # thematic | chronological | gap_analysis
    citation_style: str = "apa"       # apa | gb7714 | bibtex_citekey


_REVIEW_STRUCTURE_LABELS = {
    "thematic": "主题式（按研究主题/维度组织段落）",
    "chronological": "时间线式（按研究发展脉络组织段落）",
    "gap_analysis": "研究空白分析式（回顾已有进展，并明确指出尚未解决的研究空白）",
}

_REVIEW_MAX_PAPERS = 50          # 单次综述最多纳入的文献数
_REVIEW_CONTEXT_BUDGET = 30000   # Step 2 提示词预算（字符），超出则截断
_REVIEW_MINI_TIMEOUT = 90        # 并行 mini 摘要总等待上限（秒）


def _review_bibtex_key(paper) -> str:
    """为文献生成稳定的 BibTeX cite key（与导入导出一致的风格）。"""
    authors = paper.authors or []
    title = paper.title or ""
    year = paper.year or ""
    if authors:
        first = (authors[0] or "").strip()
        base = "".join(c for c in (first.split()[0] if first.split() else "") if c.isalnum())
    else:
        base = "".join(c for c in title.split() if c.isalnum())[:6]
    return (base + str(year)).lower() or "paper"


def _review_author_short(authors) -> str:
    """取作者名（中文用全名/姓，西文用姓氏），多位作者追加 et al./等。"""
    if not authors:
        return "Anonymous"
    a = (authors[0] or "").strip()
    if not a:
        return "Anonymous"
    if re.search(r"[\u4e00-\u9fff]", a):
        # 中文名：2-4 字直接保留全名，更长才取姓
        name = a if len(a) <= 4 else a[0]
    else:
        parts = [p for p in re.split(r"\s+", a) if p]
        name = parts[-1] if parts else a
    if len(authors) > 1:
        name += "等" if re.search(r"[\u4e00-\u9fff]", name) else " et al."
    return name


def _review_single_citation(paper, page, style: str) -> str:
    """把单条 chunk 渲染成对应引用样式的 in-text 引用文本（年份缺失时优雅降级）。"""
    short = _review_author_short(paper.authors)
    year = paper.year or ""
    if style == "gb7714":
        base = f"{short}，{year}" if year else short
        return f"{base}，第 {page} 页" if page else base
    if style == "bibtex_citekey":
        return f"\\cite{{{_review_bibtex_key(paper)}}}"
    # apa（默认）
    base = f"{short}, {year}" if year else short
    return f"{base}, p. {page}" if page else base


def _review_render_marker(refs: list[str], alias_map: dict, style: str) -> str:
    """把 ``\\citation{a,b,c}`` 渲染为目标样式文本。

    refs 为提示词中出现的短别名（如 ``c1``），alias_map: 别名 -> {paper, page, content, chunk_id}。
    别名方案显著提升模型引用精度（长 UUID 极易被模型改写/漏抄）。
    """
    if style == "bibtex_citekey":
        keys: list[str] = []
        seen: set[str] = set()
        for ref in refs:
            info = alias_map.get(ref)
            if not info:
                continue
            k = _review_bibtex_key(info["paper"])
            if k not in seen:
                seen.add(k)
                keys.append(k)
        return "\\cite{" + ",".join(keys) + "}" if keys else ""
    parts: list[str] = []
    for ref in refs:
        info = alias_map.get(ref)
        if not info:
            continue
        parts.append(_review_single_citation(info["paper"], info.get("page"), style))
    return "(" + "; ".join(parts) + ")" if parts else ""


def _topic_tokens(topic: str) -> list[str]:
    """切分综述主题为词元，用于离线/无 Embedding 时的片段相关性打分。"""
    tokens = re.findall(r"[a-z0-9][a-z0-9\-]*|\S+", (topic or "").lower())
    return [t for t in tokens if len(t) > 1]


def _review_top_chunks(db: Session, papers, topic: str) -> dict[str, list[dict]]:
    """预取全部选中文献的片段，按与 topic 的关键词重叠排序，每篇最多 6 条。"""
    ids = [p.id for p in papers]
    rows = (
        db.query(PaperChunk)
        .filter(PaperChunk.paper_id.in_(ids))
        .order_by(PaperChunk.created_at.asc())
        .all()
    )
    tokens = _topic_tokens(topic)
    grouped: dict[str, list[dict]] = {}
    for c in rows:
        low = (c.content or "").lower()
        hits = sum(1 for t in tokens if t and t in low)
        grouped.setdefault(str(c.paper_id), []).append(
            {"id": str(c.id), "page": c.page_number, "content": c.content or "", "hits": hits}
        )
    for pid in grouped:
        grouped[pid].sort(key=lambda x: (-x["hits"], -(x["page"] or 0)))
        grouped[pid] = grouped[pid][:6]
    return grouped


def _build_review_context(
    db: Session, user_id, papers, topic: str, llm
) -> list[dict]:
    """Step 1：并行生成每篇论文的 mini 摘要块，返回 [{paper, mini, excerpts}]。

    片段在主线程预取（避免 Session 跨线程使用），线程里只做 LLM 压缩调用；
    LLM 不可用 / 超时 / 降级时自动回退为摘要/标题直取，保证 50 篇不超时。
    """
    chunks_by_paper = _review_top_chunks(db, papers, topic)
    use_llm = llm.provider != "mock"
    results: list[dict] = [None] * len(papers)  # type: ignore[list-item]

    def work(idx: int) -> tuple[int, dict]:
        paper = papers[idx]
        excerpts = chunks_by_paper.get(str(paper.id), [])
        excerpt_text = "\n".join(
            f"- [{e['id']}] (p. {e['page'] or '?'}) {e['content'][:180]}" for e in excerpts
        )
        mini = ""
        if use_llm and excerpt_text.strip():
            system = (
                "You are a research assistant. Write a very concise 2-3 sentence mini summary "
                "of a paper capturing its main methods, key findings and relevance to the given "
                "research topic. Do NOT include citations, page numbers, or bullet lists."
            )
            user_msg = f"Research topic: {topic}\n\nPaper excerpts (chunk ids + page numbers):\n{excerpt_text}"
            try:
                summary = llm.chat(
                    [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
                    temperature=0.3,
                    max_tokens=250,
                ).strip()
                if summary and not summary.startswith("> ⚠️"):
                    mini = summary
            except Exception:  # noqa: BLE001
                mini = ""
        if not mini:
            mini = (paper.abstract or "").strip()[:400] or (paper.title or "Untitled")
        return idx, {"paper": paper, "mini": mini, "excerpts": excerpts}

    if len(papers) <= 12:
        for i in range(len(papers)):
            idx, block = work(i)
            results[idx] = block
    else:
        with ThreadPoolExecutor(max_workers=min(8, len(papers))) as ex:
            futures = [ex.submit(work, i) for i in range(len(papers))]
            done, _pending = wait(futures, timeout=_REVIEW_MINI_TIMEOUT)
            for f in done:
                try:
                    idx, block = f.result()
                    results[idx] = block
                except Exception:  # noqa: BLE001
                    continue
        # 超时/异常未完成的论文：片段直取兜底
        for i, block in enumerate(results):
            if block is None:
                paper = papers[i]
                results[i] = {
                    "paper": paper,
                    "mini": (paper.abstract or "").strip()[:400] or (paper.title or "Untitled"),
                    "excerpts": chunks_by_paper.get(str(paper.id), []),
                }
    return results


def _review_citation_anchor(paper, page) -> str:
    """生成 (Author, Year, p. X) 锚文本，供前端引用芯片展示。"""
    short = _review_author_short(paper.authors)
    year = paper.year or "n.d."
    return f"({short}, {year}, p. {page})" if page else f"({short}, {year})"


@router.post("/batch/literature-review")
def literature_review(
    body: LiteratureReviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """多文档综述生成（SSE 流式）：选中 N 篇文献 → 一句指令 → 逐段输出带精确引用的综述。

    流式结构（与单篇 /papers/{id}/chat/stream 同构，前端复用）：
      data: {"delta": "段落文本"}   （按段输出，引用已按 citation_style 替换）
      data: {"citations": [...]}   （流结束元事件：被引用片段列表，供 citation 芯片）
    """
    topic = (body.topic or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="请填写综述主题")
    structure = body.structure if body.structure in _REVIEW_STRUCTURE_LABELS else "thematic"
    style = body.citation_style if body.citation_style in ("apa", "gb7714", "bibtex_citekey") else "apa"

    papers = (
        db.query(Paper)
        .filter(Paper.user_id == user.id, Paper.id.in_(body.paper_ids))
        .all()
    )
    if not papers:
        raise HTTPException(status_code=400, detail="未找到选中的文献，请先上传并解析文献")
    papers = papers[:_REVIEW_MAX_PAPERS]
    llm = LLMAdapter.from_config(settings_service.get_llm_config(db, str(user.id)))

    def gen():
        yield f"data: {json.dumps({'delta': f'📚 正在为 {len(papers)} 篇文献生成综述…（主题：{topic}）\n\n'})}\n\n"

        # Step 1：并行 mini 摘要
        ctx = _build_review_context(db, user.id, papers, topic, llm)

        # 构造 Step 2 提示词（按预算截断：只保留先到的论文块）
        # 短别名方案：把长 UUID 替换成 c1/c2/…，大幅提升模型抄写引用标记的准确率；
        # 后处理阶段再通过 alias_map 还原为真实 chunk_id。
        alias_map: dict[str, dict] = {}
        blocks: list[str] = []
        used = 0
        alias_no = 0
        for block in ctx:
            paper = block["paper"]
            header = (
                f"### {paper.title or 'Untitled'} | {_review_author_short(paper.authors)} "
                f"({paper.year or 'n.d.'})\n"
            )
            excerpt_lines: list[str] = []
            for e in block["excerpts"]:
                alias_no += 1
                alias = f"c{alias_no}"
                alias_map[alias] = {
                    "chunk_id": e["id"],
                    "paper": paper,
                    "page": e.get("page"),
                    "content": e.get("content") or "",
                }
                excerpt_lines.append(f"- [{alias}] (p. {e['page'] or '?'}) {e['content'][:160]}")
            block_text = (
                f"{header}Mini summary: {block['mini'].strip()}\n"
                f"Chunks:\n{'\n'.join(excerpt_lines)}\n\n"
            )
            if used + len(block_text) > _REVIEW_CONTEXT_BUDGET and used > 0:
                break
            blocks.append(block_text)
            used += len(block_text)

        structure_label = _REVIEW_STRUCTURE_LABELS[structure]
        style_hint = {
            "apa": "author-year citations, e.g. (Smith et al., 2020, p. 12)",
            "gb7714": "中文国标 author-year 引用，如 (张三，2020，第 12 页)",
            "bibtex_citekey": "LaTeX 引用键，如 \\cite{smith2020}",
        }[style]
        system = (
            "You are an academic research assistant writing a literature review section.\n\n"
            f"Research topic: {topic}\n"
            f"Structure: {structure_label}\n"
            f"Citation style: {style_hint}\n\n"
            "Below are the selected papers with mini summaries and their evidence chunks. "
            "Each chunk is labeled with a SHORT alias like [c1], [c2] and a page number.\n\n"
            "Write the literature review in Markdown following the requested structure. Requirements:\n"
            "1. EVERY factual claim MUST be immediately followed by a citation marker, e.g. "
            "\\citation{c1, c3}. You may cite multiple aliases that jointly support the claim.\n"
            "2. ONLY use the aliases that appear in the provided chunk list (like c1, c2, ...). "
            "Never invent aliases, and copy them exactly.\n"
            "3. Example claim with citation: 'The reagent adsorbs strongly on chalcopyrite "
            "surfaces through sulfur-metal bonds \\citation{c1}, leading to selective "
            "flotation at high pH \\citation{c2, c5}.'\n"
            "4. Do NOT write a numbered reference list at the end; the citation markers will be "
            "automatically converted to the required citation style.\n"
            "5. Write several well-organized paragraphs; be thorough but concise."
        )
        user_prompt = f"Papers:\n\n{''.join(blocks)}"

        # Step 3：流式输出 + 引用后处理（按段替换 \citation 标记）
        # 模型只输出短别名（c1/c2…），此处还原为真实 chunk_id 并渲染成目标引用样式。
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user_prompt}]
        buffer = ""
        cited: dict[str, dict] = {}
        marker_re = re.compile(r"\\citation\{([^}]*)\}")

        def process_paragraph(text: str) -> tuple[str, list[str]]:
            refs_in_para: list[str] = []

            def repl(m: re.Match) -> str:
                refs = [c.strip() for c in m.group(1).split(",") if c.strip()]
                refs_in_para.extend(refs)
                return _review_render_marker(refs, alias_map, style)

            return marker_re.sub(repl, text), refs_in_para

        try:
            for tok in llm.chat_stream(messages, temperature=0.3, max_tokens=2500):
                buffer += tok
                while "\n\n" in buffer:
                    para, buffer = buffer.split("\n\n", 1)
                    processed, refs = process_paragraph(para)
                    for ref in refs:
                        if ref in alias_map:
                            cited[alias_map[ref]["chunk_id"]] = alias_map[ref]
                    if processed:
                        yield f"data: {json.dumps({'delta': processed + '\n\n'})}\n\n"
            if buffer.strip():
                processed, refs = process_paragraph(buffer)
                for ref in refs:
                    if ref in alias_map:
                        cited[alias_map[ref]["chunk_id"]] = alias_map[ref]
                if processed:
                    yield f"data: {json.dumps({'delta': processed})}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'delta': f'\n\n⚠️ 综述生成失败：{exc}'})}\n\n"

        # 引用元事件（前端据此渲染 citation 芯片 / 可跳转原文位置）
        citations = []
        for cid, info in cited.items():
            paper = info.get("paper")
            if not paper:
                continue
            citations.append(
                {
                    "chunk_id": cid,
                    "paper_id": str(paper.id),
                    "paper_title": paper.title,
                    "page": info.get("page"),
                    "snippet": (info.get("content") or "")[:160],
                    "citation": _review_single_citation(paper, info.get("page"), style),
                    "anchor": _review_citation_anchor(paper, info.get("page")),
                }
            )
        if citations:
            yield f"data: {json.dumps({'citations': citations})}\n\n"
        yield f"data: {json.dumps({'done': True, 'citation_count': len(citations), 'papers': len(papers)})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
