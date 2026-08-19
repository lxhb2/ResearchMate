"""Paper processing pipeline: PyMuPDF parse -> structure-aware splitting -> LLM dimensions -> embedding -> store.

轻量化：移除 GROBID（Java 服务），PDF 解析全部走 PyMuPDF（纯本地）。
借鉴 GROBID / PaperMage / structure-aware chunking 的思路，用轻量规则解析章节层级：

1. 按中英文标题模式识别章节树（Abstract / Introduction / Method / Results / Conclusion 等）；
2. 原文切片不再按页硬切，而是按章节 + 段落边界切分，并保留重叠与章节名；
3. 六维语义拆分时给 LLM 的是带章节标记的结构化正文，而不是截断的连续字符流；
4. 无 LLM 时按章节语义降级，而不是均匀切成 6 段。

无 Embedding API Key 时跳过向量化，仅保存文本片段（检索走关键词降级）。
"""
import os
import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models.paper import Paper
from app.models.paper_chunk import PaperChunk
from app.services import graph_service, llm_service, embedding_service

# 精简后的 6 个核心语义维度（保留读者最关心的内容，删除冗余维度）
DIMENSIONS = [
    "title_keywords",
    "background",
    "method",
    "results",
    "conclusion",
    "contributions",
]

DIMENSION_PROMPT = """You are a scientific paper analyst. Read the ENTIRE structured full text of an academic paper \
(provided with ### section markers and a [SOURCE MAP]). Extract and summarize it into 6 core semantic dimensions. \
Each dimension must be a self-contained paragraph in the SAME LANGUAGE as the paper, grounded in the actual content.

CRITICAL INSTRUCTIONS:
1. Use the [SOURCE MAP] below: background must come from Introduction/Background sections, method from Method/Approach/Data sections, \
results from Results/Experiments/Analysis sections, conclusion from Conclusion/Discussion, contributions from Abstract/Contributions.
2. If the paper is a review without a dedicated Method/Results section, put the research framework from the abstract into "method", \
and put the MAIN BODY ANALYSIS sections into "results" (not only the abstract).
3. Prefer concrete facts, numbers, and findings from the actual sections. Do NOT write a generic abstract-style summary that ignores the body.

Return ONLY a JSON object with these keys (fill every one):
- "title_keywords": the paper title and a short list of keywords / key terms.
- "background": the problem, motivation, and research context.
- "method": the proposed approach, methodology, and model.
- "results": the main findings and quantitative results.
- "conclusion": conclusions and future work.
- "contributions": the paper's main innovations / contributions.

Additionally return:
- "keywords": a list of 5-12 important technical keywords.
- "evidence": an object mapping each dimension key above to the source section title(s) or page(s) you used.

Keep each dimension to 4-8 sentences. Be faithful to the paper; do not invent facts."""


# 送入 LLM 的正文上限（字符数）。原来的 14000 只够约 2-4 页，
# 大于 5 页的论文会被截断成"看起来没解析全"。提高到 60000，
# 覆盖更长的论文，同时避免 token 爆炸。
MAX_EXTRACT_CHARS = 60000

# 结构感知原文切片的参数：片段上限 + 片段间重叠。
# 重叠让检索/图谱不会因为一个语义段落恰好被切断而丢上下文；
# 上限控制在 Embedding 模型常用 token 窗口内。
TEXT_CHUNK_CHARS = 2800
TEXT_CHUNK_OVERLAP = 240
MIN_TEXT_CHUNK = 80


@dataclass
class PaperSection:
    """论文中的一个检测到的小节（heading 起止 + 语义归类）。"""

    level: int
    title: str
    start: int
    end: int
    kind: str = "other"


# 中英文常见章节标题模式（借鉴 GROBID fulltext 的常见 section 命名）。
_CN_NUMBERED_HEADING = re.compile(
    r"^\s*(\d+(?:[.\u3001]\d+)*)[\s.\u3001、]+\s*([^\n]{2,90})$"
)
_EN_KNOWN_HEADING = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[\s.\-]+\s*)?(?:"
    r"Abstract|Introduction|Background|Related Work|Literature Review|Preliminaries|"
    r"Method(?:ology)?|Methods and Materials|Materials and Methods|Experimental Setup|"
    r"Experiments?|Results|Discussion|Conclusion(?:s)?|Contributions|Future Work|"
    r"Acknowledg(?:e)?ments|References|Appendix(?:es)?"
    r")\s*[:.]?\s*$",
    re.IGNORECASE,
)
_CN_KNOWN_HEADING = re.compile(
    r"^\s*(摘要|引言|前言|研究背景|背景|文献综述|相关工作|研究方法|方法|模型|"
    r"实验|结果|讨论|结论|总结|展望|贡献|创新点|参考文献|致谢)\s*[:：]?\s*$"
)


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


def _iter_lines(full_text: str):
    """逐行返回 (行首偏移, 含换行符的原始行)。"""
    offset = 0
    for line in (full_text or "").splitlines(keepends=True):
        yield offset, line
        offset += len(line)


def _classify_section(title: str) -> str:
    """把章节标题归类到六维拆分对应的语义桶。"""
    low = (title or "").lower()
    if any(k in low for k in ("摘要", "abstract", "keyword")):
        return "abstract"
    if any(k in low for k in ("参考文献", "reference")):
        return "references"
    if any(k in low for k in ("结论", "总结", "展望", "讨论", "conclusion", "discussion", "future work")):
        return "conclusion"
    if any(k in low for k in ("贡献", "创新", "contribution")):
        return "contributions"
    if any(k in low for k in ("引言", "背景", "综述", "相关工作", "前言", "introduction", "background", "related work", "literature review", "preliminar")):
        return "background"
    if any(k in low for k in ("方法", "模型", "研究设计", "实验设置", "method", "methodology", "approach", "model", "materials", "experimental setup")):
        return "method"
    if any(k in low for k in ("结果", "实验", "评估", "性能", "result", "experiment", "evaluation", "performance")):
        return "results"
    return "other"


def _heading_hit(line: str) -> dict | None:
    """识别一行是否是论文章节标题。返回 {title, level} 或 None。"""
    s = line.strip()
    if not s or len(s) > 120:
        return None
    m = _CN_NUMBERED_HEADING.match(s)
    if m:
        num = m.group(1)
        first = int(re.match(r"\d+", num).group())
        if first > 15:
            return None
        title = m.group(2).strip()
        # 只接受像 "2 全球..." / "2.1 Methods" 的章节标题；
        # "21 世纪..."、列表项 "8 刚果（金）"、"651 万t" 这类正文短行会被过滤。
        if not (re.match(r"^[\u4e00-\u9fff]{2}", title) or re.match(r"^[A-Za-z]", title)):
            return None
        if re.search(r"[()（）]", title):
            return None
        level = len(re.findall(r"[.\u3001]", num)) + 1
        return {"title": f"{num} {title}", "level": level}
    if _EN_KNOWN_HEADING.match(s):
        title = re.sub(r"^[0-9.\s\-]+", "", s.strip().rstrip(":."))
        return {"title": title, "level": 1}
    if _CN_KNOWN_HEADING.match(s):
        return {"title": s.strip().rstrip(":："), "level": 1}
    return None


def _detect_structure(full_text: str) -> list[PaperSection]:
    """基于标题规则构建轻量章节树（GROBID fulltext 思路的本地版）。"""
    headings: list[dict] = []
    last_top_num = 0
    for start, line in _iter_lines(full_text):
        hit = _heading_hit(line)
        if not hit:
            continue
        if hit["level"] == 1:
            m_num = re.match(r"^(\d+)", hit["title"])
            if m_num:
                n = int(m_num.group(1))
                # 正文里的数字开头短行常被误判成同级标题（如 "2 座坐落于…"）。
                # 真正的一级章节编号通常是递增的，重复/回退编号直接跳过。
                if n <= last_top_num:
                    continue
                last_top_num = n
        title = hit["title"]
        if re.match(r"^(图|表|Figure|Table)\s*\d", title, re.IGNORECASE):
            continue
        hit["kind"] = "references" if title.lower() in ("references", "参考文献", "附中文参考文献") else _classify_section(title)
        hit["start"] = start
        headings.append(hit)
        # 参考文献之后通常是引用列表，停止章节识别，避免把参考文献里的
        # "Background / Resilience" 等词误判为正文章节。
        if hit["kind"] == "references":
            break

    sections: list[PaperSection] = []
    for i, h in enumerate(headings):
        end = headings[i + 1]["start"] if i + 1 < len(headings) else len(full_text or "")
        sections.append(
            PaperSection(
                level=h["level"],
                title=h["title"],
                start=h["start"],
                end=end,
                kind=h.get("kind", "other"),
            )
        )
    return sections


def _top_level_sections(full_text: str, structure: list[PaperSection] | None) -> list[PaperSection]:
    """把检测到的章节折叠成一级章节组，用于切片和 LLM 上下文预算。"""
    if not structure:
        return []
    tops = [s for s in structure if s.level == 1]
    if not tops:
        tops = [structure[0]]
    groups: list[PaperSection] = []
    for i, s in enumerate(tops):
        end = tops[i + 1].start if i + 1 < len(tops) else len(full_text or "")
        groups.append(PaperSection(level=s.level, title=s.title, start=s.start, end=end, kind=s.kind))
    return groups


def _section_cap(kind: str) -> int:
    """每个语义章节送入 LLM 的字符预算（按章节截断，而不是从开头截断）。"""
    return {
        "abstract": 3000,
        "background": 12000,
        "method": 15000,
        "results": 15000,
        "conclusion": 7000,
        "contributions": 4000,
        "references": 0,
        "other": 8000,
    }.get(kind, 8000)


def _build_llm_context(full_text: str, structure: list[PaperSection] | None) -> str:
    """构建带章节标记的 LLM 输入。

    全文在预算内时完整送入；超出预算时按“每章至少一段 + 剩余预算按章节容量分配”
    截断，避免长论文只读到前面几页。
    """
    groups = _top_level_sections(full_text, structure)
    groups = [g for g in groups if g.kind != "references"]
    if not groups:
        return (full_text or "")[:MAX_EXTRACT_CHARS]

    texts = [(g.title, full_text[g.start:g.end].strip()) for g in groups]
    texts = [(t, x) for t, x in texts if x]
    front = (full_text or "")[:2400].strip()
    total = len(front) + sum(len(x) for _t, x in texts)
    if total <= MAX_EXTRACT_CHARS:
        parts = [f"### {title}\n{text}" for title, text in texts]
        if front:
            parts.insert(0, f"### Front matter (title / abstract / keywords)\n{front}")
        return "\n\n".join(parts)

    budget = MAX_EXTRACT_CHARS - len(front)
    caps = [
        min(len(x), max(_section_cap(_classify_section(title)), 1200))
        for title, x in texts
    ]
    alloc = [0] * len(texts)
    min_take = min(800, budget // max(1, len(texts)))
    for i in range(len(texts)):
        alloc[i] = min(min_take, caps[i])
    remaining = budget - sum(alloc)
    while remaining > 0:
        weights = [max(0, caps[i] - alloc[i]) for i in range(len(texts))]
        total_w = sum(weights)
        if total_w <= 0:
            break
        distributed = False
        for i, w in enumerate(weights):
            if w <= 0:
                continue
            add = min(w, max(0, int(remaining * w / total_w)))
            if add <= 0:
                continue
            alloc[i] += add
            remaining -= add
            distributed = True
        if not distributed:
            break

    parts: list[str] = []
    for i, (title, text) in enumerate(texts):
        take = min(len(text), alloc[i])
        body = text[:take]
        if take < len(text):
            body += "\n[TRUNCATED: remaining section content skipped]"
        parts.append(f"### {title}\n{body}")
    if front:
        parts.insert(0, f"### Front matter (title / abstract / keywords)\n{front}")
    return "\n\n".join(parts)


def _extract_front_matter(full_text: str) -> str:
    """取标题页/摘要/关键词附近的文字，供 title_keywords 与离线降级使用。"""
    text = (full_text or "").strip()
    if not text:
        return ""
    m = re.search(r"(摘要|Abstract|KEYWORDS|Keywords)[\s\S]{0,1600}", text, re.IGNORECASE)
    return (m.group(0).strip() if m else text[:1600]).strip()


def _dimension_source_map(
    full_text: str,
    structure: list[PaperSection] | None,
) -> dict[str, list[str]]:
    """按章节语义为六个维度生成建议来源，提示 LLM 不要只盯着摘要。"""
    groups = _top_level_sections(full_text, structure)
    groups = [g for g in groups if g.kind != "references"]
    body = [g for g in groups if g.kind in ("method", "results", "other")]
    by_kind: dict[str, list[str]] = {}
    for g in groups:
        by_kind.setdefault(g.kind, []).append(g.title)
    result: dict[str, list[str]] = {
        "title_keywords": by_kind.get("abstract", []) or (["Front matter"] if groups else []),
        "background": by_kind.get("background", []),
        "method": by_kind.get("method", []),
        "results": by_kind.get("results", []),
        "conclusion": by_kind.get("conclusion", []),
        "contributions": by_kind.get("contributions", []),
    }
    if not result["method"] and body:
        result["method"] = [body[0].title]
    if not result["results"]:
        result["results"] = [g.title for g in body[1:]]
    return result


def _paragraph_balanced_split(text: str, n: int = 6) -> list[str]:
    """无结构时的兜底：按段落边界均衡切分，避免在句子中间硬切。"""
    text = (text or "").strip()
    if not text:
        return [""] * n
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paragraphs) < 2:
        paragraphs = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not paragraphs:
        return [text] + [""] * (n - 1)
    target = max(1, len(text) // n)
    parts = [""] * n
    idx = 0
    for p in paragraphs:
        if idx >= n:
            break
        if parts[idx] and len(parts[idx]) + len(p) > target:
            idx += 1
            if idx >= n:
                break
        parts[idx] = (parts[idx] + "\n\n" if parts[idx] else "") + p
    return parts


def _section_fallback_split(full_text: str, structure: list[PaperSection] | None) -> dict:
    """无 LLM 时的结构感知降级：按章节语义取原文，而不是均匀切成 6 段。"""
    groups = _top_level_sections(full_text, structure)
    front = _extract_front_matter(full_text)

    def first_of(kinds: set[str]) -> str:
        for g in groups:
            if g.kind in kinds:
                return full_text[g.start:g.end].strip()
        return ""

    def nth(i: int) -> str:
        return full_text[groups[i].start:groups[i].end].strip() if i < len(groups) else ""

    body_groups = [g for g in groups if g.kind in ("method", "results", "other")]

    def join_body(idx_list: list[int], max_chars: int = 2600) -> str:
        parts: list[str] = []
        used = 0
        for idx in idx_list:
            if idx >= len(body_groups):
                continue
            text = full_text[body_groups[idx].start:body_groups[idx].end].strip()
            if used and used + len(text) > max_chars:
                break
            parts.append(text)
            used += len(text)
        return "\n\n".join(parts)

    dims = {
        "title_keywords": front[:1600] or nth(0)[:1600],
        "background": (first_of({"background"}) or nth(0))[:2600],
        "method": (first_of({"method"}) or join_body([0]))[:2600],
        "results": (first_of({"results"}) or join_body(list(range(1, len(body_groups)))))[:2600],
        "conclusion": (first_of({"conclusion"}) or (nth(-1) if groups else ""))[:2200],
        "contributions": (first_of({"contributions"}) or (first_of({"conclusion"}) or "")[:1200]),
    }
    if not any(dims.values()):
        parts = _paragraph_balanced_split(full_text, 6)
        for i, d in enumerate(DIMENSIONS):
            dims[d] = parts[i] if i < len(parts) else ""
    return dims


def _page_for_offset(page_offsets: list[int], offset: int) -> int | None:
    """由字符偏移反查页码；page_offsets 为空时返回 None。"""
    if not page_offsets:
        return None
    for idx, start in enumerate(page_offsets):
        if offset < start:
            return idx
    return len(page_offsets)


def _section_line_blocks(full_text: str, start: int, end: int) -> list[tuple[int, int, str]]:
    """把章节范围拆成非空行单元，供贪心分块合并。"""
    blocks: list[tuple[int, int, str]] = []
    for offset, line in _iter_lines(full_text[start:end]):
        if not line.strip():
            continue
        b_start = start + offset
        blocks.append((b_start, b_start + len(line), line))
    return blocks


def _chunk_range(
    paper_id: str,
    full_text: str,
    page_offsets: list[int],
    start: int,
    end: int,
    section_title: str,
) -> list[PaperChunk]:
    """把一个章节范围切成带重叠的段落级片段，并回填页码/字符偏移/章节名。"""
    blocks = _section_line_blocks(full_text, start, end)
    if not blocks:
        return []
    chunks: list[PaperChunk] = []
    seq = 0
    i = 0
    while i < len(blocks):
        j = i
        used = 0
        while j < len(blocks) and used + len(blocks[j][2]) <= TEXT_CHUNK_CHARS:
            used += len(blocks[j][2])
            j += 1
        if j == i:
            j = i + 1
        body_raw = "".join(blocks[k][2] for k in range(i, j))
        body = body_raw.strip()
        if body:
            body_start = blocks[i][0] + (len(body_raw) - len(body_raw.lstrip()))
            body_end = body_start + len(body)
            seq += 1
            chunks.append(
                PaperChunk(
                    paper_id=paper_id,
                    dimension="text",
                    content=body,
                    section=section_title,
                    meta={"role": "section", "section": section_title, "chunk_index": seq},
                    page_number=_page_for_offset(page_offsets, body_start),
                    char_start=body_start,
                    char_end=body_end,
                )
            )
        if j >= len(blocks):
            break
        # 下一块从当前块尾部回退 overlap 字符（按行回退，保证重叠完整）。
        # 剩余内容已不足一个完整块时不再制造重复小片段。
        overlap_budget = min(TEXT_CHUNK_OVERLAP, used // 2)
        if overlap_budget <= 0:
            i = j
            continue
        k = j
        overlap = 0
        while k > i and overlap + len(blocks[k - 1][2]) <= overlap_budget:
            k -= 1
            overlap += len(blocks[k][2])
        i = max(k, i + 1)
    return chunks


def _create_text_chunks(
    paper_id: str,
    full_text: str,
    page_offsets: list[int],
    structure: list[PaperSection] | None = None,
) -> list[PaperChunk]:
    """把全文切分为细粒度原文切片（dimension='text'）。"""
    groups = _top_level_sections(full_text, structure)
    chunks: list[PaperChunk] = []
    if groups:
        first_start = groups[0].start
        if first_start > 0:
            chunks.extend(_chunk_range(paper_id, full_text, page_offsets, 0, first_start, "摘要/标题页"))
        for g in groups:
            if g.kind == "references":
                continue
            chunks.extend(_chunk_range(paper_id, full_text, page_offsets, g.start, g.end, g.title))
    else:
        chunks.extend(_chunk_range(paper_id, full_text, page_offsets, 0, len(full_text or ""), "正文"))
    return chunks


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
        # 结构感知原文切片：先识别章节树，再按章节 + 段落边界切分
        structure = _detect_structure(full_text)
        text_chunks = _create_text_chunks(paper.id, full_text, page_offsets, structure)
        paper.analysis_meta = {
            "structure": [
                {"title": s.title, "level": s.level, "kind": s.kind, "chars": s.end - s.start}
                for s in structure
            ],
            "top_level": [
                {"title": s.title, "kind": s.kind, "chars": s.end - s.start}
                for s in _top_level_sections(full_text, structure)
            ],
            "chunking": {
                "text_chunks": len(text_chunks),
                "mode": "structure" if structure else "paragraph",
                "chunk_chars": TEXT_CHUNK_CHARS,
                "overlap": TEXT_CHUNK_OVERLAP,
            },
        }
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
        graph_service.invalidate_cache(paper.user_id)
    except Exception as e:  # noqa: BLE001
        _mark_error(db, paper, str(e))
        return

    # ---- 阶段 2：LLM 语义拆分 + 向量化（慢；失败不影响阅读） ----
    try:
        dimensions, split_meta = _extract_dimensions(db, paper.user_id, full_text, structure)
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
            page_number, char_start, char_end = _locate_in_fulltext(full_text, content, page_offsets)
            evidence = split_meta.get("evidence", {}).get(key, []) if isinstance(split_meta.get("evidence"), dict) else []
            evidence = evidence if isinstance(evidence, list) else []
            section = evidence[0] if evidence else {
                "title_keywords": "摘要/标题页",
                "background": "引言/背景",
                "method": "方法",
                "results": "结果",
                "conclusion": "结论",
                "contributions": "创新点",
            }.get(key)
            chunk = PaperChunk(
                paper_id=paper.id,
                dimension=key,
                content=content,
                embedding=vec,
                section=section,
                meta={
                    "mode": split_meta.get("mode", "llm"),
                    "keywords": split_meta.get("keywords", []) if isinstance(split_meta.get("keywords"), list) else [],
                    "evidence_sections": evidence,
                },
                page_number=page_number,
                char_start=char_start,
                char_end=char_end,
            )
            db.add(chunk)

        analysis_meta = dict(paper.analysis_meta or {})
        analysis_meta["split"] = {
            "mode": split_meta.get("mode", "llm"),
            "dimension_count": len(keys),
            "keywords": split_meta.get("keywords", []) if isinstance(split_meta.get("keywords"), list) else [],
            "evidence": split_meta.get("evidence", {}) if isinstance(split_meta.get("evidence"), dict) else {},
        }
        paper.analysis_meta = analysis_meta
        paper.analysis_status = "done"
        db.commit()
        graph_service.invalidate_cache(paper.user_id)
    except Exception:  # noqa: BLE001
        # AI 拆分失败：文献仍可正常阅读/问答，仅标记分析失败供前端提示
        try:
            paper.analysis_status = "failed"
            db.commit()
        except Exception:  # noqa: BLE001
            pass


def _evidence_covers(expected: list[str], evidence: list[str]) -> bool:
    """判断 LLM 给出的来源是否覆盖了建议章节（防止它只写“摘要”）。"""
    if not expected:
        return True
    hay = " | ".join(evidence).lower()
    return any(exp.lower() in hay for exp in expected)


def _extract_dimensions(
    db: Session,
    user_id,
    source_text: str,
    structure: list[PaperSection] | None,
) -> tuple[dict, dict]:
    """六维语义拆分：LLM 优先，失败时按章节语义降级。

    返回 (维度文本 dict, 拆分元数据 dict)；拆分元数据包含 keywords / evidence，
    供阅读页与图谱展示每个维度的原文依据。
    """
    context = _build_llm_context(source_text, structure)
    source_map = _dimension_source_map(source_text, structure)
    source_lines = "\n".join(
        f"- {k}: {', '.join(v) if v else '(derive from full text)'}"
        for k, v in source_map.items()
    )
    messages = llm_service.system_user(
        DIMENSION_PROMPT,
        f"[SOURCE MAP]\n{source_lines}\n\nStructured paper text:\n\n{context}",
    )
    fallback = _section_fallback_split(source_text, structure)
    try:
        data = llm_service.chat_json(db, user_id, messages, temperature=0.2)
        dims = {d: str(data.get(d) or "").strip() for d in DIMENSIONS}
        if not any(dims.values()):
            raise ValueError("empty dimensions")
        raw_evidence = data.get("evidence", {})
        evidence = {}
        if isinstance(raw_evidence, dict):
            for k, v in raw_evidence.items():
                if isinstance(v, str) and v.strip():
                    evidence[k] = [part.strip() for part in v.split(",") if part.strip()]
                elif isinstance(v, list):
                    evidence[k] = [str(x).strip() for x in v if str(x).strip()]
        meta = {
            "mode": "llm",
            "keywords": data.get("keywords", []) if isinstance(data.get("keywords"), list) else [],
            "evidence": evidence,
        }
        # 防“只读摘要”：若关键维度没有引用建议章节，用章节原文兜底，保证结果贴合正文。
        for key in ("background", "method", "results", "conclusion"):
            expected = source_map.get(key, [])
            if not expected or _evidence_covers(expected, evidence.get(key, [])):
                continue
            grounded = (fallback.get(key) or "").strip()
            if grounded:
                dims[key] = grounded
                evidence[key] = expected
                meta["mode"] = "llm-grounded"
        return dims, meta
    except Exception:  # noqa: BLE001
        return fallback, {"mode": "fallback", "keywords": [], "evidence": {}}

def _locate_in_fulltext(
    full_text: str,
    content: str,
    page_offsets: list[int] | None = None,
) -> tuple[int | None, int | None, int | None]:
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
    page_number = _page_for_offset(page_offsets or [], char_start)
    if page_number is None:
        # 无 page_offsets 时按换行数估算页码
        page_number = full_text.count("\n", 0, char_start) + 1
    return page_number, char_start, char_end


def _mark_error(db: Session, paper: Paper, msg: Optional[str] = None) -> None:
    paper.status = "error"
    paper.analysis_status = "failed"
    if msg:
        paper.full_text = (paper.full_text or "") + f"\n\n[ERROR] {msg}"
    db.commit()
