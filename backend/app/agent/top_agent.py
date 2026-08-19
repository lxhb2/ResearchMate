"""顶层 Agent：全局权限 + 智能推荐 + 工具调用 + 长期记忆。

架构（借鉴主流 Agent 项目：LLM 驱动的工具调用循环）：
1. 科研 skill 强命中 → 调用 research_skills 执行，产物落盘 output/research/
2. 命中专用 Agent 意图（RAG / 数据 / 实验 / 写作）→ 调用对应专用 Agent
3. 兜底 → 全局 Agent：注入长期记忆 + 工具目录，由 LLM 决定调用工具
   （联网搜索 / API 一键配置 / 文件读写 / 记忆读写 / 模块导航 / 系统概览），
   也可直接回答。全部模块均可访问（全局权限）。

返回统一结构：
  {"path": "skill"|"rag"|"data"|"experiment"|"writing"|"chat",
   "answer": str, "route_label": str, "artifact_path": str|None,
   "recommendation": dict|None, "tool_trace": list|None}
"""
import json
from typing import Any, Optional

from app.agent.llm_adapter import LLMAdapter
from app.agent.specialized import build_agent, intents_for
from app.agent.tools import ToolContext, get_tool, tool_descriptions
from app.agent import memory as memory_mod
from app.agent import modules as modules_mod
from app.services import settings_service


class TopAgent:
    """对话顶层路由 + 全局权限 Agent。"""

    def __init__(self, db, user_id, llm: LLMAdapter | None = None, mock: bool = False):
        self.user_id = str(user_id)
        self.ctx = ToolContext(db=db, user_id=self.user_id, llm=llm, mock=mock)

    # ------------------------------------------------------------------
    # 对外主入口
    # ------------------------------------------------------------------

    def recommend(self, text: str) -> dict:
        """智能推荐：识别功能意图，返回 {matched, module, reason, steps}。"""
        return modules_mod.recommend(text)

    def route(self, text: str, web_search: bool = False) -> dict:
        """返回路由结果；path == 'chat' 表示走全局 Agent 对话。

        web_search=True（用户显式开启联网开关）时优先走全局对话：
        联网搜索是用户的明确指令，不能被 skill / 专用 Agent 路由抢占后忽略。
        """
        # 0. 用户显式要求联网 → 直接进全局 Agent（保证 web_search 工具被执行）
        if web_search:
            return {"path": "chat"}
        # 1. 科研 skill 强命中
        skill = self._match_skill(text)
        if skill:
            return {"path": "skill", "skill": skill}
        # 2. 专用 Agent
        agent_cls = intents_for(text)
        if agent_cls:
            return {"path": agent_cls.name, "agent": agent_cls}
        # 3. 兜底：全局 Agent
        return {"path": "chat"}

    def handle(
        self,
        text: str,
        use_library: bool = False,
        web_search: bool = False,
        contexts: Optional[list[dict]] = None,
    ) -> dict:
        """完整处理一条消息（全局权限 Agent）。"""
        r = self.route(text, web_search=web_search)
        if r["path"] == "skill":
            out = self._run_skill(r["skill"], text)
        elif r["path"] != "chat":
            agent_cls = r.get("agent")
            try:
                agent = build_agent(r["path"], self.ctx)
                out = agent.handle(text)
            except Exception as exc:  # noqa: BLE001
                out = {"answer": f"{getattr(agent_cls, 'label', r['path'])}执行失败：{exc}"}
            out["route_label"] = out.get("route_label", getattr(agent_cls, "label", r["path"]))
        else:
            out = self._global_chat(
                text, use_library=use_library, web_search=web_search, contexts=contexts
            )
            out["route_label"] = "全局助手"

        out["path"] = r["path"]
        # 智能推荐（供前端跳转引导）
        out["recommendation"] = modules_mod.recommend(text)
        # 记录交互事件到长期记忆（学习用户习惯）
        try:
            memory_mod.record_event(self.user_id, f"[{out.get('route_label','')}] {text[:100]}")
        except Exception:  # noqa: BLE001
            pass
        return out

    def stream(
        self,
        text: str,
        use_library: bool = False,
        web_search: bool = False,
        contexts: Optional[list[dict]] = None,
    ):
        """流式版本：逐段产出回答文本（SSE 用）。

        - 先即时产出一条状态提示：skill / 联网 / 工具调用可能耗时，
          避免执行期间前端长时间空白（用户以为无响应）；
        - skill / 专用 Agent：先同步执行，再把结果分块流出；
        - 全局对话：先做工具决策（可选），再把最终回答分块流出，
          保证流式接口总能拿到完整回答（含工具调用结果）。
        """
        notice = "正在处理你的请求，稍候…\n\n"
        yield notice
        r = self.route(text, web_search=web_search)
        if r["path"] == "chat":
            out = self._global_chat(
                text, use_library=use_library, web_search=web_search, contexts=contexts
            )
        else:
            out = self.handle(text, use_library=use_library, web_search=web_search, contexts=contexts)
        full = out.get("answer", "")
        if not full:
            full = "（助手暂未生成回答）"
        for i in range(0, len(full), 8):
            yield full[i : i + 8]

    # ------------------------------------------------------------------
    # 全局对话（LLM 驱动工具调用 + 记忆注入）
    # ------------------------------------------------------------------

    def _system_prompt(
        self, text: str, use_library: bool, web_search: bool, contexts: Optional[list[dict]] = None
    ) -> str:
        parts: list[str] = [
            "你是「ResearchMate」的全局助手，拥有访问所有功能模块的全局权限，"
            "可以调用工具协助用户完成科研任务。回答用中文，简洁、准确、可执行。",
            "你可以调用以下工具（当任务需要时主动调用，不需要则直接回答）：",
            tool_descriptions(),
            "",
            "模块导航（用户想用某功能时，用 module_navigate 返回跳转建议）：",
            _modules_text(),
        ]

        # @ 引用上下文（用户在输入框用 @ 添加的对象：技能/工具/记忆/模块）
        ctx_text = self._contexts_prompt(contexts)
        if ctx_text:
            parts.append(ctx_text)

        # 长期记忆（跨对话共享）
        try:
            mctx = memory_mod.memory_prompt(self.user_id)
            if mctx:
                parts.append(mctx)
        except Exception:  # noqa: BLE001
            pass

        # 文献库检索增强
        if use_library and self.ctx.db is not None:
            try:
                from app.services import search_service

                hits = search_service.semantic_search(
                    self.ctx.db, query=text, top_k=5, user_id=self.ctx.user_id
                )
                if hits:
                    ctx = "\n\n".join(
                        f"[{h['dimension']}] (from: {h['paper_title']}) {h['content']}" for h in hits
                    )
                    parts.append(
                        "以下为从用户文献库检索到的相关片段，回答时优先参考并标注出处：\n" + ctx
                    )
            except Exception:  # noqa: BLE001
                pass

        if web_search:
            parts.append(
                "用户要求联网查询：请使用 web_search 工具获取最新资料后回答，并标注来源链接。"
            )

        return "\n\n".join(parts)

    def _contexts_prompt(self, contexts: Optional[list[dict]]) -> str:
        """把用户 @ 引用的对象（技能/工具/记忆/模块）加载为可读上下文。"""
        if not contexts:
            return ""
        blocks: list[str] = []
        for c in contexts:
            ctype = str(c.get("type", ""))
            name = str(c.get("name", ""))
            if not name:
                continue
            try:
                if ctype == "skill":
                    from research_skills.registry import get_registry

                    s = get_registry().all_by_name(name)
                    if s:
                        blocks.append(
                            f"[技能@{name}] 目标：{s.get('description','')}\n"
                            f"触发词：{s.get('trigger_keyword')}\n"
                            f"工作流：{(s.get('prompt_template') or '')[:2000]}"
                        )
                elif ctype == "memory":
                    content = memory_mod.read_memory(self.user_id, name)
                    if content:
                        blocks.append(f"[记忆@{name}]\n{content[:3000]}")
                elif ctype == "tool":
                    from app.agent.tools import get_tool

                    t = get_tool(name)
                    if t:
                        blocks.append(f"[工具@{name}] {t.description}\n参数: {t.parameters}")
                elif ctype == "module":
                    m = modules_mod.get_module(name)
                    if m:
                        blocks.append(
                            f"[模块@{name}] {m.get('desc','')}\n"
                            f"跳转路径：{m.get('path','')}\n"
                            f"操作步骤：{m.get('steps')}"
                        )
            except Exception:  # noqa: BLE001
                continue
        if not blocks:
            return ""
        return "用户通过 @ 引用了以下内容，请结合它们回答：\n\n" + "\n\n".join(blocks)

    def _global_chat(
        self,
        text: str,
        use_library: bool,
        web_search: bool,
        contexts: Optional[list[dict]] = None,
    ) -> dict:
        """全局 Agent：注入记忆与工具目录，LLM 决策工具调用循环。"""
        system = self._system_prompt(text, use_library, web_search, contexts)
        history: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ]

        # 无 LLM（纯 mock）时直接给结构化回答，避免反复解析失败
        if self.ctx.llm is None or self.ctx.llm.provider == "mock":
            return self._mock_global(text, use_library, web_search)

        tool_trace: list[dict] = []
        used_tools: set[str] = set()
        seen_calls: set[str] = set()
        for _ in range(3):
            try:
                decision = self.ctx.llm.chat_json(history, temperature=0.2)
            except Exception:  # noqa: BLE001
                break

            tool_name = decision.get("tool") or decision.get("action")
            direct = decision.get("answer")
            if isinstance(direct, dict):
                direct = json.dumps(direct, ensure_ascii=False)
            direct = (direct or "").strip() if isinstance(direct, str) else direct
            if not tool_name:
                if direct:
                    return {"answer": direct, "tool_trace": tool_trace}
                # 模型返回空决策（空 JSON / 键名不符 / answer 为空）：
                # 不再返回死占位符，跳出循环走普通对话兜底
                break

            tool = get_tool(tool_name)
            if tool is None:
                history.append(
                    {"role": "assistant", "content": f"工具 {tool_name} 不存在，请直接回答用户。"}
                )
                continue
            args = decision.get("args") or {}
            # 同工具同参数去重：模型固执重复同一调用时不再重复执行
            sig = f"{tool_name}:{json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)}"
            if sig in seen_calls:
                break
            seen_calls.add(sig)
            try:
                result = tool.run(self.ctx, args)
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "error": str(exc)}
            tool_trace.append(
                {"tool": tool_name, "args": args, "result": _preview(result)}
            )
            used_tools.add(tool_name)
            history.append(
                {"role": "assistant", "content": f"（工具 {tool_name} 已调用，结果：{result}）"}
            )

        # 用户明确开启联网开关但模型未自主调用 web_search：强制执行一次
        # （联网开关是用户的显式指令，不依赖模型决策是否调用工具）
        forced_search: Optional[dict] = None
        if web_search and "web_search" not in used_tools:
            tool = get_tool("web_search")
            if tool is not None:
                try:
                    result = tool.run(self.ctx, {"query": text})
                except Exception as exc:  # noqa: BLE001
                    result = {"ok": False, "error": str(exc)}
                forced_search = result if isinstance(result, dict) else None
                tool_trace.append(
                    {"tool": "web_search", "args": {"query": text}, "result": _preview(result)}
                )
                history.append(
                    {
                        "role": "assistant",
                        "content": (
                            f"（已按用户要求联网搜索「{text}」，结果：{result}）"
                            "请基于以上搜索结果回答用户，并标注来源链接。"
                        ),
                    }
                )

        # 用完工具轮次后，要求模型组织最终回答
        try:
            final = self.ctx.llm.chat(
                history,
                temperature=0.3,
                max_tokens=1500,
            ).strip()
        except Exception:  # noqa: BLE001
            final = "（未能生成最终回答，请重试或检查配置。）"
        if not final:
            final = "（工具调用完成，但模型未生成文字回答。）"

        # 大模型不可达（降级文案）但联网搜索已成功：直接呈现原始搜索结果，
        # 让「联网」开关即使在没有可用 LLM 时也有真实价值
        if forced_search and "离线降级响应" in final:
            items = forced_search.get("items") or []
            if items:
                lines = [f"**联网搜索「{text}」结果**（大模型服务暂不可达，以下为原始结果）", ""]
                for i, it in enumerate(items, 1):
                    title = it.get("title", "")
                    url = it.get("url", "")
                    lines.append(f"{i}. [{title}]({url})" if url else f"{i}. {title}")
                    if it.get("snippet"):
                        lines.append(f"   {it['snippet']}")
                lines.append("")
                lines.append("> 提示：到「设置」页确认大模型接口可用后重试，即可获得 AI 整合后的回答。")
                final = "\n".join(lines)
        return {"answer": final, "tool_trace": tool_trace}

    def _mock_global(self, text: str, use_library: bool, web_search: bool) -> dict:
        """无 LLM 时的确定性回答（演示/离线）：优先给模块推荐 + 工具模拟。"""
        rec = modules_mod.recommend(text)
        answer = f"已收到你的请求：「{text[:60]}」。"
        if rec.get("matched"):
            m = rec["module"]
            answer += (
                f"\n\n我推荐你使用「{m['name']}」模块，点击即可跳转。\n"
                f"操作步骤：\n" + "\n".join(f"{i+1}. {s}" for i, s in enumerate(rec["steps"]))
            )
        answer += (
            "\n\n（当前未连接大模型服务，以上为离线模式。配置 API 后，"
            "助手可联网搜索、一键配置 API、读写文件与长期记忆。）"
        )
        return {"answer": answer, "tool_trace": []}

    # ------------------------------------------------------------------
    # 内部实现（沿用原路由逻辑）
    # ------------------------------------------------------------------

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


def _modules_text() -> str:
    return "\n".join(
        f"- {m['name']}（{m['desc']}）→ {m['path']}" for m in modules_mod.catalog()
    )


def _preview(result: Any) -> str:
    s = str(result)
    return s[:300] + ("…" if len(s) > 300 else "")


def top_route(db, user_id, text: str, llm: LLMAdapter | None = None, mock: bool = False) -> dict:
    """便捷入口：构造顶层 Agent 并执行路由（兼容旧调用）。"""
    return TopAgent(db, user_id, llm=llm, mock=mock).handle(text)


def global_agent(
    db,
    user_id,
    text: str,
    use_library: bool = False,
    web_search: bool = False,
    llm: LLMAdapter | None = None,
) -> dict:
    """全局 Agent 便捷入口。"""
    return TopAgent(db, user_id, llm=llm).handle(text, use_library=use_library, web_search=web_search)
