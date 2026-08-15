"""Paper processing pipeline: PyMuPDF parse -> LLM dimension extraction -> embedding -> store.

轻量化：移除 GROBID（Java 服务），PDF 解析全部走 PyMuPDF（纯本地）。
无 Embedding API Key 时跳过向量化，仅保存文本片段（检索走关键词降级）。
"""
import os
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models.paper import Paper
from app.models.paper_chunk import PaperChunk
from app.services import llm_service, embedding_service

# 精简后的 6 个核心语义维度（保留读者最关心的内容，删除冗余维度）
DIMENSIONS = [
    "title_keywords",
    "background",
    "method",
    "results",
    "conclusion",
    "contributions",
]

DIMENSION_PROMPT = """You are a scientific paper analyst. Given the full text of an academic paper, \
extract and summarize it into 6 core semantic dimensions. Each dimension must be a self-contained natural-language \
paragraph in English capturing that aspect of the paper.

Return ONLY a JSON object with these keys (fill every one):
- "title_keywords": the paper title and a short list of keywords / key terms.
- "background": the problem, motivation, and research context.
- "method": the proposed approach, methodology, and model.
- "results": the main findings and quantitative results.
- "conclusion": conclusions and future work.
- "contributions": the paper's main innovations / contributions.

Keep each dimension to 3-6 sentences. Be faithful to the paper; do not invent facts."""


def _extract_text_with_pymupdf(abs_path: str) -> str:
    """用 PyMuPDF 抽取 PDF 全文（纯本地，无外部服务依赖）。"""
    try:
        import pymupdf  # noqa: PLC0415

        doc = pymupdf.open(abs_path)
        try:
            text = "\n".join(page.get_text() for page in doc)
        finally:
            doc.close()
        return text.strip()
    except Exception:  # noqa: BLE001
        return ""


def _extract_title_heuristic(full_text: str) -> str:
    """从 pymupdf 抽取的文本中启发式取标题（前几行非空文本）。"""
    for line in (full_text or "").splitlines():
        line = line.strip()
        if len(line) >= 8 and sum(c.isalpha() for c in line) >= 4:
            return line[:300]
    return ""


def process_paper(paper_id: str, db: Session) -> None:
    """后台任务：处理一篇已上传的论文。会修改数据库。"""
    paper = db.get(Paper, str(paper_id))
    if paper is None:
        return
    try:
        if not paper.file_path:
            _mark_error(db, paper)
            return
        abs_path = os.path.join(settings.PDF_DIR, os.path.basename(paper.file_path))
        if not os.path.exists(abs_path):
            _mark_error(db, paper)
            return

        # 全部走 PyMuPDF 本地抽取（不再依赖 GROBID）
        full_text = _extract_text_with_pymupdf(abs_path)
        if not full_text.strip():
            _mark_error(db, paper, "No extractable text from PDF")
            return

        if not paper.title:
            paper.title = _extract_title_heuristic(full_text) or os.path.basename(paper.file_path)
        paper.full_text = full_text
        # 移除旧片段（重复处理场景）
        db.query(PaperChunk).filter(PaperChunk.paper_id == paper.id).delete()
        # 提前提交：正文与标题是"快写"，先落库，避免在下面较慢的 LLM/Embedding 调用期间
        # 长时间持有 SQLite 写锁，导致用户并发做笔记/批注时出现 "database is locked"。
        db.commit()

        # 语义化拆分（LLM 可用时）；LLM 不可用时用朴素切分兜底
        dimensions = _extract_dimensions(db, paper.user_id, full_text)
        texts = [dimensions[d] for d in DIMENSIONS if (dimensions.get(d) or "").strip()]
        keys = [d for d in DIMENSIONS if (dimensions.get(d) or "").strip()]

        # Embedding 可用时向量化；否则仅存文本（检索走关键词降级）
        vectors: list[list[float]] = []
        if texts and embedding_service.is_available(db, paper.user_id):
            try:
                vectors = embedding_service.embed_many(db, paper.user_id, texts)
            except Exception:  # noqa: BLE001
                vectors = []

        for i, key in enumerate(keys):
            vec = vectors[i] if i < len(vectors) else None
            chunk = PaperChunk(
                paper_id=paper.id,
                dimension=key,
                content=texts[i],
                embedding=vec,
            )
            db.add(chunk)

        paper.status = "ready"
        db.commit()
    except Exception as e:  # noqa: BLE001
        _mark_error(db, paper, str(e))


def _extract_dimensions(db, user_id, source_text: str) -> dict:
    # Truncate to avoid token blowup.
    truncated = source_text[:14000]
    messages = llm_service.system_user(
        DIMENSION_PROMPT,
        f"Paper text:\n\n{truncated}",
    )
    try:
        return llm_service.chat_json(db, user_id, messages, temperature=0.2)
    except Exception:
        # LLM 不可用时：朴素切分，保证有内容可检索
        splits = _naive_split(truncated)
        dims = dict.fromkeys(DIMENSIONS, "")
        for i, d in enumerate(DIMENSIONS):
            if i < len(splits):
                dims[d] = splits[i]
        return dims


def _naive_split(text: str, n: int = 6) -> list[str]:
    """把长文本朴素均分为 n 段（无 LLM 时的兜底，段数=维度数）。"""
    text = text or ""
    if not text:
        return [""] * n
    seg = max(1, len(text) // n)
    parts = [text[i * seg:(i + 1) * seg] for i in range(n)]
    return parts


def _mark_error(db: Session, paper: Paper, msg: Optional[str] = None) -> None:
    paper.status = "error"
    if msg:
        paper.full_text = (paper.full_text or "") + f"\n\n[ERROR] {msg}"
    db.commit()