"""文献导入路由：Zotero 库 / BibTeX / RIS。

预览与导入分离：preview 只解析不回写，前端先展示命中情况，用户确认后再真正导入。
导入走后台任务解析 PDF（与上传一致），带 PDF 的条目立即可读。
"""
import os
import shutil

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.paper import Paper
from app.models.user import User
from app.services import import_service

router = APIRouter(prefix="/imports", tags=["imports"])


class ZoteroImportRequest(BaseModel):
    data_dir: str


class TextImportRequest(BaseModel):
    content: str


class MetadataLookupRequest(BaseModel):
    query: str
    sources: list[str] = []


class MetadataApplyRequest(BaseModel):
    paper_id: str
    metadata: dict


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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """真正导入 Zotero 库：带 PDF 的条目复制入库存档并后台解析，其余建元数据条目。"""
    result = import_service.parse_zotero(body.data_dir.strip())
    if result["errors"]:
        raise HTTPException(status_code=400, detail=result["errors"][0])
    return _import_entries(db, user, result["entries"], "zotero")


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


@router.post("/metadata")
def lookup_metadata(body: MetadataLookupRequest, user: User = Depends(get_current_user)):
    """在线补全元数据：按 DOI / arXiv ID / 标题从多个来源检索候选。"""
    from app.services import metadata_service
    return metadata_service.lookup(body.query, body.sources or None)


@router.post("/metadata/apply")
def apply_metadata(
    body: MetadataApplyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """把查到的元数据应用到已有文献记录。"""
    paper = db.get(Paper, body.paper_id)
    if not paper or paper.user_id != user.id:
        raise HTTPException(status_code=404, detail="Paper not found")
    meta = body.metadata or {}
    doi = (meta.get("doi") or "").strip()
    if doi:
        dup = (
            db.query(Paper)
            .filter(Paper.user_id == user.id, Paper.doi == doi, Paper.id != paper.id)
            .first()
        )
        if dup:
            raise HTTPException(status_code=400, detail="该 DOI 已存在于你的文献库")
    dirty = False
    for field in ("title", "authors", "year", "doi", "abstract"):
        if field in meta and meta[field] is not None:
            setattr(paper, field, meta[field])
            dirty = True
    if dirty:
        db.commit()
        db.refresh(paper)
    return {
        "ok": True,
        "paper": {
            "id": str(paper.id),
            "title": paper.title,
            "authors": paper.authors or [],
            "year": paper.year,
            "doi": paper.doi,
            "abstract": paper.abstract,
        },
    }


@router.post("/bibtex/import")
def bibtex_import(
    body: TextImportRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    entries = import_service.parse_bibtex(body.content or "")
    return _import_entries(db, user, entries, "bibtex")


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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    entries = import_service.parse_ris(body.content or "")
    return _import_entries(db, user, entries, "ris")


def _import_entries(db: Session, user: User, entries: list[dict], source: str) -> dict:
    imported: list[dict] = []
    skipped_duplicates = 0
    with_pdf = 0
    without_pdf = 0
    from app.services import task_queue

    def store_pdf(pdf_path: str) -> str | None:
        """把 Zotero 附件复制到 ResearchMate 的 PDF 目录，返回 /pdfs/... 路径。"""
        if not pdf_path or not os.path.isfile(pdf_path) or not pdf_path.lower().endswith(".pdf"):
            return None
        os.makedirs(settings.PDF_DIR, exist_ok=True)
        stored_name = f"{os.urandom(6).hex()}_{os.path.basename(pdf_path)}"
        dest = os.path.join(settings.PDF_DIR, stored_name)
        try:
            shutil.copyfile(pdf_path, dest)
        except OSError:
            return None
        return f"/pdfs/{stored_name}"

    for e in entries:
        # DOI 去重：同一 DOI 已存在则跳过（避免重复导入）
        dup = None
        if e.get("doi"):
            dup = db.query(Paper).filter(
                Paper.user_id == user.id, Paper.doi == e["doi"]
            ).first()
        else:
            # 无 DOI 的旧 Zotero 记录按来源 + 标题匹配，重新导入时补附件
            dup = db.query(Paper).filter(
                Paper.user_id == user.id,
                Paper.source == source,
                Paper.title == e["title"],
            ).first()
        if dup:
            # 旧记录缺 PDF 时补附件，避免用户必须先删旧数据再重导
            if not dup.file_path and e.get("pdf_path"):
                file_path = store_pdf(e["pdf_path"])
                if file_path:
                    dup.file_path = file_path
                    dup.status = "processing"
                    db.commit()
                    db.refresh(dup)
                    task_queue.enqueue(db, user.id, "paper_processing", {"paper_id": str(dup.id)})
                    imported.append(
                        {
                            "id": str(dup.id),
                            "title": dup.title,
                            "has_pdf": True,
                            "status": dup.status,
                        }
                    )
                    with_pdf += 1
                    continue
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
        stored_path = store_pdf(pdf_path) if pdf_path else None
        if stored_path:
            paper.file_path = stored_path
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
        # 带 PDF 的条目进入持久化任务队列
        if paper.file_path:
            task_queue.enqueue(db, user.id, "paper_processing", {"paper_id": str(paper.id)})
    return {
        "ok": True,
        "imported": imported,
        "count": len(imported),
        "with_pdf": with_pdf,
        "without_pdf": without_pdf,
        "skipped_duplicates": skipped_duplicates,
    }
