"""Supervisor 评审后置模块（基于 HKUSTDial/Supervisor-Skills 的理念）。

任何科研产物完成后，可被调用做缺陷诊断、可行性评估、风险提示，
贴合风险控制思维。作为「可选」阶段，不阻塞主流程。
"""
import json
import os

from research_skills import config, memory
from research_skills.llm import LLMClient

REVIEW_DIMENSIONS = [
    "缺陷诊断（逻辑漏洞 / 证据缺口 / 引用可信度）",
    "可行性评估（数据可得性 / 成本 / 时间 / 技术门槛）",
    "风险提示（与结论相悖的证据 / 伦理合规 / 统计效力）",
]


def review(
    content: str,
    topic: str = "",
    opts: dict | None = None,
    client: LLMClient | None = None,
) -> dict:
    """对一段科研内容做评审，返回结构化评审意见。

    content 可以是字符串，也可以是 {output_file, output} 形式的执行结果。
    """
    opts = opts or {}
    project = (opts.get("project") or "").strip() or None

    if isinstance(content, dict):
        content = content.get("output") or read_file(content.get("output_file"))
    content = (content or "").strip()

    client = client or LLMClient()
    system = (
        "SKILL: supervisor\n"
        "你是一名严谨的科研评审专家（Supervisor）。请对下述科研产出做系统化评审，"
        "覆盖：缺陷诊断、可行性评估、风险提示。逐条给出结论，并标注严重程度 "
        "(高/中/低) 与可执行建议。输出规范的 Markdown。\n"
        f"评审维度：\n- " + "\n- ".join(REVIEW_DIMENSIONS)
    )
    user = f"科研主题：{topic or '（未提供）'}\n\n--- 待评审产出 ---\n\n{content[:12000]}"

    try:
        body = client.chat(system, user)
    except Exception as exc:  # noqa: BLE001
        body = f"# 评审意见（降级）\n\n评审失败：{exc}\n\n请在配置 LLM 后重试。"

    # 产物落盘到 output/research/_review/
    config.ensure_dirs()
    out_dir = os.path.join(config.RESEARCH_OUTPUT_DIR, "_review")
    os.makedirs(out_dir, exist_ok=True)
    from datetime import datetime, timezone

    fname = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-supervisor.md"
    out_path = os.path.join(out_dir, fname)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# Supervisor 评审\n\n> 主题：{topic}\n\n---\n\n" + body.strip() + "\n")

    memory.append_log(f"Supervisor 评审 → {out_path}", project)
    memory.record_artifact("supervisor-review", out_path, project)

    return {"status": "ok", "output_file": out_path, "output": body}


def review_result(result: dict, opts: dict | None = None) -> dict:
    """便捷入口：直接对一次 `dispatch`/`run_skill` 的结果进行评审。"""
    return review(result, opts=opts)


def list_reviews() -> list[str]:
    """列出已生成的评审产物。"""
    out_dir = os.path.join(config.RESEARCH_OUTPUT_DIR, "_review")
    if not os.path.isdir(out_dir):
        return []
    return sorted(
        os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.endswith(".md")
    )


def read_file(path: str) -> str:
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return ""