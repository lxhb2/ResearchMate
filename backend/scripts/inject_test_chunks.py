"""向运行中的库注入带 embedding 的合成片段（验证 Smart Graph embedding 模式）。"""
import math
import random

from app.database import SessionLocal
from app.models.paper import Paper
from app.models.paper_chunk import PaperChunk

rng = random.Random(42)
D = 64  # 维度无需等于真实 embedding 维度，图谱管线对维度自适应

THEMES = {
    "transformer": ("Transformer 注意力机制在语言模型中的应用", "attention transformer language model self-attention mechanism"),
    "quantum": ("量子计算与量子纠错的物理机制研究", "quantum computing error correction qubit entanglement physics"),
    "vision": ("卷积神经网络在图像识别与目标检测中的应用", "convolutional neural network image recognition object detection CNN"),
}

db = SessionLocal()
user = db.query(Paper).first()
if not user:
    print("库中无用户文献，先跳过")
else:
    uid = user.user_id
    n = 0
    for theme, (title_zh, words_en) in THEMES.items():
        p = db.query(Paper).filter(Paper.user_id == uid, Paper.title == title_zh).first()
        if not p:
            p = Paper(user_id=uid, title=title_zh, source="upload", status="ready", analysis_status="done")
            db.add(p)
            db.commit()
            db.refresh(p)
        # 主题中心向量 + 噪声 → 同主题片段自然聚成一簇
        center = [rng.gauss(0, 1) if i % 3 == list(THEMES).index(theme) else rng.gauss(0, 0.1) for i in range(D)]
        for k in range(8):
            content = f"{title_zh}（第 {k+1} 部分）：{words_en}。关键实验 {k+1} 表明该 {theme} 方法显著优于基线。"
            vec = [c + rng.gauss(0, 0.15) for c in center]
            db.add(PaperChunk(paper_id=p.id, dimension="method", content=content, embedding=vec, page_number=k + 1))
            n += 1
    db.commit()
    print(f"已注入 {n} 个带向量的片段（3 主题 × 8 片段）")
db.close()
