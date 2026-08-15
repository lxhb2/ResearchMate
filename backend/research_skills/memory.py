"""持久记忆：跨会话保存科研状态，不丢失中间思考。

复用 Orchestra-Research/AI-research-SKILLs 的 autoresearch 设计：
  findings.md        —— 演进的叙事性综合（找 points / 结论）
  research-log.md    —— 决策时间线
  research-state.yaml—— 中央状态跟踪（当前阶段 / 假设 / 已产出的产物）
"""
import os
from datetime import datetime, timezone

import yaml

from research_skills import config


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _paths(project_slug: str | None = None) -> dict[str, str]:
    """返回持久记忆文件路径（按项目细分，缺省用 research/ 根目录）。"""
    base = config.RESEARCH_OUTPUT_DIR
    if project_slug:
        base = os.path.join(config.RESEARCH_OUTPUT_DIR, _slug(project_slug))
    config.ensure_dirs()
    return {
        "dir": base,
        "findings": os.path.join(base, config.FINDINGS_FILE),
        "log": os.path.join(base, config.LOG_FILE),
        "state": os.path.join(base, config.STATE_FILE),
    }


def _slug(name: str) -> str:
    import re

    s = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", (name or "").strip().lower())
    return s[:40] or "research"


def load_state(project_slug: str | None = None) -> dict:
    p = _paths(project_slug)["state"]
    if not os.path.isfile(p):
        return {"phase": "init", "hypotheses": [], "artifacts": [], "updated_at": _now()}
    try:
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_state(state: dict, project_slug: str | None = None) -> str:
    p = _paths(project_slug)["state"]
    state["updated_at"] = _now()
    with open(p, "w", encoding="utf-8") as f:
        yaml.safe_dump(state, f, allow_unicode=True, sort_keys=False)
    return p


def append_log(entry: str, project_slug: str | None = None) -> str:
    """在 research-log.md 追加一条时间线记录。"""
    p = _paths(project_slug)["log"]
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"- **{_now()}** {entry}\n")
    return p


def update_findings(section: str, content: str, project_slug: str | None = None) -> str:
    """把一段综合结论并入 findings.md（按二级标题分节）。"""
    p = _paths(project_slug)["findings"]
    header = f"## {section}\n\n"
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"\n{header}{content.strip()}\n")
    return p


def record_artifact(kind: str, path: str, project_slug: str | None = None) -> dict:
    """把一个科研产物登记进 research-state.yaml。"""
    state = load_state(project_slug)
    artifacts = state.setdefault("artifacts", [])
    artifacts.append({"kind": kind, "path": path, "at": _now()})
    return {"state": save_state(state, project_slug), "path": path}