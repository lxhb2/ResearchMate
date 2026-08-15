"""Skill 调度层：科研意图识别与分发。

- 当用户/内部任务触发科研相关意图 → 自动匹配对应 skill 并产出科研文档；
- 非科研任务 → 返回 FEED 标记，继续走原有情报处理链路，互不干扰。
"""
from typing import Any

from research_skills import config
from research_skills.executor import run_skill
from research_skills.registry import get_registry


# 用来判定「非科研 → 走原情报链路」的强信号词。命中即视为情报/泛任务。
_FEED_STRONG = [
    "rss", "feed", "资讯", "新闻", "日报", "早报", "舆情", "摘要资讯",
    "抓取", "爬取", "feed源", "情报摘要", "导出md", "归档资讯",
]

# 科研意图弱信号（需要与 skill 触发词生命周期配合）
_RESEARCH_WEAK = [
    "文献", "综述", "论文", "研究", "实验", "假设", "选题", "idea",
    "proposal", "hypothesis", "review", "write paper", "literature",
    "实验设计", "仿写", "分析", "方法对比", "引用", "validation",
]


class Intent:
    """一次调度的判定结果。"""

    def __init__(self, kind: str, skills=None, matched: str = ""):
        self.kind = kind            # "research" | "feed"
        self.skills = skills or []  # 命中的科研 skill 列表
        self.matched_skill = matched

    def __repr__(self) -> str:  # pragma: no cover
        return f"Intent(kind={self.kind}, matched_skill={self.matched_skill})"


def classify(text: str) -> Intent:
    """对用户输入做意图分类。

    规则：
    1. 强情报信号 → feed（走原链路）；
    2. 命中科研 skill 触发词 → research（并给出匹配的 skill）；
    3. 弱科研信号 → research（默认用 research_closed_loop 编排）；
    4. 其余 → feed。
    """
    text = (text or "").strip()
    low = text.lower()

    # 1) 强情报信号
    if any(k in text or k in low for k in _FEED_STRONG):
        return Intent("feed")

    # 2) 科研 skill 触发词匹配
    registry = get_registry()
    hits = registry.match(text)
    if hits:
        return Intent("research", skills=hits, matched=hits[0]["name"])

    # 3) 弱科研信号
    if any(k in text or k in low for k in _RESEARCH_WEAK):
        return Intent("research")

    # 4) 兜底
    return Intent("feed")


def dispatch(text: str, opts: dict[str, Any] | None = None) -> dict:
    """执行一次调度：识别意图并当为科研任务时直接运行命中的 skill。

    返回形如：
      {"intent": "research", "skill": "deep-research",
       "output_file": "...", "output": "..."}
    或
      {"intent": "feed", "note": "非科研任务，走原有情报处理链路"}
    """
    opts = opts or {}
    intent = classify(text)

    if intent.kind == "feed":
        return {"intent": "feed", "note": "非科研任务，走原有情报处理链路。"}

    # 选择要执行的 skill：指定 → 命中第一个 → 默认编排器
    requested = (opts.get("skill") or "").strip()
    registry = get_registry()
    target = None
    if requested:
        target = registry.get(requested)
    if target is None and intent.skills:
        target = intent.skills[0]
    if target is None:
        target = registry.get("research-closed-loop") or registry.get("research_closed_loop")

    if target is None:
        return {"intent": "research", "error": "未找到可用科研 skill"}

    result = run_skill(target, text, opts=opts)
    result["intent"] = "research"
    result["skill"] = target["name"]
    return result