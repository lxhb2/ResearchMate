"""长期记忆系统：基于本地 Markdown 文件，跨对话共享。

设计目标（对应产品需求）：
- 以本地 md 文档协助记忆：profile.md（用户画像/偏好）、knowledge.md（知识沉淀）、
  notes.md（笔记/想法）、events.md（交互日志，用于机器学习适应用户习惯）。
- 多个对话框调用同一个记忆文件夹里的全部文件：记忆按 user_id 隔离，
  但同一用户的所有会话共享同一目录，任何会话写入的记忆其他会话立即可见。
- 长期上下文：每次对话前把记忆内容注入系统提示词，让 Agent 记住用户偏好与历史。

目录结构：<storage>/agent/memory/<user_id>/
"""
import os
import re
import time
from datetime import datetime
from typing import Any, Optional

from app.config import settings as app_settings

# 默认记忆文件名 -> 标题（前端展示用）
MEMORY_FILES: dict[str, str] = {
    "profile.md": "用户画像",
    "knowledge.md": "知识沉淀",
    "notes.md": "笔记想法",
    "events.md": "交互日志",
}


def _root() -> str:
    return os.path.join(app_settings.STORAGE_DIR, "agent", "memory")


def memory_dir(user_id: str) -> str:
    d = os.path.join(_root(), str(user_id))
    os.makedirs(d, exist_ok=True)
    return d


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---- 读取 ----

def list_memories(user_id: str) -> list[dict]:
    """列出该用户的全部记忆文件（含元信息与摘要）。"""
    d = memory_dir(user_id)
    items: list[dict] = []
    for name in sorted(os.listdir(d)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(d, name)
        try:
            stat = os.stat(path)
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except OSError:
            continue
        items.append(
            {
                "name": name,
                "title": MEMORY_FILES.get(name, name),
                "size": stat.st_size,
                "updated_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "excerpt": content.strip().replace("\n", " ")[:120],
            }
        )
    return items


def _safe_name(name: str) -> str:
    """清洗记忆文件名：仅保留 basename，防止路径穿越，并确保 .md 后缀。"""
    name = os.path.basename(name)
    if not name.endswith(".md"):
        name = name + ".md"
    return name


def read_memory(user_id: str, name: str) -> str:
    """读取单个记忆文件内容；文件不存在返回空字符串。"""
    name = _safe_name(name)
    path = os.path.join(memory_dir(user_id), name)
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_all(user_id: str, max_chars: int = 6000) -> str:
    """读取记忆目录下的全部 md 文件，合并成一段上下文文本。"""
    parts: list[str] = []
    total = 0
    for name in sorted(os.listdir(memory_dir(user_id))):
        if not name.endswith(".md"):
            continue
        try:
            with open(os.path.join(memory_dir(user_id), name), encoding="utf-8") as f:
                content = f.read().strip()
        except OSError:
            continue
        if not content:
            continue
        title = MEMORY_FILES.get(name, name)
        block = f"### {title}（{name}）\n{content}"
        if total + len(block) > max_chars:
            # 超限时截断该文件
            remain = max_chars - total
            if remain > 200:
                parts.append(block[:remain] + "\n…(已截断)")
            break
        parts.append(block)
        total += len(block)
    if not parts:
        return ""
    return "===== 长期记忆（跨对话共享） =====\n" + "\n\n".join(parts)


# ---- 写入 ----

def write_memory(user_id: str, name: str, content: str, append: bool = False) -> dict:
    """写入（或追加）记忆文件，返回 {name, updated_at, size}。"""
    name = _safe_name(name)
    path = os.path.join(memory_dir(user_id), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "a" if append else "w"
    with open(path, mode, encoding="utf-8") as f:
        if append:
            f.write(f"\n\n---\n\n## {_ts()}\n\n{content.strip()}\n")
        else:
            f.write(f"# {MEMORY_FILES.get(name, name)}\n\n> 最后更新：{_ts()}\n\n{content.strip()}\n")
    stat = os.stat(path)
    return {"name": name, "updated_at": _ts(), "size": stat.st_size}


def record_event(user_id: str, text: str) -> None:
    """向 events.md 追加一条交互记录（用于学习用户习惯）。"""
    try:
        write_memory(user_id, "events.md", text, append=True)
    except OSError:
        pass


# ---- 检索 ----

def search(user_id: str, query: str, top_k: int = 5) -> list[dict]:
    """在全部记忆文件中做关键词检索，返回命中的 {file, content, score}。"""
    tokens = [t for t in re.findall(r"[\w\u4e00-\u9fff]+", (query or "").lower()) if len(t) > 1]
    if not tokens:
        return []
    d = memory_dir(user_id)
    results: list[dict] = []
    for name in sorted(os.listdir(d)):
        if not name.endswith(".md"):
            continue
        try:
            with open(os.path.join(d, name), encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            low = line.lower()
            score = sum(1 for t in tokens if t in low)
            if score == 0:
                continue
            results.append(
                {
                    "file": name,
                    "title": MEMORY_FILES.get(name, name),
                    "content": line.strip()[:300],
                    "line": i + 1,
                    "score": score,
                }
            )
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]


def memory_prompt(user_id: str, max_chars: int = 4000) -> str:
    """生成注入系统提示词的记忆片段（无记忆时返回空串）。"""
    context = load_all(user_id, max_chars=max_chars)
    if not context:
        return ""
    return (
        "下面是助手长期记住的、关于用户偏好的信息（跨对话共享，来自本地 md 记忆文件）。"
        "回答时应尽量贴合用户的习惯与历史偏好：\n" + context
    )


def ensure_exists(user_id: str) -> list[str]:
    """确保默认记忆文件存在，返回已存在的文件名列表。"""
    d = memory_dir(user_id)
    created: list[str] = []
    for name in MEMORY_FILES:
        if not os.path.isfile(os.path.join(d, name)):
            try:
                write_memory(user_id, name, f"（暂无记录，使用对话后可自动沉淀于此）")
                created.append(name)
            except OSError:
                pass
    return created
