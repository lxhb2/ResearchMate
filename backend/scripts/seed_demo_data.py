"""为 Q1-1 / Q1-2 试用注入演示数据（幂等：已存在则跳过）。

- 为已入库文献补齐作者/年份元数据，并基于 full_text 生成带页码的真实片段（chunk）。
- 补充若干「卡片笔记」标注（comment 非空），用于验证 Reader 卡片面板/拖拽/双向跳转。

用法：cd backend && ./.venv/bin/python -m scripts.seed_demo_data
"""
import re

from app.database import SessionLocal
from app.models.annotation import Annotation
from app.models.paper import Paper
from app.models.paper_chunk import PaperChunk

db = SessionLocal()
try:
    papers = db.query(Paper).filter(Paper.status == "ready").all()
    if not papers:
        print("库中无 ready 文献，跳过")
    for p in papers:
        # ---- 1) 补齐作者/年份元数据（来自标题中的作者名，年份保持 n.d.）----
        if not p.authors and p.title:
            m = re.search(r"[_【（(]?([\u4e00-\u9fff·]{2,4})[_】）)]?$", p.title.split("_")[-1])
            if m:
                p.authors = [m.group(1)]
                print(f"  [meta] 设置作者 {p.authors} <- {p.title[-20:]}")

        # ---- 2) 基于 full_text 生成片段（真实内容 + 页码）----
        existing = db.query(PaperChunk).filter(PaperChunk.paper_id == p.id).count()
        ft = p.full_text or ""
        if existing == 0 and len(ft) > 200:
            # 按段落切分，合并成 ~600 字一组的片段
            paras = [x.strip() for x in re.split(r"\n\s*\n|\n", ft) if len(x.strip()) > 30]
            chunks: list[str] = []
            buf = ""
            for para in paras:
                if len(buf) + len(para) > 600 and buf:
                    chunks.append(buf)
                    buf = ""
                buf += para
            if buf:
                chunks.append(buf)
            n_pages = max(1, (len(ft) // 1500) + 1)  # 粗略估算页数
            for i, text in enumerate(chunks[:40]):
                page = min(n_pages, (i * n_pages) // len(chunks) + 1)
                db.add(
                    PaperChunk(
                        paper_id=p.id,
                        dimension="method",
                        content=text,
                        embedding=None,
                        page_number=page,
                    )
                )
            db.commit()
            print(f"  [chunks] 为「{p.title[:20]}…」注入 {len(chunks[:40])} 个片段（约 {n_pages} 页）")

        # ---- 3) 补充卡片笔记标注（Q1-1 演示；不足 3 张时补齐）----
        existing_pins = (
            db.query(Annotation)
            .filter(Annotation.paper_id == p.id, Annotation.comment.isnot(None))
            .count()
        )
        notes = [
            (1, "浮选机理核心：硫脲类捕收剂 CPTU 通过 S 原子与矿物表面金属离子成键，形成疏水膜。", "CPTU 以硫原子与铜、铁离子发生络合吸附，是浮选疏水化的关键。"),
            (3, "高碱条件下 CPTU 仍能保持黄铜矿的优先可浮性，说明其选择性来源于对黄铁矿的弱作用。", "高碱下黄铜矿自身氧化受抑，CPTU 的选择性差异主要来自黄铁矿表面。"),
            (5, "电化学机理：捕收剂在矿物表面发生氧化还原反应，产物决定疏水性强弱。", "阳极氧化产物（双黄药类）增强疏水性，阴极过程消耗氧，抑制氧化。"),
        ]
        for page, snippet, note in notes[existing_pins:]:
            db.add(
                Annotation(
                    user_id=p.user_id,
                    paper_id=p.id,
                    type="highlight",
                    content=snippet,
                    comment=note,
                    page_number=page,
                    position={
                        "rects": [
                            {"x": 0.1 + 0.05 * i, "y": 0.2 + 0.1 * i, "w": 0.7, "h": 0.03}
                            for i in range(page)
                        ],
                        "color": ["#ffe58f", "#b7eb8f", "#91caff"][page % 3],
                        "cardOrder": page - 1,
                    },
                )
            )
        if len(notes) > existing_pins:
            db.commit()
            print(f"  [pins] 为「{p.title[:20]}…」补充 {len(notes) - existing_pins} 张卡片笔记")
    db.commit()
    print("演示数据就绪 ✓")
finally:
    db.close()
