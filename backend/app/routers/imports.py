"""文献导入路由：Zotero 库 / BibTeX / RIS。

预览与导入分离：preview 只解析不回写，前端先展示命中情况，用户确认后再真正导入。
导入走后台任务解析 PDF（与上传一致），带 PDF 的条目立即可读。
"""
import os
import shutil

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.paper import Paper
from app.models.user import User
from app.services import import_service
from app.routers.papers import _run_processing

router = APIRouter(prefix="/imports", tags=["imports"])


class ZoteroImportRequest(BaseModel):
    data_dir: str


class TextImportRequest(BaseModel):
    content: str


def _entry_preview(entry: dict) -> dict:
    return {
        "title": entry["title"],
        "authors": entry["authors"],
        "year": entry["year"],
        "doi": entry["doi"],
        "journal": entry["journal"],
        "tags": entry["tags"],
        "has_pdf": bool(entry.get("pdf_path")),
    }


@router.post("/zotero/preview")
def zotero_preview(body: ZoteroImportRequest, user: User = Depends(get_current_user)):
    """解析 Zotero 数据目录并返回预览（不回写数据库）。"""
    result = import_service.parse_zotero(body.data_dir.strip())
    if result["errors"]:
        return {"ok": False, "errors": result["errors"], "entries": [], "total": 0, "attachments_found": 0}
    entries = result["entries"]
    return {
        "ok": True,
        "errors": [],
        "entries": [_entry_preview(e) for e in entries[:50]],
        "total": len(entries),
        "attachments_found": result["attachments_found"],
    }


@router.post("/zotero/import")
def zotero_import(
    body: ZoteroImportRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """真正导入 Zotero 库：带 PDF 的条目复制入库存档并后台解析，其余建元数据条目。"""
    result = import_service.parse_zotero(body.data_dir.strip())
    if result["errors"]:
        raise HTTPException(status_code=400, detail=result["errors"][0])
    return _import_entries(db, user, result["entries"], background_tasks, "zotero")


@router.post("/bibtex/preview")
def bibtex_preview(body: TextImportRequest, user: User = Depends(get_current_user)):
    entries = import_service.parse_bibtex(body.content or "")
    return {
        "ok": True,
        "errors": [],
        "entries": [_entry_preview(e) for e in entries[:50]],
        "total": len(entries),
        "attachments_found": 0,
    }


@router.post("/bibtex/import")
def bibtex_import(
    body: TextImportRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    entries = import_service.parse_bibtex(body.content or "")
    return _import_entries(db, user, entries, background_tasks, "bibtex")


@router.post("/ris/preview")
def ris_preview(body: TextImportRequest, user: User = Depends(get_current_user)):
    entries = import_service.parse_ris(body.content or "")
    return {
        "ok": True,
        "errors": [],
        "entries": [_entry_preview(e) for e in entries[:50]],
        "total": len(entries),
        "attachments_found": 0,
    }


@router.post("/ris/import")
def ris_import(
    body: TextImportRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    entries = import_service.parse_ris(body.content or "")
    return _import_entries(db, user, entries, background_tasks, "ris")


def _import_entries(db: Session, user: User, entries: list[dict], background_tasks, source: str) -> dict:
    imported: list[dict] = []
    skipped_duplicates = 0
    with_pdf = 0
    without_pdf = 0
    for e in entries:
        # DOI 去重：同一 DOI 已存在则跳过（避免重复导入）
        if e.get("doi"):
            dup = (
                db.query(Paper)
                .filter(Paper.user_id == user.id, Paper.doi == e["doi"])
                .first()
            )
            if dup:
                skipped_duplicates += 1
                continue
        paper = Paper(
            user_id=user.id,
            title=e["title"],
            authors=e["authors"] or None,
            year=e["year"],
            doi=e["doi"] or None,
            abstract=e["abstract"] or None,
            tags=e["tags"] or None,
            source=source,
            status="ready",
        )
        pdf_path = e.get("pdf_path")
        if pdf_path and os.path.isfile(pdf_path) and pdf_path.lower().endswith(".pdf"):
            stored_name = f"{os.urandom(6).hex()}_{os.path.basename(pdf_path)}"
            dest = os.path.join(settings.PDF_DIR, stored_name)
            try:
                shutil.copyfile(pdf_path, dest)
            except OSError:
                # 附件拷贝失败：降级为无附件元数据条目
                pdf_path = None
            else:
                paper.file_path = f"/pdfs/{stored_name}"
                paper.status = "processing"
                with_pdf += 1
        if not paper.file_path:
            # 无 PDF 附件：以摘要作为全文（AI 问答仍可用），标记分析完成
            paper.full_text = e.get("abstract") or ""
            paper.analysis_status = "done"
            without_pdf += 1
        db.add(paper)
        db.commit()
        db.refresh(paper)
        imported.append(
            {
                "id": str(paper.id),
                "title": paper.title,
                "has_pdf": bool(paper.file_path),
                "status": paper.status,
            }
        )
        # 带 PDF 的条目后台解析（fresh session）
        if paper.file_path:
            background_tasks.add_task(_run_processing, str(paper.id))
    return {
        "ok": True,
        "imported": imported,
        "count": len(imported),
        "with_pdf": with_pdf,
        "without_pdf": without_pdf,
        "skipped_duplicates": skipped_duplicates,
    }
