"""Smart Graph 数学核心验收测试（无第三方依赖，stub 掉 sqlalchemy/app.model 导入）。

覆盖：池化投影、PCA 2D、球面 k-means（合成三簇应被正确分开）、
kNN 边（簇内为主）、簇关键词（中英文）、词袋离线降级、轮转采样。
"""
import importlib.util
import random
import sys
import types

# ---- stub 掉 graph_service 顶部的 sqlalchemy / app 模型导入（沙盒未装依赖）----
_sa = types.ModuleType("sqlalchemy")
_sa_orm = types.ModuleType("sqlalchemy.orm")
_sa_orm.Session = object
_sa.orm = _sa_orm
sys.modules.setdefault("sqlalchemy", _sa)
sys.modules.setdefault("sqlalchemy.orm", _sa_orm)

app_mod = types.ModuleType("app")
models_mod = types.ModuleType("app.models")
paper_mod = types.ModuleType("app.models.paper")
chunk_mod = types.ModuleType("app.models.paper_chunk")
paper_mod.Paper = type("Paper", (), {"id": None, "user_id": None})
chunk_mod.PaperChunk = type("PaperChunk", (), {"paper_id": None})
app_mod.models = models_mod
models_mod.paper = paper_mod
models_mod.paper_chunk = chunk_mod
sys.modules.setdefault("app", app_mod)
sys.modules.setdefault("app.models", models_mod)
sys.modules.setdefault("app.models.paper", paper_mod)
sys.modules.setdefault("app.models.paper_chunk", chunk_mod)

spec = importlib.util.spec_from_file_location("graph_service", "app/services/graph_service.py")
gs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gs)

rng = random.Random(123)
D = 1536

def make_group(center, n, noise=0.25):
    out = []
    for _ in range(n):
        v = [c + rng.gauss(0, noise) for c in center]
        out.append(v)
    return out

# 三个语义方向迥异的簇（维度正交区域 + 不同符号模式）
c1 = [1.5 if i % 3 == 0 else -0.3 for i in range(D)]
c2 = [-1.2 if i % 3 == 1 else 0.4 for i in range(D)]
c3 = [1.0 if i % 3 == 2 else -0.2 for i in range(D)]
vecs = make_group(c1, 50) + make_group(c2, 50) + make_group(c3, 50)
truth = [0] * 50 + [1] * 50 + [2] * 50

# 1) 池化投影 + 归一化 + k-means：三簇应被正确分开（聚类纯度 = 1.0）
pooled = gs._pool_project(vecs)
assert all(len(v) == gs.POOL_DIM for v in pooled), "池化维度错误"
normed = gs._normalize_rows(pooled)
labels = gs._kmeans(normed, 3)
assert len(labels) == 150

def purity(labels, truth, k=3):
    from collections import Counter
    total = 0
    for j in range(k):
        members = [t for l, t in zip(labels, truth) if l == j]
        total += Counter(members).most_common(1)[0][1] if members else 0
    return total / len(truth)

p = purity(labels, truth)
print(f"[1] k-means 聚类纯度: {p:.3f}")
assert p >= 0.98, f"聚类纯度过低: {p}"

# 2) PCA 2D：坐标有限且非退化（方差 > 0）
pts = gs._pca_2d(pooled)
assert len(pts) == 150 and all(len(pt) == 2 for pt in pts)
xs = [pt[0] for pt in pts]
var = sum((x - sum(xs) / len(xs)) ** 2 for x in xs) / len(xs)
print(f"[2] PCA 2D x 方差: {var:.2f}（>0 即非退化）")
assert var > 0.01

# 3) kNN 边：簇内边应显著多于跨簇边
ids = [f"n{i}" for i in range(150)]
edges = gs._knn_edges(normed, ids)
assert 0 < len(edges) <= gs.MAX_EDGES
within = sum(1 for e in edges if truth[int(e["source"][1:])] == truth[int(e["target"][1:])])
print(f"[3] kNN 边 {len(edges)} 条，簇内占比 {within / len(edges):.1%}")
assert within / len(edges) >= 0.85, "跨簇边过多，kNN 失真"

# 4) 簇关键词：中英文混合文本应提取出簇特征词
texts_zh = ["深度学习在图像识别中的应用与卷积神经网络"] * 20 + ["量子计算与量子纠缠的物理机制研究"] * 20
kw = gs._cluster_keywords(texts_zh, [0] * 20 + [1] * 20, 2)
print(f"[4] 中文簇关键词: {kw}")
flat = " ".join(kw[0]) + " ".join(kw[1])
assert ("学习" in flat or "深度" in flat or "图像" in flat) and ("量子" in flat), flat

texts_en = ["transformer attention mechanism for language model"] * 20 + ["reinforcement learning policy gradient agent"] * 20
kw_en = gs._cluster_keywords(texts_en, [0] * 20 + [1] * 20, 2)
print(f"[4] 英文簇关键词: {kw_en}")
flat_en = " ".join(kw_en[0]) + " ".join(kw_en[1])
assert "transformer" in flat_en and "reinforcement" in flat_en

# 5) 词袋离线降级：仅凭关键词也应把两类文本分开
bow = gs._bow_vectors(["卷积神经网络 图像分类 卷积"] * 15 + ["量子纠缠 量子比特 量子"] * 15)
bl = gs._kmeans(gs._normalize_rows(gs._pool_project(bow)), 2)
bp = purity(bl, [0] * 15 + [1] * 15, 2)
print(f"[5] 离线词袋聚类纯度: {bp:.3f}")
assert bp >= 0.95

# 6) 轮转采样：文献均衡（每篇交替取样，单篇不霸占）
class FakePaper:
    def __init__(self, i): self.id = f"p{i}"
class FakeChunk:
    def __init__(self, i): self.id = f"c{i}"
rows = [(FakeChunk(i), FakePaper(i % 5)) for i in range(100)]
sampled = gs._round_robin_sample(rows, 25)
papers_in = {str(p.id) for _, p in sampled}
print(f"[6] 轮转采样 25/100，覆盖文献数: {len(papers_in)}/5")
assert len(sampled) == 25 and len(papers_in) == 5

# 7) 边界情况：单向量 / 空输入 / k>n
assert gs._pca_2d([list(c1)]) == [[0.0, 0.0]]
assert gs._pca_2d([]) == []
assert gs._kmeans([], 3) == []
assert gs._kmeans(normed[:2], 5) in ([0, 0], [0, 1], [1, 0])
assert gs._knn_edges([], []) == []
print("[7] 边界情况通过")

# 8) 确定性：同输入两次计算结果完全一致（缓存/复现友好）
assert gs._kmeans(normed, 3, seed=7) == gs._kmeans(normed, 3, seed=7)
assert gs._pool_project(vecs[:10]) == gs._pool_project(vecs[:10])
print("[8] 确定性通过")

# 9) 端到端管线：build_smart_graph 全流程（embedding 模式 + 缓存命中 + 结构校验）
class FakeQuery:
    def __init__(self, rows): self.rows = rows
    def join(self, *a, **k): return self
    def filter(self, *a, **k): return self
    def all(self): return self.rows

class FakeDB:
    def __init__(self, rows): self._q = FakeQuery(rows)
    def query(self, *a, **k): return self._q

class FakePaper:
    def __init__(self, i): self.id, self.title = f"paper-{i}", f"论文{i}"

class FakeChunk:
    def __init__(self, i, vec, dim="method", page=3):
        self.id, self.content, self.embedding = f"chunk-{i}", f"研究内容片段 {i}，关于深度学习与图像识别。", vec
        self.dimension, self.page_number = dim, page

rows = [(FakeChunk(i, vecs[i]), FakePaper(i % 4)) for i in range(150)]
db = FakeDB(rows)
g = gs.build_smart_graph(db, "user-1")
assert g["ok"] and g["mode"] == "embedding" and g["node_count"] == 150
assert len(g["clusters"]) >= 2
node_ids = {n["id"] for n in g["nodes"]}
for n in g["nodes"]:
    assert 60 <= n["x"] <= 940 and 60 <= n["y"] <= 940, f"画布坐标越界: {n['x']},{n['y']}"
    assert 0 <= n["cluster"] < len(g["clusters"]) and n["paper_id"].startswith("paper-")
    assert n["snippet"]
for e in g["edges"]:
    assert e["source"] in node_ids and e["target"] in node_ids
for c in g["clusters"]:
    assert c["count"] > 0 and c["color"].startswith("#") and c["papers"] >= 1
    assert c["label"], "簇标签为空"
print(f"[9] 端到端管线：{g['node_count']} 节点 / {len(g['clusters'])} 簇 / {len(g['edges'])} 边")
print(f"    簇标签示例: {[c['label'] for c in g['clusters'][:3]]}")

# 缓存命中：同签名第二次调用直接返回缓存（对象同一）
g2 = gs.build_smart_graph(db, "user-1")
assert g2 is g, "缓存未命中"
# 文库变化（新增片段）→ 签名变化 → 自动重建
rows.append((FakeChunk(999, vecs[0]), FakePaper(9)))
g3 = gs.build_smart_graph(FakeDB(rows), "user-1")
assert g3 is not g and g3["total_chunks"] == 151
print("[9] 缓存：命中与失效均正常")

# 10) 离线降级：全部无向量 → keyword 模式，图谱仍可用
rows_k = [(FakeChunk(i, None), FakePaper(i % 3)) for i in range(30)]
gk = gs.build_smart_graph(FakeDB(rows_k), "user-2")
assert gk["ok"] and gk["mode"] == "keyword" and gk["node_count"] == 30 and gk["clusters"]
print(f"[10] 离线降级：keyword 模式，{len(gk['clusters'])} 簇")

# 11) 空库 / 少量向量边界
g_empty = gs.build_smart_graph(FakeDB([]), "user-3")
assert g_empty["node_count"] == 0 and g_empty["ok"]
g_few = gs.build_smart_graph(FakeDB([(FakeChunk(0, vecs[0]), FakePaper(0))]), "user-4")
assert g_few["node_count"] == 1
print("[11] 空库与单片段边界通过")

# 12) 维度混用（用户换过 Embedding 模型：4096 维旧向量 + 64 维新向量混存）
mixed = []
for i in range(60):
    base = vecs[i][:64]  # 64 维新模型
    mixed.append(base if i % 2 else base + [0.01] * 1472)  # 旧数据是 1536 维
pm = gs._pool_project(mixed)
assert len(pm) == 60 and all(len(v) == gs.POOL_DIM for v in pm), "维度混用池化失败"
# 池化前先归一维度，不抛 IndexError 即为修复
mm = gs._kmeans(gs._normalize_rows(pm), 3)
assert len(mm) == 60
print("[12] 维度混用（64 维 + 1536 维）通过，不再 IndexError")

# 13) 异常 embedding 防御（存成字符串/None 的脏数据不参与向量模式）
class DirtyChunk(FakeChunk):
    def __init__(self, i, vec):
        super().__init__(i, vec)
        if i == 0:
            self.embedding = "not-a-vector"  # 脏数据
        elif i == 1:
            self.embedding = []
        elif i == 2:
            self.embedding = None
rows_dirty = [(DirtyChunk(i, vecs[i]), FakePaper(i % 2)) for i in range(10)]
gd = gs.build_smart_graph(FakeDB(rows_dirty), "user-5")
assert gd["ok"] and gd["mode"] == "embedding" and gd["node_count"] == 7  # 10 - 3 条脏数据
print("[13] 脏 embedding 防御通过（10 条中 3 条脏数据被过滤）")

print("\n=== Smart Graph 数学核心验收：全部通过 ===")
