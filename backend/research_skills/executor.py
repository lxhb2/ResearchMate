"""Skill 执行器：把 skill 定义 + 用户输入 → LLM 调用 → Markdown 产物。

产物统一写入 ./output/research/（与情报 ./output/feed/ 隔离），并登记进
持久记忆（findings.md / research-log.md / research-state.yaml）。
"""
import os
from datetime import datetime, timezone

from research_skills import config, memory
from research_skills.llm import LLMClient


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def build_prompt(skill: dict, user_text: str) -> tuple[str, str]:
    """构造 (system, user) 提示词。

    system 由 skill 的 prompt_template（系统提示/工作流）构成，并注入
    skill 名称、约束规则；user 为原始科研指令。
    """
    template = (skill.get("prompt_template") or "").strip()
    constraints = (skill.get("constraints") or "").strip()

    system = f"SKILL: {skill.get('name','')}\n"
    system += f"你正在执行科研 Skill「{skill.get('name','')}」。\n"
    if skill.get("description"):
        system += f"目标：{skill.get('description','')}\n"
    if template:
        system += "--- 方法/工作流 ---\n" + template + "\n"
    if constraints:
        system += "--- 约束规则 ---\n" + constraints + "\n"
    system += "\n请针对用户的科研指令，输出规范的 Markdown 科研文档作为最终产物。"

    user = user_text.strip()
    return system, user


def run_skill(
    skill: dict,
    user_text: str,
    opts: dict | None = None,
    client: LLMClient | None = None,
) -> dict:
    """执行单个 skill，返回产物信息。"""
    opts = opts or {}
    project = (opts.get("project") or "").strip() or None
    client = client or LLMClient()

    system, user = build_prompt(skill, user_text)
    try:
        content = client.chat(system, user)
    except Exception as exc:  # noqa: BLE001
        content = (
            f"# {skill.get('name','')} 执行失败\n\n"
            f"**错误**：{exc}\n\n"
            f"**原始指令**：{user_text}\n\n"
            f"提示：请检查 LLM 配置，或改用离线模式（RESEARCH_LLM_PROVIDER=mock）。"
        )

    # 统一写到 ./output/research/
    config.ensure_dirs()
    sub = project or skill.get("name", "research")
    out_dir = os.path.join(config.RESEARCH_OUTPUT_DIR, _slug(sub))
    os.makedirs(out_dir, exist_ok=True)
    fname = f"{_now()}-{skill.get('name','skill')}.md"
    out_path = os.path.join(out_dir, fname)

    document = _wrap_document(skill, user_text, content)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(document)

    # 持久记忆
    memory.update_findings(skill.get("name", "research"), content, project)
    memory.append_log(f"执行 Skill「{skill.get('name','')}」→ {out_path}", project)
    memory.record_artifact(skill.get("name", "research"), out_path, project)

    return {
        "status": "ok",
        "skill": skill.get("name"),
        "category": skill.get("category"),
        "output_file": out_path,
        "output": content,
    }


def _slug(name: str) -> str:
    import re

    s = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", name.strip().lower())
    return s[:40] or "research"


def _wrap_document(skill: dict, user_text: str, content: str) -> str:
    """给产物加一个包含元信息的文件头。"""
    header = [
        "---",
        f"skill: {skill.get('name','')}",
        f"category: {skill.get('category','')}",
        f"github_source: {skill.get('github_source','')}",
        f"generated_at: {_now()}",
        "---",
        "",
        f"> 科研指令：{user_text.strip()}",
        "",
        "---",
        "",
    ]
    return "\n".join(header) + content.strip() + "\n"