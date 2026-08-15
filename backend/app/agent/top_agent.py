"""顶层 Agent：对话入口的意图路由（轻量，不做重 orchestrator）。

职责：
1. 科研 skill 命中（强触发词）→ 调用 research_skills 执行，产物落盘 output/research/
2. 命中专用 Agent 意图（RAG / 数据 / 实验 / 写作）→ 调用对应专用 Agent
3. 兜底 → 返回 None，由调用方走原有对话链路

返回统一结构：
  {"path": "skill"|"rag"|"data"|"experiment"|"writing"|"chat",
   "answer": str, "route_label": str, "artifact_path": str|None}
"""
from typing import Any

from app.agent.llm_adapter import LLMAdapter
from app.agent.specialized import build_agent, intents_for
from app.agent.tools import ToolContext
from app.services import settings_service


class TopAgent:
    """对话顶层路由。"""

    def __init__(self, db, user_id, llm: LLMAdapter | None = None, mock: bool = False):
        self.ctx = ToolContext(db=db, user_id=str(user_id), llm=llm, mock=mock)

    # ---- 对外主入口 ----

    def route(self, text: str) -> dict:
        """返回路由结果；path == 'chat' 表示走原对话。"""
        # 1. 科研 skill 强命中
        skill = self._match_skill(text)
        if skill:
            return {"path": "skill", "skill": skill}

        # 2. 专用 Agent
        agent_cls = intents_for(text)
        if agent_cls:
            return {"path": agent_cls.name, "agent": agent_cls}

        # 3. 兜底
        return {"path": "chat"}

    def execute(self, text: str) -> dict | None:
        """执行路由；path == 'chat' 时返回 None，由调用方走原对话。"""
        r = self.route(text)
        if r["path"] == "chat":
            return {"path": "chat"}
        if r["path"] == "skill":
            return self._run_skill(r["skill"], text)
        # 专用 Agent：handle 异常时返回错误文本，不回退成普通对话
        agent_cls = r.get("agent")
        try:
            agent = build_agent(r["path"], self.ctx)
            out = agent.handle(text)
        except Exception as exc:  # noqa: BLE001
            out = {"answer": f"{getattr(agent_cls, 'label', r['path'])}执行失败：{exc}"}
        out["path"] = r["path"]
        out["route_label"] = out.get("route_label", agent_cls.label if agent_cls else r["path"])
        return out

    # ---- 内部实现 ----

    def _match_skill(self, text: str) -> dict | None:
        """科研 skill 触发词匹配（复用 research_skills 注册表）。"""
        try:
            from research_skills.registry import get_registry

            hits = get_registry().match(text)
            if hits:
                return hits[0]
        except Exception:  # noqa: BLE001
            pass
        return None

    def _skill_client(self):
        """按 app 的 LLM 配置构造 research_skills 的 LLMClient（保持一致）。"""
        from research_skills.llm import LLMClient

        try:
            cfg = settings_service.get_llm_config(self.ctx.db, self.ctx.user_id)
        except Exception:  # noqa: BLE001
            return LLMClient(provider="mock")
        base = (cfg.get("base_url") or "").strip()
        api_key = (cfg.get("api_key") or "").strip()
        model = (cfg.get("model") or "gpt-4o").strip()
        if "ollama" in base.lower():
            return LLMClient(provider="ollama", model=model, base_url=base)
        if not api_key or "placeholder" in api_key.lower() or api_key in ("sk-xxx", "sk-placeholder"):
            return LLMClient(provider="mock")
        return LLMClient(provider="openai", model=model, base_url=base, api_key=api_key)

    def _run_skill(self, skill: dict, text: str) -> dict:
        """执行 skill，产物落盘 output/research/ 并返回路径。"""
        from research_skills.executor import run_skill

        try:
            result = run_skill(skill, text, opts={}, client=self._skill_client())
            return {
                "path": "skill",
                "answer": result.get("output", ""),
                "route_label": f"科研Skill·{skill.get('name','')}",
                "artifact_path": result.get("output_file"),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "path": "skill",
                "answer": f"Skill「{skill.get('name','')}」执行失败：{exc}",
                "route_label": f"科研Skill·{skill.get('name','')}",
            }


def top_route(db, user_id, text: str, llm: LLMAdapter | None = None, mock: bool = False) -> dict:
    """便捷入口：构造顶层 Agent 并执行路由。"""
    return TopAgent(db, user_id, llm=llm, mock=mock).execute(text)