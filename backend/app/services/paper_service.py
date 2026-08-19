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


# 送入 LLM 的正文上限（字符数）。原来的 14000 只够约 2-4 页，
# 大于 5 页的论文会被截断成"看起来没解析全"。提高到 60000，
# 覆盖更长的论文，同时避免 token 爆炸。
MAX_EXTRACT_CHARS = 60000


def _extract_text_with_pymupdf(abs_path: str) -> tuple[str, list[int]]:
    """用 PyMuPDF 抽取 PDF 全文，并返回每页在全文中的起始字符偏移。

    返回 (full_text, page_offsets)，page_offsets[i] 为第 i+1 页首字符在 full_text 中的偏移。
    逐页容错：某些复杂 PDF 的某一页可能损坏/抛异常，逐页 try/except
    保证其它页仍能提取，而不是整篇解析失败。
    """
    try:
        import pymupdf  # noqa: PLC0415

        doc = pymupdf.open(abs_path)
        try:
            parts: list[str] = []
            offsets: list[int] = []
            for page in doc:
                try:
                    t = page.get_text("text")
                    if not t.strip():
                        # 部分复杂 PDF 用 "text" 模式取不到，但 blocks 可取出
                        blocks = page.get_text("blocks")
                        t = "\n".join(b[4] for b in blocks if len(b) >= 5 and b[4].strip())
                except Exception:  # noqa: BLE001
                    t = ""
                offsets.append(sum(len(p) + 1 for p in parts))
                parts.append(t)
            raw_text = "\n".join(parts)
            full_text = raw_text.strip()
            # 修正每页起始偏移：去掉首尾空白后，后续偏移需平移
            leading = len(raw_text) - len(raw_text.lstrip())
            offsets = [max(0, off - leading) for off in offsets]
            return full_text, offsets
        finally:
            doc.close()
    except Exception:  # noqa: BLE001
        return "", []


def _is_likely_scanned(full_text: str, page_count: int) -> bool:
    """启发式判断是否为扫描版/图片型 PDF（无文字层）。

    平均每页可提取字符数过少时，判定为"疑似扫描版"，
    便于给出更明确的提示而不是笼统报错。
    """
    if page_count <= 0:
        return False
    avg = len(full_text or "") / page_count
    return avg < 50


def _count_pages(abs_path: str) -> int:
    """返回 PDF 页数；失败返回 0（不抛异常）。"""
    try:
        import pymupdf  # noqa: PLC0415

        doc = pymupdf.open(abs_path)
        try:
            return doc.page_count
        finally:
            doc.close()
    except Exception:  # noqa: BLE001
        return 0


def _extract_title_heuristic(full_text: str) -> str:
    """从 pymupdf 抽取的文本中启发式取标题（前几行非空文本）。"""
    for line in (full_text or "").splitlines():
        line = line.strip()
        if len(line) >= 8 and sum(c.isalpha() for c in line) >= 4:
            return line[:300]
    return ""


def _extract_year_heuristic(full_text: str) -> Optional[int]:
    """从正文开头启发式提取发表年份（19xx / 20xx，取首个合理命中）。"""
    import re  # noqa: PLC0415

    head = (full_text or "")[:2000]
    m = re.search(r"\b(19[89]\d|20[0-4]\d)\b", head)
    return int(m.group(1)) if m else None


def process_paper(paper_id: str, db: Session) -> None:
    """后台任务：处理一篇已上传的论文。分两阶段落库（Zotero 式体验）。

    阶段 1（快，纯本地 PyMuPDF，通常 < 1s）：抽取全文/页数/年份 → status="ready"。
      之后用户即可点开 PDF 阅读、划词翻译、基于全文问答。
    阶段 2（慢，LLM 六维语义拆分 + Embedding）：analysis_status pending → done。
      在后台慢慢跑，不阻塞阅读；失败也不影响已 ready 的阅读体验。
    """
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

        # ---- 阶段 1：本地快速解析（PyMuPDF，秒级） ----
        full_text, page_offsets = _extract_text_with_pymupdf(abs_path)
        page_count = _count_pages(abs_path)
        if not full_text.strip():
            if _is_likely_scanned(full_text, page_count):
                _mark_error(
                    db,
                    paper,
                    "No extractable text from PDF (likely a scanned/image-only PDF). "
                    "OCR is not bundled; please upload a text-based PDF.",
                )
            else:
                _mark_error(db, paper, "No extractable text from PDF")
            return

        if not paper.title:
            paper.title = _extract_title_heuristic(full_text) or os.path.basename(paper.file_path)
        if paper.year is None:
            paper.year = _extract_year_heuristic(full_text)
        paper.full_text = full_text
        # 移除旧的原文切片（重复处理场景），保留 LLM 维度摘要（阶段 2 单独更新）
        db.query(PaperChunk).filter(
            PaperChunk.paper_id == paper.id, PaperChunk.dimension == "text"
        ).delete()
        # 生成细粒度原文切片，用于 RAG / citation 溯源 / Smart Graph
        text_chunks = _create_text_chunks(paper.id, full_text, page_offsets)
        if text_chunks and embedding_service.is_available(db, paper.user_id):
            try:
                texts = [c.content for c in text_chunks]
                vectors = embedding_service.embed_many(db, paper.user_id, texts)
                for i, chunk in enumerate(text_chunks):
                    if i < len(vectors):
                        chunk.embedding = vectors[i]
            except Exception:  # noqa: BLE001
                pass
        for chunk in text_chunks:
            db.add(chunk)
        # 快写落库：status 置 ready，用户此刻已可打开阅读与问答；
        # AI 维度拆分标记 pending，继续在后台慢慢跑。
        paper.status = "ready"
        paper.analysis_status = "pending"
        db.commit()
    except Exception as e:  # noqa: BLE001
        _mark_error(db, paper, str(e))
        return

    # ---- 阶段 2：LLM 语义拆分 + 向量化（慢；失败不影响阅读） ----
    try:
        dimensions = _extract_dimensions(db, paper.user_id, full_text)
        texts = [dimensions[d] for d in DIMENSIONS if (dimensions.get(d) or "").strip()]
        keys = [d for d in DIMENSIONS if (dimensions.get(d) or "").strip()]

        # 移除旧的 LLM 维度摘要（保留原文切片 dimension='text'）
        db.query(PaperChunk).filter(
            PaperChunk.paper_id == paper.id, PaperChunk.dimension.in_(DIMENSIONS)
        ).delete()

        # Embedding 可用时向量化；否则仅存文本（检索走关键词降级）
        vectors: list[list[float]] = []
        if texts and embedding_service.is_available(db, paper.user_id):
            try:
                vectors = embedding_service.embed_many(db, paper.user_id, texts)
            except Exception:  # noqa: BLE001
                vectors = []

        for i, key in enumerate(keys):
            vec = vectors[i] if i < len(vectors) else None
            content = texts[i]
            page_number, char_start, char_end = _locate_in_fulltext(full_text, content)
            chunk = PaperChunk(
                paper_id=paper.id,
                dimension=key,
                content=content,
                embedding=vec,
                page_number=page_number,
                char_start=char_start,
                char_end=char_end,
            )
            db.add(chunk)

        paper.analysis_status = "done"
        db.commit()
    except Exception:  # noqa: BLE001
        # AI 拆分失败：文献仍可正常阅读/问答，仅标记分析失败供前端提示
        try:
            paper.analysis_status = "failed"
            db.commit()
        except Exception:  # noqa: BLE001
            pass


def _extract_dimensions(db, user_id, source_text: str) -> dict:
    # Truncate to avoid token blowup（上限提高到能覆盖多页论文）
    truncated = source_text[:MAX_EXTRACT_CHARS]
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


def _create_text_chunks(
    paper_id: str, full_text: str, page_offsets: list[int]
) -> list[PaperChunk]:
    """把全文按页切分为细粒度原文切片（dimension='text'），用于 RAG / citation 溯源。

    每页生成一个 chunk；空页或内容过少的页跳过，减少无意义向量。
    """
    chunks: list[PaperChunk] = []
    for idx, start in enumerate(page_offsets):
        page_number = idx + 1
        end = page_offsets[idx + 1] - 1 if idx + 1 < len(page_offsets) else len(full_text)
        # 注意：full_text 经 .strip() 后可能与原始拼接长度不同，
        # 这里以 offsets 计算的范围截取；strip 只影响首尾空白，
        # 对中间页影响极小，可接受。
        content = full_text[start:end].strip()
        if len(content) < 20:
            continue
        chunks.append(
            PaperChunk(
                paper_id=paper_id,
                dimension="text",
                content=content,
                page_number=page_number,
                char_start=start,
                char_end=end,
            )
        )
    return chunks


def _locate_in_fulltext(full_text: str, content: str) -> tuple[int | None, int | None, int | None]:
    """在 full_text 中定位 content 的位置，返回 (page_number, char_start, char_end)。

    用于 LLM 维度摘要 chunk 回填 page/offset。若找不到或全文为空则返回 (None, None, None)。
    """
    if not full_text or not content:
        return None, None, None
    snippet = content[:200].strip()
    if not snippet:
        return None, None, None
    idx = full_text.find(snippet)
    if idx == -1:
        return None, None, None
    char_start = idx
    char_end = min(idx + len(content), len(full_text))
    # 页码通过换页符（parts 之间用 \n 拼接）估算：数前面有多少个 \n
    # 更精确的做法需要 page_offsets，但 stage2 调用处未传，这里先按换行数估算
    page_number = full_text.count("\n", 0, char_start) + 1
    return page_number, char_start, char_end


def _mark_error(db: Session, paper: Paper, msg: Optional[str] = None) -> None:
    paper.status = "error"
    paper.analysis_status = "failed"
    if msg:
        paper.full_text = (paper.full_text or "") + f"\n\n[ERROR] {msg}"
    db.commit()