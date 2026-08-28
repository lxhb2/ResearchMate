"""内置工具注册与实现。

工具是工作流调度引擎的叶子能力，每个工具暴露：名称、说明、参数 JSON Schema、
以及 ``run(ctx, args)`` 实现。工具通过 ``ToolContext`` 注入数据库会话与 LLM 适配器，
因此既可以接入真实后端服务（文献解析、向量检索、翻译），也可以在 mock 模式下离线
演示（不依赖外部服务）。

设计借鉴 DeepSeek Harness 将工具编排与执行解耦的思想，但为独立实现。
"""
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.agent.llm_adapter import LLMAdapter


@dataclass
class ToolContext:
    """工具执行上下文：携带外部依赖，便于注入与测试。"""
    db: Any = None                      # SQLAlchemy Session（可为 None）
    user_id: Optional[str] = None       # 当前用户 ID
    llm: Optional[LLMAdapter] = None    # LLM 适配器
    mock: bool = False                  # True 时不访问外部服务，返回示例数据
    extra: dict = field(default_factory=dict)  # 预留扩展位


class Tool:
    """单个工具的定义与实现。"""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: Callable[[ToolContext, dict], Any],
        source: str = "",
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.source = source  # 来源标记：内置工具为空串，插件工具为插件名

    def run(self, ctx: ToolContext, args: dict) -> Any:
        return self.handler(ctx, args)


# ---------------------------------------------------------------------------
# 各工具的具体实现
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _paper_parse(ctx: ToolContext, args: dict) -> dict:
    """解析 PDF 文献。source 可取 'latest'（最新导入）或具体 paper_id。"""
    source = args.get("source", "latest")
    if ctx.mock or ctx.db is None:
        return {
            "source": source,
            "found": True,
            "paper_id": "mock-paper-001",
            "title": "示例论文标题（Attention is All You Need）",
            "abstract": "This is a sample abstract about a novel method for ...",
            "full_text": "This is the sample full text used for offline demo.",
        }
    # 懒加载，避免导入时连接数据库
    from app.models.paper import Paper
    q = ctx.db.query(Paper).filter(Paper.user_id == ctx.user_id)
    if source == "latest":
        paper = q.order_by(Paper.created_at.desc()).first()
    else:
        paper = q.filter(Paper.id == source).first()
    if paper is None:
        return {"found": False, "error": "未找到论文"}
    return {
        "found": True,
        "paper_id": str(paper.id),
        "title": paper.title,
        "abstract": paper.abstract or "",
        "full_text": (paper.full_text or "")[:12000],
    }


def _rag_search(ctx: ToolContext, args: dict) -> dict:
    """语义检索论文片段（本地 SQLite 向量/关键词降级）。highlighted_only=True 时仅检索用户标记重点的文献。"""
    query = args.get("query", "")
    top_k = int(args.get("top_k", 5))
    dimension = args.get("dimension")
    highlighted_only = bool(args.get("highlighted_only", False))

    if ctx.mock or ctx.db is None:
        hits = [
            {"paper_id": "mock-paper-001", "paper_title": "文献A", "dimension": "method",
             "content": "Method A: uses transformer-based approach.", "score": 0.92},
            {"paper_id": "mock-paper-002", "paper_title": "文献B", "dimension": "method",
             "content": "Method B: uses graph neural network.", "score": 0.88},
        ][:top_k]
        return {"count": len(hits), "hits": hits}

    from app.models.annotation import Annotation
    from app.services import search_service

    hits = search_service.semantic_search(
        ctx.db, query=query, top_k=top_k, dimension=dimension, user_id=ctx.user_id
    )
    if highlighted_only:
        # 仅保留用户标记过重点（highlight/summary）的文献对应片段
        annotated = {
            r.paper_id for r in ctx.db.query(Annotation.paper_id)
            .filter(Annotation.user_id == ctx.user_id)
            .all()
        }
        hits = [h for h in hits if h["paper_id"] in annotated]
    return {"count": len(hits), "hits": hits}


def _llm_translate(ctx: ToolContext, args: dict) -> dict:
    """学术文本中英互译。"""
    text = args.get("text", "")
    target_lang = args.get("target_lang", "zh")
    if not text.strip():
        return {"translation": "", "target_lang": target_lang}
    if ctx.llm is None:
        return {"translation": f"（无 LLM）（Mock）{text}", "target_lang": target_lang}
    system = (
        "你是一名专业学术翻译。请将用户文本翻译成目标语言，保持术语准确，"
        "只返回译文，不要任何解释。"
    )
    user = f"目标语言: {target_lang}\n\n待翻译文本:\n{text}"
    translation = ctx.llm.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.2, max_tokens=1200,
    ).strip()
    return {"translation": translation, "target_lang": target_lang}


def _note_append(ctx: ToolContext, args: dict) -> dict:
    """追加内容到写作项目 / 科研笔记。"""
    content = args.get("content", "")
    project_id = args.get("project_id", "auto")

    if ctx.mock or ctx.db is None:
        return {"ok": True, "project_id": "mock-project-001", "appended": len(content), "note": "（Mock）已写入写作项目"}

    from app.models.project import Project
    q = ctx.db.query(Project).filter(Project.user_id == ctx.user_id)
    if project_id == "auto":
        project = q.order_by(Project.updated_at.desc()).first()
    else:
        project = q.filter(Project.id == project_id).first()
    if project is None:
        return {"ok": False, "error": "未找到写作项目"}
    existing = project.content or ""
    sep = "\n\n" if existing else ""
    project.content = existing + sep + str(content)
    ctx.db.commit()
    return {"ok": True, "project_id": str(project.id), "appended": len(str(content))}


def _llm_compare(ctx: ToolContext, args: dict) -> dict:
    """多篇文献方法/结论对比，输出对比表格。"""
    query = args.get("query", "")
    dimensions = args.get("dimensions", ["method", "conclusion"])
    base_chunks = args.get("materials", [])  # 支持下发已检索的材料

    # 收集对比材料：未下发时，从「6 维度向量表」按指定维度分别检索
    if not base_chunks:
        for d in dimensions:
            base_chunks += _rag_search(ctx, {"query": query, "top_k": 2, "dimension": d})["hits"]
        # 按论文去重，避免同一文献重复
        seen: set[str] = set()
        dedup: list[dict] = []
        for c in base_chunks:
            pid = c.get("paper_id")
            if pid in seen:
                continue
            seen.add(pid)
            dedup.append(c)
        base_chunks = dedup

    if ctx.llm is None:
        materials = "\n".join(f"- {c.get('paper_title','')}: {c.get('content','')}" for c in base_chunks)
        return {
            "table": f"| 维度 | 文献 | 内容 |\n|------|------|------|\n" +
                     "\n".join(f"| {d} | 多篇 | ... |" for d in dimensions),
            "summary": f"（Mock）共对比 {len(base_chunks)} 篇文献。\n{materials[:500]}",
        }

    materials = "\n\n".join(
        f"[{c.get('paper_title','?')}]\n{c.get('content','')}" for c in base_chunks
    )
    system = (
        "你是一名科研文献对比助手。请根据提供的多篇文献片段，按指定维度进行对比，"
        "输出一张 Markdown 表格（第一列为维度，其余列为各文献），并附 2-3 句对比总结。"
        "直接输出 Markdown，不要额外解释。"
    )
    user = f"对比维度: {', '.join(dimensions)}\n\n文献材料:\n{materials}"
    text = ctx.llm.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.2, max_tokens=1500,
    ).strip()
    return {"table": text, "summary": text}


def _citation_generate(ctx: ToolContext, args: dict) -> dict:
    """生成 GB7714 / APA 格式参考文献。"""
    fmt = args.get("format", "GB7714")
    text = args.get("text", "")          # 可提供文献信息文本
    paper_ids = args.get("paper_ids", [])

    if ctx.llm is None:
        return {"format": fmt, "references": ["[1] 示例. 参考文献[M]. 2020."]}

    system = (
        f"你是一名科研格式助手。请根据提供的文献信息，生成 {fmt} 格式的参考文献列表。"
        "只输出格式化后的引用条目，每条一行，不要解释。"
    )
    user = text if text else ", ".join(str(p) for p in paper_ids)
    refs_text = ctx.llm.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user or "请生成一条示例参考文献"}],
        temperature=0.1, max_tokens=800,
    ).strip()
    refs = [ln.strip() for ln in refs_text.splitlines() if ln.strip()]
    return {"format": fmt, "references": refs}


def _paper_summarize(ctx: ToolContext, args: dict) -> dict:
    """对一篇文献做总结，返回结构化总结。

    source 可为 'latest' 或 paper_id；mode 可为 'full'（全文总结）或 'abstract'（摘要总结）。
    dimensions 可指定从「6 维度向量表」取对应维度的片段作为总结素材（如 contributions/results），
    优先于原始全文——这是工作流调用向量表的接口之一。
    """
    source = args.get("source", "latest")
    mode = args.get("mode", "full")
    dimensions = args.get("dimensions", [])

    if ctx.mock or ctx.db is None:
        return {
            "paper_id": "mock-paper-001",
            "title": "示例论文标题",
            "summary": "（Mock）该论文提出了一种新方法，解决了现有方法在效率上的不足。",
            "highlights": ["创新点1", "创新点2"],
        }

    from app.models.paper import Paper
    q = ctx.db.query(Paper).filter(Paper.user_id == ctx.user_id)
    if source == "latest":
        paper = q.order_by(Paper.created_at.desc()).first()
    else:
        paper = q.filter(Paper.id == source).first()
    if paper is None:
        return {"found": False, "error": "未找到论文"}

    # 优先从 6 维度向量表取指定维度片段作为总结素材
    if dimensions and not ctx.mock:
        from app.models.paper_chunk import PaperChunk
        chunks = (
            ctx.db.query(PaperChunk)
            .filter(PaperChunk.paper_id == paper.id, PaperChunk.dimension.in_(dimensions))
            .all()
        )
        if chunks:
            text = "\n\n".join(f"[{c.dimension}] {c.content}" for c in chunks)[:12000]
        else:
            text = (paper.full_text or "")[:12000] if mode == "full" else (paper.abstract or "")
    else:
        text = (paper.full_text or "")[:12000] if mode == "full" else (paper.abstract or "")
    if not text.strip():
        return {"found": True, "paper_id": str(paper.id), "title": paper.title,
                "summary": "（未提取到正文/维度片段，无法总结）"}

    if ctx.llm is None:
        return {"found": True, "paper_id": str(paper.id), "title": paper.title,
                "summary": f"（Mock）{text[:300]}..."}

    system = (
        "你是一名科研论文总结助手。请对论文进行结构化总结，输出 JSON："
        '{"summary": "2-3 句核心总结", "contributions": ["贡献1", "贡献2"], '
        '"keywords": ["关键词1", "关键词2"]}'
    )
    user = f"论文标题：{paper.title}\n\n正文/摘要:\n{text}"
    try:
        data = ctx.llm.chat_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.2,
        )
    except Exception:  # noqa: BLE001
        data = {"summary": text[:300], "contributions": [], "keywords": []}

    return {
        "found": True,
        "paper_id": str(paper.id),
        "title": paper.title,
        "summary": data.get("summary", ""),
        "contributions": data.get("contributions", []),
        "keywords": data.get("keywords", []),
    }


def _library_list(ctx: ToolContext, args: dict) -> dict:
    """列出/检索用户文献库，支持关键词、年份、状态过滤与分页。"""
    keyword = args.get("keyword", "")
    year = args.get("year")
    status = args.get("status")
    limit = int(args.get("limit", 20))
    offset = int(args.get("offset", 0))

    if ctx.mock or ctx.db is None:
        return {
            "count": 2,
            "papers": [
                {"paper_id": "mock-paper-001", "title": "文献A", "year": 2021, "status": "ready"},
                {"paper_id": "mock-paper-002", "title": "文献B", "year": 2022, "status": "ready"},
            ],
        }

    from app.models.paper import Paper
    q = ctx.db.query(Paper).filter(Paper.user_id == ctx.user_id)
    if keyword:
        kw = f"%{keyword}%"
        q = q.filter(Paper.title.ilike(kw))
    if year:
        q = q.filter(Paper.year == int(year))
    if status:
        q = q.filter(Paper.status == status)

    total = q.count()
    rows = q.order_by(Paper.created_at.desc()).offset(offset).limit(limit).all()
    papers = [
        {
            "paper_id": str(p.id),
            "title": p.title,
            "authors": p.authors or [],
            "year": p.year,
            "status": p.status,
            "doi": p.doi,
        }
        for p in rows
    ]
    return {"count": total, "papers": papers}


def _data_analyze(ctx: ToolContext, args: dict) -> dict:
    """实验数据分析：结合文献库与用户分析需求，生成并（可选）执行分析代码，输出结果与图表路径。

    data 可直接传 JSON 数组；question 为自然语言分析需求。exec_code 为 True 时在安全沙箱执行
    生成的 Python 代码，False 时仅返回代码与说明。
    """
    question = args.get("question", "")
    data = args.get("data", [])
    exec_code = bool(args.get("exec_code", True))

    if ctx.llm is None or not question:
        return {
            "code": "# 示例分析代码\nimport statistics\nprint(statistics.mean([1,2,3]))",
            "executed": False,
            "result": "（Mock）未执行分析。",
            "chart": None,
        }

    data_text = ""
    if data:
        try:
            import json as _json
            data_text = _json.dumps(data, ensure_ascii=False)[:6000]
        except Exception:  # noqa: BLE001
            data_text = str(data)[:6000]

    system = (
        "你是一名科研数据分析助手。根据用户的分析需求与数据，生成一段可独立运行的 Python 代码。"
        "要求：使用标准库（statistics/scipy.stats可选），若不可用则用纯 Python 实现；"
        "输出关键统计结果用 print 打印。只返回 Python 代码，不要解释。"
    )
    user = f"分析需求：{question}\n\n数据:\n{data_text or '（未提供数据，请在代码内用示例数据）'}"
    code = ctx.llm.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.2, max_tokens=1200,
    ).strip()
    if code.startswith("```"):
        code = code.split("```")[1]
        if code.startswith("python"):
            code = code[len("python"):]
        code = code.strip()

    if not exec_code:
        return {"code": code, "executed": False, "result": "（未执行）", "chart": None}

    try:
        from app.services import sandbox_service
        result = sandbox_service.run_python(code, timeout=20)
        return {"code": code, "executed": True, "result": result.output, "chart": result.chart}
    except Exception as e:  # noqa: BLE001
        return {"code": code, "executed": False, "result": f"执行失败: {e}", "chart": None}


def _experiment_plan(ctx: ToolContext, args: dict) -> dict:
    """结合文献库的实验设置，为研究问题生成实验设计建议（基线/数据集/评估指标/实验计划）。"""
    question = args.get("question", "")
    top_k = int(args.get("top_k", 4))

    # 从文献库检索相关实验设置片段
    materials = []
    if not (ctx.mock or ctx.db is None):
        from app.services import search_service
        try:
            hits = search_service.semantic_search(
                ctx.db, query=question, top_k=top_k,
                dimension="method", user_id=ctx.user_id,
            )
            materials = [
                {"paper_title": h["paper_title"], "content": h["content"]} for h in hits
            ]
        except Exception:  # noqa: BLE001
            materials = []

    if ctx.llm is None:
        plan = (
            "（Mock）实验设计建议：\n"
            "1. 基线：对比现有最先进方法。\n"
            "2. 数据集：选用领域公开数据集。\n"
            "3. 评估指标：Accuracy / F1。"
        )
        return {"plan": plan, "materials_count": len(materials)}

    materials_text = "\n\n".join(
        f"[{m['paper_title']}]\n{m['content']}" for m in materials
    ) or "（文献库无相关实验设置片段）"
    system = (
        "你是一名科研实验设计顾问。根据研究问题与相关文献的实验设置，输出一份结构化的"
        "Markdown 实验设计建议，包含：研究假设、基线选择、数据集、评估指标、实验步骤、"
        "风险与备选方案。"
    )
    user = f"研究问题：{question}\n\n相关文献实验设置：\n{materials_text}"
    plan = ctx.llm.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.3, max_tokens=1200,
    ).strip()
    return {"plan": plan, "materials_count": len(materials)}


# ---------------------------------------------------------------------------
# 全局能力工具：联网搜索 / 文件配置 / API 一键配置 / 长期记忆 / 模块导航
# ---------------------------------------------------------------------------

def _clean_search_query(q: str) -> str:
    """剥去口语化前缀/连接词，提高搜索引擎结果相关性。

    "搜索陶瓷材料相关文献" → "陶瓷材料 文献"（否则搜索引擎会返回引擎自身页面）。
    """
    import re as _re

    cleaned = _re.sub(
        r"^(请|麻烦|帮我|帮忙|给我)?(在网上|在线|联网)?(搜索|搜一下|检索|查找|查询|查一下|查查|找一下|找)",
        "",
        q.strip(),
    )
    cleaned = _re.sub(
        r"(相关|有关)?的?(学术名词|学术论文|学术资料|研究进展|相关文献|相关资料|相关论文)",
        " ",
        cleaned,
        flags=_re.IGNORECASE,
    )
    cleaned = _re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or q


def _search_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


def _fetch_bing_rss(query: str, limit: int, timeout: float = 15.0) -> list[dict]:
    """Bing RSS：比 HTML 抓取更稳定，自带标题/链接/摘要/日期。"""
    import httpx
    from bs4 import BeautifulSoup
    from xml.etree import ElementTree as ET

    resp = httpx.get(
        "https://www.bing.com/search",
        params={"format": "rss", "q": query, "mkt": "zh-CN", "count": min(limit, 10)},
        headers=_search_headers(),
        timeout=timeout,
        follow_redirects=True,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items: list[dict] = []
    for node in root.findall(".//item"):
        title = node.findtext("title") or ""
        link = (node.findtext("link") or "").strip()
        desc_raw = node.findtext("description") or ""
        desc = BeautifulSoup(desc_raw, "html.parser").get_text(" ", strip=True)
        if title and link and not link.startswith(("http://", "https://")):
            continue
        if title and link:
            items.append(
                {
                    "title": title.strip(),
                    "url": link,
                    "snippet": desc[:300],
                    "date": (node.findtext("pubDate") or "").strip(),
                    "source": "bing",
                }
            )
        if len(items) >= limit:
            break
    return items


def _fetch_bing_html(query: str, limit: int, timeout: float = 15.0) -> list[dict]:
    """Bing HTML 抓取，作为 RSS 无结果时的兜底。"""
    import httpx
    from bs4 import BeautifulSoup

    resp = httpx.get(
        "https://www.bing.com/search",
        params={"q": query, "count": min(limit, 10), "mkt": "zh-CN"},
        headers=_search_headers(),
        timeout=timeout,
        follow_redirects=True,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    items: list[dict] = []
    for li in soup.select("li.b_algo"):
        a = li.select_one("h2 a") or li.select_one("a")
        if not a:
            continue
        title = a.get_text(" ", strip=True)
        href = (a.get("href") or "").strip()
        if not title or not href.startswith(("http://", "https://")):
            continue
        snippet = li.select_one("p")
        text = snippet.get_text(" ", strip=True) if snippet else ""
        items.append(
            {
                "title": title,
                "url": href,
                "snippet": text[:300],
                "date": "",
                "source": "bing",
            }
        )
        if len(items) >= limit:
            break
    return items


def _fetch_duckduckgo_html(query: str, limit: int, timeout: float = 8.0) -> list[dict]:
    """DuckDuckGo HTML 兜底：部分网络环境下可用，失败会自动跳过。"""
    import httpx
    from bs4 import BeautifulSoup

    resp = httpx.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        headers=_search_headers(),
        timeout=timeout,
        follow_redirects=True,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    items: list[dict] = []
    for result in soup.select(".result"):
        a = result.select_one(".result__a")
        if not a:
            continue
        title = a.get_text(" ", strip=True)
        href = (a.get("href") or "").strip()
        if not title or not href.startswith(("http://", "https://")):
            continue
        snippet = result.select_one(".result__snippet")
        text = snippet.get_text(" ", strip=True) if snippet else ""
        items.append(
            {
                "title": title,
                "url": href,
                "snippet": text[:300],
                "date": "",
                "source": "duckduckgo",
            }
        )
        if len(items) >= limit:
            break
    return items


def _web_search(ctx: ToolContext, args: dict) -> dict:
    """联网深度搜索：学术查询走可选学术源，通用查询走公共/自建搜索。

    结果会按 URL/标题去重、关键词与来源可信度重排，并读取少量网页正文作为证据。
    任何单一提供方失败都不会阻断整次搜索。
    """
    raw_query = str(args.get("query") or "")
    query = _clean_search_query(raw_query)
    try:
        limit = max(1, min(int(args.get("limit", 5)), 10))
    except (TypeError, ValueError):
        limit = 5
    if not query:
        return {"count": 0, "items": [], "error": "缺少 query 参数"}

    errors: list[str] = []
    from app.services import web_search_providers

    requested_mode = str(args.get("mode") or "auto").lower()
    if requested_mode not in ("auto", "general", "academic"):
        requested_mode = "auto"
    effective_mode = requested_mode
    if effective_mode == "auto":
        effective_mode = "academic" if web_search_providers._is_academic_query(raw_query) else "general"
    selected_sources = args.get("academic_sources")
    if selected_sources is not None and not isinstance(selected_sources, list):
        selected_sources = [selected_sources]

    search_cfg = None
    if ctx and ctx.db is not None and ctx.user_id:
        from app.services import settings_service

        search_cfg = settings_service.get_search_config(ctx.db, str(ctx.user_id))

    result = web_search_providers.deep_web_search(
        query,
        limit=limit,
        config=search_cfg,
        read_pages=1,
        mode=effective_mode,
        academic_sources=selected_sources,
    )
    if result.get("items"):
        return result
    errors.extend(result.get("errors") or [])
    return {
        "count": 0,
        "items": [],
        "query": query,
        "error": "；".join(errors) or "无搜索结果",
    }


def _file_root() -> str:
    """文件工具的沙箱根目录（仅允许读写此目录，避免越权操作任意路径）。"""
    root = os.path.join(app_settings_dir(), "agent", "files")
    os.makedirs(root, exist_ok=True)
    return root


def app_settings_dir() -> str:
    from app.config import settings as _s
    return _s.STORAGE_DIR


def _resolve_path(name: str) -> str:
    """把用户给出的文件名解析为沙箱内绝对路径；防目录穿越。"""
    safe = os.path.basename((name or "").replace("\\", "/").rstrip("/"))
    if not safe:
        safe = "untitled.txt"
    return os.path.join(_file_root(), safe)


def _file_read(ctx: ToolContext, args: dict) -> dict:
    """读取沙箱内文本文件（用于读取/检查配置文件）。"""
    path = _resolve_path(args.get("path", ""))
    if not os.path.isfile(path):
        return {"ok": False, "error": f"文件不存在：{args.get('path')}", "path": path}
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        return {"ok": True, "path": path, "content": content[:20000]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "path": path}


def _file_write(ctx: ToolContext, args: dict) -> dict:
    """写入（或追加）沙箱内文本文件，用于保存配置/笔记/脚本。"""
    path = _resolve_path(args.get("path", ""))
    content = args.get("content", "")
    append = bool(args.get("append", False))
    try:
        mode = "a" if append else "w"
        with open(path, mode, encoding="utf-8") as f:
            f.write(str(content))
        return {"ok": True, "path": path, "size": os.path.getsize(path)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "path": path}


def _api_configure(ctx: ToolContext, args: dict) -> dict:
    """API 一键配置：保存 LLM 配置（base_url/api_key/model）并重置熔断，立即生效。"""
    from app.services import settings_service
    from app.agent.llm_adapter import reset_breakers

    payload: dict[str, str] = {}
    if args.get("base_url"):
        payload["llm_base_url"] = str(args["base_url"]).strip()
    if args.get("api_key"):
        payload["llm_api_key"] = str(args["api_key"]).strip()
    if args.get("model"):
        payload["llm_model"] = str(args["model"]).strip()

    if ctx.db is None or not ctx.user_id:
        return {"ok": False, "error": "缺少数据库上下文"}
    if not payload:
        return {"ok": False, "error": "至少需要提供 base_url/api_key/model 之一"}

    try:
        settings_service.update_many(ctx.db, str(ctx.user_id), payload)
        reset_breakers()  # 关键：保存后立即清除熔断，新配置马上生效
        return {"ok": True, "updated": list(payload.keys()), "tip": "已保存并立即生效"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"保存失败：{e}"}


def _memory_save(ctx: ToolContext, args: dict) -> dict:
    """保存到长期记忆（本地 md，跨对话共享）。append=True 时追加而不是覆盖。"""
    from app.agent import memory as memory_mod

    if not ctx.user_id:
        return {"ok": False, "error": "缺少用户上下文"}
    name = args.get("name", "notes.md")
    content = args.get("content", "")
    append = bool(args.get("append", True))
    if not content:
        return {"ok": False, "error": "缺少 content"}
    try:
        info = memory_mod.write_memory(ctx.user_id, name, content, append=append)
        return {"ok": True, **info}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _memory_recall(ctx: ToolContext, args: dict) -> dict:
    """从长期记忆检索内容（关键词搜索全部 md 文件），便于 Agent 引用历史偏好。"""
    from app.agent import memory as memory_mod

    if not ctx.user_id:
        return {"ok": False, "error": "缺少用户上下文"}
    query = args.get("query", "")
    if not query:
        # 无查询时返回全部记忆文件摘要
        return {"files": memory_mod.list_memories(ctx.user_id)}
    hits = memory_mod.search(ctx.user_id, query, top_k=int(args.get("top_k", 5)))
    return {"ok": True, "count": len(hits), "hits": hits}


def _module_navigate(ctx: ToolContext, args: dict) -> dict:
    """返回模块导航信息：识别用户想用的功能对应哪个模块、跳转路径与引导步骤。"""
    from app.agent import modules

    text = args.get("text", "")
    if not text:
        text = args.get("query", "")
    result = modules.recommend(text)
    return result


def _system_info(ctx: ToolContext, args: dict) -> dict:
    """获取系统概览：LLM 配置状态、文献/项目数量，供 Agent 判断可用能力。"""
    from app.services import settings_service

    info: dict[str, Any] = {"app": "ResearchMate", "modules": [], "llm_configured": False}
    if ctx.db is not None and ctx.user_id:
        try:
            cfg = settings_service.get_llm_config(ctx.db, str(ctx.user_id))
            key = (cfg.get("api_key") or "").strip()
            info["llm_configured"] = bool(key) and key not in ("", "sk-xxx")
            info["llm_base_url"] = cfg.get("base_url", "")
            info["llm_model"] = cfg.get("model", "")
        except Exception:  # noqa: BLE001
            pass
        try:
            from app.models.paper import Paper
            from app.models.project import Project
            from app.models.conversation import Conversation

            info["paper_count"] = ctx.db.query(Paper).filter(Paper.user_id == ctx.user_id).count()
            info["project_count"] = ctx.db.query(Project).filter(Project.user_id == ctx.user_id).count()
            info["conversation_count"] = ctx.db.query(Conversation).filter(Conversation.user_id == ctx.user_id).count()
        except Exception:  # noqa: BLE001
            pass
    info["modules"] = modules.catalog()
    return info


def _skills_list(ctx: ToolContext, args: dict) -> dict:
    """列出当前可用 Skill（含自定义），供 Agent 判断能调用哪些技能。"""
    try:
        from research_skills.registry import get_registry

        skills = get_registry().all()
        return {
            "count": len(skills),
            "skills": [
                {"name": s.get("name"), "category": s.get("category"), "description": s.get("description")}
                for s in skills
            ],
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "skills": []}


def _mcp_tools(ctx: ToolContext, args: dict) -> dict:
    """列出已配置的 MCP 服务器与其可用工具；refresh=True 时先重新发现。"""
    from app.agent import mcp_runtime
    from app.agent.mcp_store import list_servers

    if args.get("refresh"):
        mcp_runtime.refresh_all()
    servers = list_servers()
    result = []
    for s in servers:
        tools = s.get("tools") or []
        result.append(
            {
                "name": s["name"],
                "type": s.get("type", "http"),
                "enabled": s.get("enabled", True),
                "tools": [
                    {
                        "name": t.get("name"),
                        "description": t.get("description"),
                        "registered": f"mcp__{s['name']}__{t.get('name')}",
                    }
                    for t in tools
                ],
            }
        )
    return {"count": len(servers), "servers": result}


def _skill_search(ctx: ToolContext, args: dict) -> dict:
    """搜索 GitHub 上符合 Agent Skills 规范的技能仓库。"""
    from app.agent.skill_store import search_github

    query = args.get("query", "")
    limit = int(args.get("limit", 6))
    try:
        items = search_github(query, limit)
        return {"count": len(items), "items": items}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "items": []}


def _skill_install(ctx: ToolContext, args: dict) -> dict:
    """从 GitHub 仓库自动导入并注册 Skill（下载 → 解析 SKILL.md → 注册）。"""
    from app.agent.skill_store import import_github

    repo_url = args.get("repo_url", "")
    if not repo_url:
        return {"ok": False, "error": "缺少 repo_url 参数"}
    try:
        skills = import_github(repo_url)
        return {"ok": True, "count": len(skills), "skills": skills}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "skills": []}


def _workflow_execute(ctx: ToolContext, args: dict) -> dict:
    """把一句话任务交给 Agent 拆解为工作流并执行（计划 → 执行 → 汇总）。"""
    task = (args.get("task") or "").strip()
    if not task:
        return {"ok": False, "error": "缺少 task 参数"}
    if ctx.llm is None or ctx.llm.provider == "mock":
        return {"ok": False, "error": "当前未配置可用 LLM，无法自动规划多步任务"}

    from app.agent.agent import Agent, WorkflowGenerationError
    from app.agent.executor import Executor
    from app.agent.schema import Workflow

    try:
        workflow, description = Agent(ctx.llm).generate_workflow(task)
    except WorkflowGenerationError as e:
        return {"ok": False, "error": f"任务规划失败：{e}"}

    try:
        result = Executor(llm=ctx.llm, auto_confirm=False).run(workflow, ctx)
        logs = [
            {"node": log.node_id, "status": log.status, "detail": log.detail}
            for log in result.logs
        ]
        if ctx.user_id:
            try:
                from app.services import reflection_service
                reflection_service.save_reflection(
                    ctx.user_id,
                    "工作流反思",
                    task,
                    str(result.final_output or description),
                    result.status,
                    llm=ctx.llm,
                )
            except Exception:  # noqa: BLE001
                pass
        return {
            "ok": result.status == "success",
            "status": result.status,
            "description": description,
            "workflow_id": workflow.workflow_id,
            "final_output": result.final_output,
            "error": result.error,
            "logs": logs,
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"工作流执行失败：{e}"}


# ---------------------------------------------------------------------------
# 工具注册表
# ---------------------------------------------------------------------------

def _build_registry() -> dict[str, Tool]:
    tools = {
        "paper_parse": Tool(
            name="paper_parse",
            description="解析 PDF 文献（PyMuPDF 本地解析），返回标题、摘要与全文；source 可为 'latest' 或论文 ID。",
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "论文来源：'latest' 或 paper_id"},
                },
                "required": [],
            },
            handler=_paper_parse,
        ),
        "rag_search": Tool(
            name="rag_search",
            description="在本地文献库按语义检索论文片段（6 维度向量表，无向量时关键词降级）；highlighted_only=True 时只检索用户标记重点的文献。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索查询语句"},
                    "top_k": {"type": "integer", "description": "返回片段数（默认 5）"},
                    "dimension": {"type": "string", "description": "片段维度：title_keywords/background/method/results/conclusion/contributions"},
                    "highlighted_only": {"type": "boolean", "description": "是否仅检索标记重点的文献"},
                },
                "required": ["query"],
            },
            handler=_rag_search,
        ),
        "llm_translate": Tool(
            name="llm_translate",
            description="学术文本中英互译，返回 translation。",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "待翻译文本"},
                    "target_lang": {"type": "string", "description": "目标语言，如 zh/en"},
                },
                "required": ["text"],
            },
            handler=_llm_translate,
        ),
        "note_append": Tool(
            name="note_append",
            description="追加内容到写作项目/科研笔记；project_id 为 'auto' 时写入最近项目。",
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "写作项目 ID 或 'auto'"},
                    "content": {"type": "string", "description": "要追加的内容（支持 $results.nodeX.output 引用）"},
                },
                "required": ["content"],
            },
            handler=_note_append,
        ),
        "llm_compare": Tool(
            name="llm_compare",
            description="多篇文献方法/结论对比，返回对比表格 table 与总结 summary。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "用于检索待对比文献的查询"},
                    "dimensions": {"type": "array", "items": {"type": "string"},
                                   "description": "对比维度，如 method/conclusion"},
                    "materials": {"type": "array", "description": "可选：直接传入已检索的片段"},
                },
                "required": ["query"],
            },
            handler=_llm_compare,
        ),
        "citation_generate": Tool(
            name="citation_generate",
            description="生成 GB7714 / APA 格式参考文献列表。",
            parameters={
                "type": "object",
                "properties": {
                    "format": {"type": "string", "description": "格式：GB7714 或 APA"},
                    "text": {"type": "string", "description": "文献信息文本"},
                    "paper_ids": {"type": "array", "items": {"type": "string"}, "description": "论文 ID 列表"},
                },
                "required": [],
            },
            handler=_citation_generate,
        ),
        "paper_summarize": Tool(
            name="paper_summarize",
            description="对一篇文献做全文或摘要级结构化总结，返回 summary/contributions/keywords。"
                        "可指定 dimensions 从 6 维度向量表取对应片段作为总结素材（优先于原始全文）。",
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "论文来源：'latest' 或 paper_id"},
                    "mode": {"type": "string", "description": "总结粒度为 'full'（全文）或 'abstract'（摘要）"},
                    "dimensions": {"type": "array", "items": {"type": "string"},
                                   "description": "可选：从 6 维度向量表取指定维度片段（如 contributions/results）"},
                },
                "required": [],
            },
            handler=_paper_summarize,
        ),
        "library_list": Tool(
            name="library_list",
            description="列出/检索用户文献库，支持关键词、年份、状态过滤与分页。",
            parameters={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "标题关键词过滤"},
                    "year": {"type": "integer", "description": "按年份过滤"},
                    "status": {"type": "string", "description": "按状态过滤：processing/ready/error"},
                    "limit": {"type": "integer", "description": "返回条数（默认 20）"},
                    "offset": {"type": "integer", "description": "分页偏移"},
                },
                "required": [],
            },
            handler=_library_list,
        ),
        "data_analyze": Tool(
            name="data_analyze",
            description="实验数据分析：根据自然语言分析需求生成 Python 代码，并可在安全沙箱执行，返回结果与图表。",
            parameters={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "自然语言分析需求，如'比较两组数据的显著性差异'"},
                    "data": {"type": "array", "description": "可选：直接传入 JSON 数据"},
                    "exec_code": {"type": "boolean", "description": "是否执行生成的代码（默认 True）"},
                },
                "required": ["question"],
            },
            handler=_data_analyze,
        ),
        "experiment_plan": Tool(
            name="experiment_plan",
            description="结合文献库实验设置为研究问题生成实验设计建议（基线/数据集/评估指标/步骤）。",
            parameters={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "研究问题"},
                    "top_k": {"type": "integer", "description": "检索相关实验设置片段数（默认 4）"},
                },
                "required": ["question"],
            },
            handler=_experiment_plan,
        ),
        # ---- 全局能力工具 ----
        "web_search": Tool(
            name="web_search",
            description="联网深度搜索：通用查询优先使用 AgentSearch/SearXNG/AnySearch，学术查询只路由到用户选用的 OpenAlex/Crossref/Europe PMC/Semantic Scholar/OpenCitations/WikiData，返回去重排序后的链接、摘要、证据和来源。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "limit": {"type": "integer", "description": "返回条数（默认 5，最多 10）"},
                    "mode": {
                        "type": "string",
                        "enum": ["auto", "general", "academic"],
                        "description": "路由模式：auto 自动判断，general 通用网页，academic 学术文献",
                    },
                    "academic_sources": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "openalex",
                                "crossref",
                                "europe_pmc",
                                "semantic_scholar",
                                "opencitations",
                                "wikidata",
                            ],
                        },
                        "description": "临时覆盖学术源；缺省时使用设置页保存的学术源列表",
                    },
                },
                "required": ["query"],
            },
            handler=_web_search,
        ),
        "file_read": Tool(
            name="file_read",
            description="读取本地沙箱内文本文件（用于检查配置文件/笔记/脚本）。",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "沙箱内文件名"}},
                "required": ["path"],
            },
            handler=_file_read,
        ),
        "file_write": Tool(
            name="file_write",
            description="写入或追加本地沙箱内文本文件（用于保存配置/笔记/脚本）。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "沙箱内文件名"},
                    "content": {"type": "string", "description": "文件内容"},
                    "append": {"type": "boolean", "description": "是否追加（默认 False 覆盖）"},
                },
                "required": ["path", "content"],
            },
            handler=_file_write,
        ),
        "api_configure": Tool(
            name="api_configure",
            description="API 一键配置：保存 LLM 接口配置（base_url/api_key/model），保存后立即生效、无需多次配置。",
            parameters={
                "type": "object",
                "properties": {
                    "base_url": {"type": "string", "description": "OpenAI 兼容接口地址，如 https://api.deepseek.com/v1"},
                    "api_key": {"type": "string", "description": "API Key"},
                    "model": {"type": "string", "description": "模型名，如 deepseek-chat"},
                },
                "required": [],
            },
            handler=_api_configure,
        ),
        "memory_save": Tool(
            name="memory_save",
            description="保存内容到长期记忆（本地 md 文件，跨所有对话共享），用于记录用户偏好、重要信息。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "记忆文件名（默认 notes.md）"},
                    "content": {"type": "string", "description": "要记忆的内容"},
                    "append": {"type": "boolean", "description": "是否追加（默认 True）"},
                },
                "required": ["content"],
            },
            handler=_memory_save,
        ),
        "memory_recall": Tool(
            name="memory_recall",
            description="从长期记忆中检索内容（关键词搜索全部 md 文件），用于回忆用户偏好与历史记录。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词"},
                    "top_k": {"type": "integer", "description": "返回条数（默认 5）"},
                },
                "required": [],
            },
            handler=_memory_recall,
        ),
        "module_navigate": Tool(
            name="module_navigate",
            description="智能推荐：识别用户想用的功能对应哪个模块，返回跳转路径与引导步骤（向导）。",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string", "description": "用户想做的功能描述"}},
                "required": ["text"],
            },
            handler=_module_navigate,
        ),
        "system_info": Tool(
            name="system_info",
            description="获取系统概览：LLM 配置状态、文献/项目/对话数量、可用模块清单。",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=_system_info,
        ),
        "skills_list": Tool(
            name="skills_list",
            description="列出当前可用的 Skill 技能及其说明（含自定义技能）。",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=_skills_list,
        ),
        "mcp_tools": Tool(
            name="mcp_tools",
            description="列出已配置的 MCP 服务器与其可用工具；refresh=true 时重新连接发现工具。",
            parameters={
                "type": "object",
                "properties": {
                    "refresh": {"type": "boolean", "description": "是否重新连接服务器发现工具"},
                },
                "required": [],
            },
            handler=_mcp_tools,
        ),
        "skill_search": Tool(
            name="skill_search",
            description="在 GitHub 上搜索符合 Agent Skills 规范的技能仓库（用户想找/安装新技能时使用）。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词，如 'arxiv paper review'"},
                    "limit": {"type": "integer", "description": "返回数量，默认 6"},
                },
                "required": ["query"],
            },
            handler=_skill_search,
        ),
        "skill_install": Tool(
            name="skill_install",
            description="从 GitHub 仓库自动导入并注册 Skill（下载 → 解析 SKILL.md → 注册到本地）。",
            parameters={
                "type": "object",
                "properties": {
                    "repo_url": {"type": "string", "description": "GitHub 仓库地址，如 https://github.com/owner/repo"},
                },
                "required": ["repo_url"],
            },
            handler=_skill_install,
        ),
        "workflow_execute": Tool(
            name="workflow_execute",
            description="把一个多步科研任务自动规划为工作流并执行（计划 → 执行 → 汇总），适合需要串联检索、翻译、对比、写入等步骤的任务。",
            parameters={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "一句话描述的多步任务，如：检索最近文献并对比方法，再把结果写入写作项目"},
                },
                "required": ["task"],
            },
            handler=_workflow_execute,
        ),
    }
    return tools


TOOL_REGISTRY: dict[str, Tool] = _build_registry()


def get_tool(name: str) -> Optional[Tool]:
    return TOOL_REGISTRY.get(name)


def tool_names() -> list[str]:
    return list(TOOL_REGISTRY.keys())


def tool_index() -> list[tuple[str, str]]:
    """返回 (工具名, 说明) 列表，供 @ 引用 / 前端展示。"""
    return [(t.name, t.description) for t in TOOL_REGISTRY.values()]


def tool_catalog() -> list[dict]:
    """返回工具的结构化元数据（供前端渲染工具面板 / 迭代接口）。

    每个条目包含 name/description/parameters，是「工具迭代接口」的只读视图：
    前端可据此展示可用工具、参数表单，Agent 据此生成工作流。
    """
    return [
        {
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
        }
        for t in TOOL_REGISTRY.values()
    ]


def register_tool(tool: Tool, source: str = "") -> None:
    """工具迭代接口：注册（或覆盖）一个自定义工具到全局注册表。

    自定义工具只需实现 ``run(ctx, args)``，并声明 name/description/parameters，
    即可被工作流引擎与 Agent 识别。用于后续扩展机器学习、自定义分析等能力。
    ``source`` 非空时标记为插件工具，便于插件停用时批量反注册。
    """
    if source:
        tool.source = source
    TOOL_REGISTRY[tool.name] = tool


def unregister_tool(name: str) -> bool:
    """工具迭代接口：注销一个已注册工具。"""
    return TOOL_REGISTRY.pop(name, None) is not None


def tools_by_source() -> list[dict]:
    """返回全部带来源标记的工具（供插件管理器清理孤儿注册）。"""
    return [
        {"name": t.name, "source": t.source}
        for t in TOOL_REGISTRY.values()
        if getattr(t, "source", "")
    ]


def unregister_tools_by_source(source: str) -> list[str]:
    """按来源批量注销工具（插件停用/卸载时调用），返回被注销的工具名。"""
    names = [t["name"] for t in tools_by_source() if t["source"] == source]
    for n in names:
        TOOL_REGISTRY.pop(n, None)
    return names


def tool_descriptions() -> str:
    """生成给 Agent 的工具说明文本。"""
    lines = []
    for i, name in enumerate(TOOL_REGISTRY, 1):
        t = TOOL_REGISTRY[name]
        lines.append(f"{i}. {t.name}：{t.description}\n   参数: {t.parameters}")
    return "\n\n".join(lines)
