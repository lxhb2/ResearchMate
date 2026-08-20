"""Smart Graph 语义聚类图谱服务。

参考 Latent Scope / Nomic Atlas 的「embed → reduce → cluster → label」本地管线，
做纯 Python 轻量化实现（不引入 numpy/scikit-learn 硬依赖；装了 numpy 自动加速）：

1. 降维布局：先做确定性随机池化投影（D→64 维，一次 O(N·D) 扫描，是 JL 随机
   投影的廉价变体，保留余弦结构），再用 PCA 幂迭代取前 2 主成分生成 2D 布局
   （确定性、即时；TensorBoard Embedding Projector 的默认视图同为 PCA）。
2. 聚类：球面 k-means（k-means++ 初始化 + 余弦相似度分配，embedding 天然适合
   在单位球面上聚类）。
3. 簇标签：中英文分词 + 簇内频次/跨簇普及度打分，取 top 关键词合成标签。
4. 语义关联：kNN 余弦相似边（每节点 top-2 邻居），呈现簇内/簇间关联。

离线降级：未配置 Embedding API（或可用向量不足 3 个）时，退化为哈希词袋伪向量，
图谱仍可基于关键词语义构建（与检索层的关键词降级策略一致）。
"""
import math
import random
import re
import zlib
from collections import Counter

from sqlalchemy.orm import Session

from app.models.paper import Paper
from app.models.paper_chunk import PaperChunk

# numpy 可选加速：未安装时全部走纯 Python（400 片段约数秒，个人库规模可接受）
try:
    import numpy as _np
except ImportError:  # pragma: no cover
    _np = None

# ---- 参数 ----
POOL_DIM = 64        # 池化投影目标维度（JL 引理下对数百点的余弦结构保持足够）
BOW_DIM = 128        # 离线词袋伪向量维度
MAX_NODES = 400      # 图谱节点上限（超出按文献轮转采样，保证文献多样性）
KNN_K = 3            # 每个节点保留的最近邻居数
KNN_MIN_SIM = 0.15   # 低于该余弦相似度的边不画
MAX_EDGES = 1200
CANVAS = 2600        # 布局画布边长（前端 fitView 自适应）

CLUSTER_COLORS = [
    "#5B8FF9", "#5AD8A6", "#F6BD16", "#E8684A", "#6DC8EC", "#9270CA",
    "#FF9D4D", "#269A99", "#FF99C3", "#A0A6F0", "#C2C833", "#F08BB4",
]

# ---- 分词与停用词 ----
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{2,8}")
_LATIN_WORD = re.compile(r"[a-zA-Z][a-zA-Z0-9\-]{2,}")

# 中文虚词字符：长中文段的 n-gram 含这些字基本是语法碎片（「的应用」「在图」），
# 仅用于过滤 n-gram；≤4 字的自然短词（标点分隔出的，如「目的」）不受影响
_FUNC_CHARS = set("的了在和是与对被将其该此也很最则或于中")

_STOPWORDS = {
    # 英文常见停用词与论文口水词
    "the", "and", "for", "are", "not", "with", "this", "that", "from", "have",
    "has", "was", "were", "which", "their", "these", "those", "such", "than",
    "then", "them", "there", "here", "when", "what", "where", "how", "why",
    "can", "could", "would", "should", "will", "shall", "may", "might", "must",
    "into", "onto", "over", "under", "between", "among", "through", "during",
    "before", "after", "above", "below", "both", "each", "other", "more",
    "most", "some", "any", "all", "also", "very", "much", "many", "few",
    "our", "your", "its", "his", "her", "she", "him", "you", "they", "who",
    "whose", "whom", "but", "however", "therefore", "thus", "hence", "while",
    "based", "using", "used", "use", "propose", "proposed", "paper", "study",
    "research", "method", "methods", "result", "results", "conclusion",
    "introduction", "abstract", "table", "figure", "section", "et", "al",
    # 中文停用词
    "我们", "本文", "通过", "可以", "一个", "以及", "对于", "因此", "但是",
    "并且", "或者", "如果", "由于", "其中", "这些", "那些", "之间", "方面",
    "进行", "分析", "提出", "方法", "研究", "结果", "结论", "表明", "显示",
    "基于", "利用", "不同", "主要", "重要", "相关", "问题", "数据", "模型",
}


def _tokens(text: str) -> list[str]:
    """中英文轻量分词（无分词器依赖）。

    - 中文连续段 ≤4 字直接作为词（「深度学习」「量子计算」）；
      更长的段落用 2/3/4-gram 滑窗切分，并过滤含虚词的语法碎片。
    - 英文按词切分并小写化，过滤停用词。
    """
    if not text:
        return []
    toks: list[str] = []
    for m in _CJK_RUN.finditer(text):
        run = m.group()
        if len(run) <= 4:
            toks.append(run)
        else:
            for i in range(len(run) - 1):
                for n in (2, 3, 4):
                    g = run[i : i + n]
                    if len(g) == n and not any(ch in _FUNC_CHARS for ch in g):
                        toks.append(g)
    for m in _LATIN_WORD.finditer(text):
        w = m.group().lower()
        if w not in _STOPWORDS:
            toks.append(w)
    return [t for t in toks if t not in _STOPWORDS]


# ---- 向量小工具（纯 Python） ----
def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm_vec(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 1e-12 else list(v)


def _normalize_rows(vs: list[list[float]]) -> list[list[float]]:
    return [_norm_vec(v) for v in vs]


def _pool_project(vectors: list[list[float]], dim: int = POOL_DIM, seed: int = 42):
    """确定性随机池化投影：D 维 → dim 维（每维 = 随机桶内元素均值）。

    等价于固定随机 {0, 1/m} 权重矩阵的线性投影，是 JL 随机投影的廉价变体；
    纯 Python 下仅需一次 O(N·D) 扫描，此后 PCA / 聚类 / kNN 全在低维进行。

    兼容维度混用（用户更换过 Embedding 模型导致新旧向量维度不同）：
    统一零填充到最大维度——零填充不影响较短向量的余弦相似度。
    """
    if not vectors:
        return []
    # 维度不一致时零填充统一（4096 维 + 1536 维混存也能构建图谱）
    lens = {len(v) for v in vectors}
    if len(lens) > 1:
        d_max = max(lens)
        vectors = [list(v) + [0.0] * (d_max - len(v)) for v in vectors]
    D = len(vectors[0])
    if D <= dim:
        return [list(v) for v in vectors]
    if _np is not None:
        arr = _np.asarray(vectors, dtype=_np.float32)
        rng = _np.random.default_rng(seed)
        perm = rng.permutation(D)
        buckets = _np.array_split(perm, dim)
        mat = _np.stack([arr[:, b].mean(axis=1) for b in buckets], axis=1)
        return [[float(x) for x in row] for row in mat]
    rng = random.Random(seed)
    perm = list(range(D))
    rng.shuffle(perm)
    buckets = [perm[i::dim] for i in range(dim)]
    out = []
    for v in vectors:
        row = []
        for b in buckets:
            s = 0.0
            for i in b:
                s += v[i]
            row.append(s / len(b))
        out.append(row)
    return out


def _pca_2d(vs: list[list[float]]) -> list[list[float]]:
    """取前两个主成分，把向量投影到 2D（返回 [(x, y), ...]）。

    numpy：协方差矩阵特征分解；纯 Python：幂迭代 + 通缩（deflation）。
    """
    n = len(vs)
    if n == 0:
        return []
    if n == 1:
        return [[0.0, 0.0]]
    d = len(vs[0])
    if _np is not None:
        X = _np.asarray(vs, dtype=_np.float64)
        X = X - X.mean(axis=0)
        C = (X.T @ X) / (n - 1)
        _, V = _np.linalg.eigh(C)
        v1, v2 = V[:, -1], V[:, -2]
        pts = _np.stack([X @ v1, X @ v2], axis=1)
        return [[float(a), float(b)] for a, b in pts]

    mean = [sum(v[j] for v in vs) / n for j in range(d)]
    X = [[v[j] - mean[j] for j in range(d)] for v in vs]

    def x_dot_v(x: list[list[float]], v: list[float]) -> list[float]:
        # X @ v（每个样本在 v 上的投影）
        return [sum(row[j] * v[j] for j in range(d)) for row in x]

    def xt_dot_y(x: list[list[float]], y: list[float]) -> list[float]:
        # X^T @ y
        out = [0.0] * d
        for i, row in enumerate(x):
            yi = y[i]
            if yi:
                for j in range(d):
                    out[j] += yi * row[j]
        return out

    def power(x: list[list[float]]) -> list[float]:
        rng = random.Random(7)
        v = _norm_vec([rng.random() - 0.5 for _ in range(d)])
        for _ in range(48):
            nv = _norm_vec(xt_dot_y(x, x_dot_v(x, v)))
            if abs(_dot(nv, v)) > 0.999999:
                return nv
            v = nv
        return v

    v1 = power(X)
    proj1 = x_dot_v(X, v1)
    # 通缩：去掉第一主成分后再求第二主成分
    X2 = [[row[j] - p * v1[j] for j in range(d)] for row, p in zip(X, proj1)]
    v2 = power(X2)
    proj2 = x_dot_v(X2, v2)
    return [[float(a), float(b)] for a, b in zip(proj1, proj2)]


def _kmeans(vs: list[list[float]], k: int, seed: int = 7, iters: int = 25) -> list[int]:
    """球面 k-means（输入应为归一化向量；k-means++ 初始化，余弦相似度分配）。"""
    n = len(vs)
    if n == 0:
        return []
    k = max(1, min(k, n))
    if _np is not None:
        X = _np.asarray(vs, dtype=_np.float64)
        rng = _np.random.default_rng(seed)
        idx = [int(rng.integers(n))]
        while len(idx) < k:
            sims = X @ X[idx].T
            d2 = _np.clip(1.0 - sims.max(axis=1), 0.0, None)
            total = float(d2.sum())
            if total <= 1e-12:
                break
            idx.append(int(rng.choice(n, p=d2 / total)))
        C = X[idx].copy()
        labels = _np.zeros(n, dtype=int)
        for _ in range(iters):
            labels = _np.argmax(X @ C.T, axis=1)
            newC = C.copy()
            for j in range(len(C)):
                members = X[labels == j]
                if len(members):
                    m = members.mean(axis=0)
                    norm = float(_np.linalg.norm(m))
                    if norm > 1e-12:
                        newC[j] = m / norm
            if _np.allclose(newC, C, atol=1e-6):
                C = newC
                break
            C = newC
        return [int(x) for x in _np.argmax(X @ C.T, axis=1)]

    # 纯 Python
    rng = random.Random(seed)
    centroids = [list(vs[rng.randrange(n)])]
    while len(centroids) < k:
        dists = []
        for v in vs:
            best = max(_dot(v, c) for c in centroids)
            dists.append(max(0.0, 1.0 - best))
        total = sum(dists)
        if total <= 1e-12:
            break
        r = rng.random() * total
        acc = 0.0
        chosen = n - 1
        for i, dv in enumerate(dists):
            acc += dv
            if acc >= r:
                chosen = i
                break
        centroids.append(list(vs[chosen]))
    d = len(vs[0])
    labels = [0] * n
    for _ in range(iters):
        changed = False
        for i, v in enumerate(vs):
            bj, bs = 0, -2.0
            for j, c in enumerate(centroids):
                s = _dot(v, c)
                if s > bs:
                    bs, bj = s, j
            if labels[i] != bj:
                labels[i] = bj
                changed = True
        if not changed:
            break
        sums = [[0.0] * d for _ in centroids]
        cnts = [0] * len(centroids)
        for i, v in enumerate(vs):
            j = labels[i]
            cnts[j] += 1
            row = sums[j]
            for t, x in enumerate(v):
                row[t] += x
        for j in range(len(centroids)):
            if cnts[j]:
                centroids[j] = _norm_vec(sums[j])
    return labels


def _knn_edges(vs: list[list[float]], ids: list[str], k: int = KNN_K,
               min_sim: float = KNN_MIN_SIM) -> list[dict]:
    """kNN 余弦相似边：每个节点取 top-k 最近邻居，无向去重后按相似度截断。"""
    n = len(vs)
    if n < 2:
        return []
    pairs: list[tuple[int, int, float]] = []
    if _np is not None:
        X = _np.asarray(vs, dtype=_np.float64)
        S = X @ X.T
        kk = min(k, n - 1)
        for i in range(n):
            row = S[i].copy()
            row[i] = -2.0
            top = _np.argpartition(row, -kk)[-kk:]
            for j in top:
                s = float(row[j])
                if s >= min_sim:
                    pairs.append((i, int(j), s))
    else:
        for i in range(n):
            scored = []
            for j in range(n):
                if j != i:
                    scored.append((_dot(vs[i], vs[j]), j))
            scored.sort(reverse=True)
            for s, j in scored[:k]:
                if s >= min_sim:
                    pairs.append((i, j, s))
    seen: set[tuple[int, int]] = set()
    edges: list[dict] = []
    pairs.sort(key=lambda t: -t[2])  # 相似度高的边优先保留
    for i, j, s in pairs:
        key = (i, j) if i < j else (j, i)
        if key in seen:
            continue
        seen.add(key)
        edges.append({"source": ids[i], "target": ids[j], "sim": round(s, 3)})
        if len(edges) >= MAX_EDGES:
            break
    return edges


def _related_tokens(a: str, b: str) -> bool:
    """两个候选关键词是否为同一短语的碎片（择一保留）。

    - 互为子串：直接合并（「深度」「深度学」让位给「深度学习」）；
    - 均为中文时，2-gram 重叠率 ≥ 0.5 视为同源碎片
      （「理机制研」与「物理机制」重叠加 2/3，合并；「量子纠缠」与
      「量子计算」仅共享「量子」1/3，二者都保留）。
    """
    if a in b or b in a:
        return True
    if any("\u4e00" <= ch <= "\u9fff" for ch in a) and any("\u4e00" <= ch <= "\u9fff" for ch in b):
        ga = {a[i : i + 2] for i in range(len(a) - 1)}
        gb = {b[i : i + 2] for i in range(len(b) - 1)}
        if ga and gb and len(ga & gb) / min(len(ga), len(gb)) >= 0.5:
            return True
    return False


def _cluster_keywords(texts: list[str], labels: list[int], k: int, topn: int = 3) -> list[list[str]]:
    """每个簇的代表性关键词：簇内频次 / 跨簇普及度（TF-IDF 思想的简化版）。

    同频时更长的词（更具体）优先；同源碎片自动去重。
    """
    cluster_tf = [Counter() for _ in range(k)]
    for t, lab in zip(texts, labels):
        for tk in set(_tokens(t or "")):
            cluster_tf[lab][tk] += 1
    spread: Counter = Counter()
    for j in range(k):
        spread.update(cluster_tf[j].keys())
    out: list[list[str]] = []
    for j in range(k):
        # 先取出现 ≥2 次的词（噪声小）；不够再放宽到全部
        items = [(c, tk) for tk, c in cluster_tf[j].items() if c >= 2]
        if not items:
            items = [(c, tk) for tk, c in cluster_tf[j].items()]
        items.sort(key=lambda x: (-x[0] / max(1, spread[x[1]]), -len(x[1]), x[1]))
        picked: list[str] = []
        for _c, tk in items:
            if any(_related_tokens(tk, p) for p in picked):
                continue
            picked.append(tk)
            if len(picked) >= topn:
                break
        out.append(picked)
    return out


def _bow_vectors(texts: list[str], dim: int = BOW_DIM) -> list[list[float]]:
    """离线降级：哈希词袋伪向量（crc32 稳定哈希，跨进程结果一致）。"""
    vs = []
    for t in texts:
        v = [0.0] * dim
        for tk in _tokens(t or ""):
            v[zlib.crc32(tk.encode("utf-8")) % dim] += 1.0
        vs.append(v)
    return vs


def _round_robin_sample(rows: list, limit: int) -> list:
    """按文献轮转采样片段到 limit 个，避免单篇文献霸占整个图谱。"""
    if len(rows) <= limit:
        return rows
    by_paper: dict[str, list] = {}
    for c, p in rows:
        by_paper.setdefault(str(p.id), []).append((c, p))
    keys = list(by_paper.keys())
    out = []
    while len(out) < limit:
        progressed = False
        for key in keys:
            if by_paper[key]:
                out.append(by_paper[key].pop(0))
                progressed = True
                if len(out) >= limit:
                    break
        if not progressed:
            break
    return out


def _cluster_nebula_layout(
    pts: list[list[float]],
    labels: list[int],
    k: int,
    canvas: int = CANVAS,
) -> list[tuple[float, float]]:
    """簇感知布局：不同语义簇环形分开，簇内按黄金角形成“星云”。

    每个簇先取 PCA 质心，簇中心按圆形排列保证簇间间距；
    簇内节点按相对质心的方向 + 随成员数增长的半径排布，
    类似 Obsidian 中“相似内容聚成星云、不同内容留白”的效果。
    """
    n = len(pts)
    members: list[list[int]] = [[] for _ in range(k)]
    sums: list[tuple[float, float]] = [(0.0, 0.0)] * k
    for i, lab in enumerate(labels):
        members[lab].append(i)
        sx, sy = sums[lab]
        sums[lab] = (sx + pts[i][0], sy + pts[i][1])

    pca_cent = []
    for j in range(k):
        m = members[j]
        if m:
            pca_cent.append(
                (sum(pts[i][0] for i in m) / len(m), sum(pts[i][1] for i in m) / len(m))
            )
        else:
            pca_cent.append((0.0, 0.0))

    radius = min(1450, 450 + k * 85)
    cx = cy = canvas / 2
    positions: list[tuple[float, float]] = [(0.0, 0.0)] * n
    golden = 2.39996
    for j in range(k):
        ang = -math.pi / 2 + 2 * math.pi * j / max(1, k)
        ccx = cx + radius * math.cos(ang)
        ccy = cy + radius * math.sin(ang)
        m = members[j]
        for idx, i in enumerate(m):
            rel_x = pts[i][0] - pca_cent[j][0]
            rel_y = pts[i][1] - pca_cent[j][1]
            d = math.hypot(rel_x, rel_y)
            if d < 1e-9:
                a = (i * golden) % (2 * math.pi)
                spread = 0.0
            else:
                a = math.atan2(rel_y, rel_x)
                spread = min(1.0, d / 140.0)
            frac = idx / max(1, len(m))
            r = 55 + 500 * math.sqrt(frac) * (0.72 + 0.28 * spread)
            x = ccx + r * math.cos(a + idx * 0.13)
            y = ccy + r * math.sin(a + idx * 0.13)
            x += ((i * 37) % 9 - 4) * 2.2
            y += ((i * 53) % 11 - 5) * 2.2
            positions[i] = (
                min(max(x, 50), canvas - 50),
                min(max(y, 50), canvas - 50),
            )
    return positions


# 结果缓存：签名 = (片段总数, 有向量数, limit)，文献库变化自动失效
_CACHE: dict[str, tuple[tuple, dict]] = {}


def invalidate_cache(user_id=None) -> None:
    """重新解析/重新分析后清除图谱缓存，避免旧片段布局残留。"""
    if user_id is None:
        _CACHE.clear()
        return
    _CACHE.pop(str(user_id), None)


def build_smart_graph(db: Session, user_id, limit: int = MAX_NODES) -> dict:
    """构建语义聚类图谱：降维布局 + 球面 k-means 语义簇 + 关键词标签 + kNN 关联边。"""
    limit = max(20, min(int(limit or MAX_NODES), 1000))
    rows = (
        db.query(PaperChunk, Paper)
        .join(Paper, PaperChunk.paper_id == Paper.id)
        .filter(Paper.user_id == user_id)
        .all()
    )
    # 至少 3 个向量才走 embedding 模式，否则降级为关键词词袋
    # （防御：embedding 解析异常（非 list/空）的片段不参与向量模式）
    with_emb = [
        (c, p)
        for c, p in rows
        if isinstance(c.embedding, list) and len(c.embedding) > 0 and all(isinstance(x, (int, float)) for x in c.embedding[:4])
    ]
    sig = (len(rows), len(with_emb), limit)
    cached = _CACHE.get(str(user_id))
    if cached and cached[0] == sig:
        return cached[1]

    empty = {
        "ok": True, "mode": "embedding", "total_chunks": len(rows),
        "node_count": 0, "clusters": [], "nodes": [], "edges": [],
    }
    # 至少 3 个向量才走 embedding 模式，否则降级为关键词词袋
    use_embedding = len(with_emb) >= 3
    pool = with_emb if use_embedding else rows
    sampled = _round_robin_sample(pool, limit)
    if not sampled:
        return empty

    texts = [c.content or "" for c, _ in sampled]
    if use_embedding:
        raw = [c.embedding for c, _ in sampled]
        mode = "embedding"
    else:
        raw = _bow_vectors(texts)
        mode = "keyword"
    pooled = _pool_project(raw)
    normed = _normalize_rows(pooled)

    n = len(pooled)
    k = max(2, min(12, round(math.sqrt(n / 2)) or 2))
    if n < 4:
        k = 1 if n < 2 else 2
    labels = _kmeans(normed, k)
    k = (max(labels) + 1) if labels else 1

    # PCA 2D → 簇感知星云布局（簇间留白、簇内聚合）
    pts = _pca_2d(pooled)
    layout = _cluster_nebula_layout(pts, labels, k)
    nodes = []
    for i, (c, p) in enumerate(sampled):
        x, y = layout[i]
        nodes.append(
            {
                "id": str(c.id),
                "x": round(x, 1),
                "y": round(y, 1),
                "cluster": labels[i],
                "paper_id": str(p.id),
                "paper_title": p.title or "未命名",
                "dimension": c.dimension,
                "section": c.section,
                "page_number": c.page_number,
                "snippet": (c.content or "")[:90],
            }
        )

    kw_lists = _cluster_keywords(texts, labels, k)
    clusters = []
    for j in range(k):
        member_papers = {nd["paper_id"] for nd in nodes if nd["cluster"] == j}
        cnt = sum(1 for lab in labels if lab == j)
        kws = kw_lists[j] if j < len(kw_lists) else []
        clusters.append(
            {
                "id": j,
                "label": " · ".join(kws) if kws else f"簇 {j + 1}",
                "keywords": kws,
                "color": CLUSTER_COLORS[j % len(CLUSTER_COLORS)],
                "count": cnt,
                "papers": len(member_papers),
            }
        )

    edges = _knn_edges(normed, [nd["id"] for nd in nodes])

    result = {
        "ok": True,
        "mode": mode,
        "total_chunks": len(rows),
        "node_count": n,
        "clusters": clusters,
        "nodes": nodes,
        "edges": edges,
    }
    _CACHE[str(user_id)] = (sig, result)
    return result
