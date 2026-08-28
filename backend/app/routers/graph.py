"""Smart Graph 路由：语义聚类图谱 + 框选批量分析。"""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agent.llm_adapter import LLMAdapter
from app.database import get_db
from app.dependencies import get_current_user
from app.models.paper import Paper
from app.models.paper_chunk import PaperChunk
from app.models.user import User
from app.services import bibliometric_service, graph_service, settings_service
from app.services.search_service import DIMENSION_LABELS

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/smart")
def smart_graph(
    limit: int = 400,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """语义聚类图谱：PCA 降维布局 + 球面 k-means 语义簇 + kNN 关联边。

    结果带缓存（片段数/向量数变化自动失效），个人文献库规模下秒级返回。
    """
    return graph_service.build_smart_graph(db, user.id, limit=limit)


@router.get("/bibliometric")
def bibliometric_graph(
    network_type: str = "co_authorship",
    source: str = "library",
    query: str = "",
    external_source: str = "openalex",
    limit: int = 50,
    cluster_resolution: float = 1.0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """VOSviewer 简易版：合著/关键词共现/引文/文献耦合网络。"""
    try:
        return bibliometric_service.build_bibliometric_graph(
            db,
            user.id,
            network_type=network_type,
            source=source,
            query=query,
            external_source=external_source,
            limit=limit,
            cluster_resolution=cluster_resolution,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/bibliometric/export")
def export_bibliometric_graph(
    network_type: str = "co_authorship",
    source: str = "library",
    query: str = "",
    external_source: str = "openalex",
    limit: int = 50,
    cluster_resolution: float = 1.0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导出可在 VOSviewer 中直接打开的 map + network ZIP 文件。"""
    try:
        graph = bibliometric_service.build_bibliometric_graph(
            db,
            user.id,
            network_type=network_type,
            source=source,
            query=query,
            external_source=external_source,
            limit=limit,
            cluster_resolution=cluster_resolution,
        )
        content = bibliometric_service.build_vosviewer_bundle(graph)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = f"researchmate-{network_type.replace('_', '-')}-vosviewer.zip"
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class GraphAnalyzeRequest(BaseModel):
    chunk_ids: list[str]
    question: str = ""


@router.post("/analyze")
def analyze_selection(
    body: GraphAnalyzeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """框选批量分析：对选中的文献片段做 AI 综合分析（SSE 流式返回）。

    片段以 [S1]/[S2]... 编号注入提示词并要求模型引用标注；
    流结束后追加一个 sources 元事件（文献/页码），前端可点击跳转阅读器。
    LLM 不可达时由 LLMAdapter 自动降级为离线 mock 流，不抛 500。
    """
    ids = [i for i in (body.chunk_ids or []) if i][:30]
    if not ids:
        raise HTTPException(status_code=400, detail="未选中任何片段")
    rows = (
        db.query(PaperChunk, Paper)
        .join(Paper, PaperChunk.paper_id == Paper.id)
        .filter(Paper.user_id == user.id, PaperChunk.id.in_(ids))
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail="片段不存在")
    # 按前端框选顺序稳定排列
    order = {cid: i for i, cid in enumerate(ids)}
    rows.sort(key=lambda r: order.get(str(r[0].id), 10**9))

    excerpts = []
    sources = []
    for i, (chunk, paper) in enumerate(rows):
        dim_label = DIMENSION_LABELS.get(chunk.dimension, chunk.dimension)
        content = (chunk.content or "")[:600]
        excerpts.append(
            f"[S{i + 1}] 《{paper.title or '未命名'}》 第 {chunk.page_number or '?'} 页（{dim_label}）：\n{content}"
        )
        sources.append(
            {
                "index": i + 1,
                "paper_id": str(paper.id),
                "paper_title": paper.title or "未命名",
                "page": chunk.page_number,
            }
        )

    question = (body.question or "").strip() or (
        "这些文献片段共同讨论的主题是什么？关键观点有哪些异同？"
        "它们对后续研究有什么启发？请分点回答。"
    )
    system = (
        "You are a research assistant analyzing excerpts from the user's paper library. "
        "Synthesize the selected excerpts and answer the user's question. "
        "When you rely on a specific excerpt, cite it as [S1]/[S2] etc. "
        "If the excerpts are not enough to answer, say so honestly."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"{question}\n\nExcerpts:\n\n" + "\n\n".join(excerpts)},
    ]
    llm = LLMAdapter.from_config(settings_service.get_llm_config(db, str(user.id)))

    def gen():
        try:
            for tok in llm.chat_stream(messages, temperature=0.3, max_tokens=1500):
                yield f"data: {json.dumps({'delta': tok})}\n\n"
        finally:
            # 批量分析的引用来源元事件（前端渲染可点击的来源列表）
            if sources:
                yield f"data: {json.dumps({'sources': sources})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
