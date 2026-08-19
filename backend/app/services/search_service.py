"""Semantic (and fallback keyword) search over paper_chunks.

这是工作流调用「6 维度向量表」的统一接口层：
- ``DIMENSIONS`` 暴露全部 6 个语义维度，供工具与 Agent 编排引用。
- ``semantic_search`` 按用户隔离、可指定维度，在内存中计算余弦相似度取 Top-K。

轻量化说明：不再依赖 PostgreSQL + pgvector 的数据库级向量索引。
向量以 JSON 文本形式存于 paper_chunks.embedding，检索时读入内存计算余弦，
个人文献库规模（数百篇）性能足够，且完全本地、零服务。
无 Embedding API Key 时自动降级为关键词检索，保证离线可用。
"""
import math
import re

from sqlalchemy.orm import Session

from app.models.paper_chunk import PaperChunk
from app.models.paper import Paper

# 论文 6 个核心语义维度（与 paper_service 拆分保持一致）
# 轻量化：从 11 维精简为 6 维，保留读者最关心的内容。
DIMENSIONS = [
    "title_keywords",
    "background",
    "method",
    "results",
    "conclusion",
    "contributions",
]

# 维度中文名（供展示/引导）
DIMENSION_LABELS = {
    "title_keywords": "标题与关键词",
    "background": "研究背景与动机",
    "method": "方法/模型",
    "results": "实验结果",
    "conclusion": "结论",
    "contributions": "创新点",
}


def _cosine(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度（0~1）。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


def _keyword_score(query_tokens: list[str], content: str) -> float:
    """朴素关键词共现打分（无 Embedding 时的离线降级）。"""
    if not content:
        return 0.0
    low = content.lower()
    hits = sum(1 for t in query_tokens if t and t in low)
    if hits == 0:
        return 0.0
    # 命中越多分越高，并做长度惩罚避免长文本刷分
    return hits / max(len(query_tokens), 1) / (1.0 + math.log2(1 + len(content) / 500))


def _tokenize(query: str) -> list[str]:
    """把查询切分为小写词元（英文按词，连续中文按整句）。"""
    tokens = re.findall(r"[a-z0-9][a-z0-9\-]*|\S+", query.lower())
    return [t for t in tokens if len(t) > 1]


def _embedding_available(db: Session, user_id) -> bool:
    """判断当前是否配置了可用的 Embedding API（无 key 时为 False）。"""
    try:
        from app.services import settings_service
        cfg = settings_service.get_llm_config(db, str(user_id))
        key = (cfg.get("api_key") or "").strip()
        # 占位 key 视为未配置 -> 走关键词降级
        return bool(key) and key not in ("", "sk-xxx", "sk-[YOUR_API_KEY]")
    except Exception:  # noqa: BLE001
        return False


def semantic_search(
    db: Session,
    query: str,
    top_k: int = 5,
    dimension: str | None = None,
    user_id=None,
):
    """对论文片段做检索，返回 Top-K 片段及其出处。

    优先使用向量余弦检索；Embedding 不可用时自动降级为关键词检索。

    Args:
        dimension: 若指定，仅检索该语义维度（见 DIMENSIONS）。
        user_id:    必填，按用户隔离，避免跨用户泄露。
    """
    q = (
        db.query(PaperChunk, Paper)
        .join(Paper, PaperChunk.paper_id == Paper.id)
        .filter(Paper.user_id == user_id)
    )
    if dimension:
        q = q.filter(PaperChunk.dimension == dimension)

    rows = q.all()

    results = []
    query_vec = None
    tokens = _tokenize(query)
    use_embedding = _embedding_available(db, user_id)
    if use_embedding:
        try:
            from app.services import embedding_service
            query_vec = embedding_service.embed(db, user_id, query)
        except Exception:  # noqa: BLE001
            query_vec = None
            use_embedding = False

    if use_embedding and query_vec is not None:
        scored = []
        for chunk, paper in rows:
            vec = chunk.embedding
            if not vec:
                continue
            score = _cosine(query_vec, vec)
            kw_score = _keyword_score(tokens, chunk.content or "")
            # 混合检索：向量主导 + 关键词补偿（成熟 RAG 的 dense + sparse 融合思路）
            hybrid = 0.72 * score + 0.28 * kw_score
            scored.append((hybrid, score, chunk, paper))
        scored.sort(key=lambda x: x[0], reverse=True)
        select = [(r[0], r[2], r[3]) for r in scored[:top_k]]
    else:
        # 关键词降级：作用于全部片段（离线时片段可能没有 embedding）
        scored = []
        for chunk, paper in rows:
            score = _keyword_score(tokens, chunk.content or "")
            if score > 0:
                scored.append((score, chunk, paper))
        scored.sort(key=lambda x: x[0], reverse=True)
        select = scored[:top_k]

    for score, chunk, paper in select:
        results.append(
            {
                "chunk_id": str(chunk.id),
                "paper_id": str(paper.id),
                "paper_title": paper.title,
                "dimension": chunk.dimension,
                "section": chunk.section,
                "content": chunk.content,
                "page_number": chunk.page_number,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                "score": round(score, 4),
            }
        )
    return results


def keyword_search(
    db: Session,
    query: str,
    top_k: int = 5,
    dimension: str | None = None,
    user_id=None,
):
    """纯关键词检索（不依赖 Embedding），用于离线场景的兜底。"""
    q = (
        db.query(PaperChunk, Paper)
        .join(Paper, PaperChunk.paper_id == Paper.id)
        .filter(Paper.user_id == user_id)
    )
    if dimension:
        q = q.filter(PaperChunk.dimension == dimension)

    rows = q.all()
    tokens = _tokenize(query)

    scored = []
    for chunk, paper in rows:
        score = _keyword_score(tokens, chunk.content or "")
        if score > 0:
            scored.append((score, chunk, paper))
    scored.sort(key=lambda x: x[0], reverse=True)

    return [
        {
            "chunk_id": str(chunk.id),
            "paper_id": str(paper.id),
            "paper_title": paper.title,
            "dimension": chunk.dimension,
            "section": chunk.section,
            "content": chunk.content,
            "page_number": chunk.page_number,
            "char_start": chunk.char_start,
            "char_end": chunk.char_end,
            "score": round(score, 4),
        }
        for score, chunk, paper in scored[:top_k]
    ]
