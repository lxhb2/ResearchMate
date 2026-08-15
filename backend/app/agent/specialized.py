"""专用 Agent：面向具体科研领域的轻量编排。

每个 Agent 复用同一个 ``ToolContext``（共用一个数据库 Session 与 LLM 适配器），
不重复实现工具，只做「面向任务的编排」——把用户一句话映射到现有工具调用，
并用 LLM 把结果组织成对用户友好的对话回复。

四个专用 Agent：
- RagAgent        ：RAG 数据库管理（检索 / 解析 / 总结 / 列表）
- DataAgent       ：实验数据处理（数据分析 / 统计 / 绘图）
- ExperimentAgent ：实验流程（实验设计 / 方案）
- WritingAgent    ：科研撰写（起草 / 续写 / 写入项目 / 引用）
"""
from app.agent.tools import ToolContext, get_tool
from app.agent.llm_adapter import LLMAdapter


class SpecializedAgent:
    """专用 Agent 基类。"""

    name = "generic"
    label = "通用"

    def __init__(self, ctx: ToolContext):
        self.ctx = ctx

    def handle(self, text: str) -> dict:
        """处理用户消息，返回 {answer, route_label, artifact_path?}。"""
        raise NotImplementedError

    def _llm_or(self, messages: list[dict], fallback: str) -> str:
        """调用 LLM 组织回答；无 LLM 时返回 fallback。"""
        if self.ctx.llm is None:
            return fallback
        try:
            return self.ctx.llm.chat(messages, temperature=0.3, max_tokens=1000).strip()
        except Exception:  # noqa: BLE001
            return fallback


class RagAgent(SpecializedAgent):
    """RAG 数据库管理：检索 / 解析 / 总结 / 列表。"""

    name = "rag"
    label = "文献检索/管理"

    def handle(self, text: str) -> dict:
        low = text.lower()
        # 意图细分
        if any(k in text for k in ("解析", "导入", "读取 pd", "parse")):
            tool = get_tool("paper_parse")
            args = {"source": "latest"}
        elif any(k in text for k in ("总结", "概述", "摘要", "summarize")):
            tool = get_tool("paper_summarize")
            args = {"source": "latest", "mode": "full"}
        elif any(k in text for k in ("列出", "列表", "有哪些论文", "我的文献", "list")):
            tool = get_tool("library_list")
            args = {"limit": 10}
        else:  # 默认按语义检索
            tool = get_tool("rag_search")
            args = {"query": text, "top_k": 5}

        result = tool.run(self.ctx, args)

        # 无 LLM 时直接给出结构化结果
        if self.ctx.llm is None:
            return {"answer": _format_rag(result, args), "route_label": self.label}

        summary = self._llm_or(
            [
                {"role": "system", "content": "你是科研文献库助手。请把工具返回结果整理成一段简洁、对用户友好的中文回答，说明检索到了什么、关键信息是什么。"},
                {"role": "user", "content": f"工具结果：\n{result}"},
            ],
            fallback=_format_rag(result, args),
        )
        return {"answer": summary, "route_label": self.label}


def _format_rag(result: dict, args: dict) -> str:
    if "hits" in result:
        hits = result.get("hits") or []
        lines = [f"- {h.get('paper_title','?')} [{h.get('dimension','')}]：{h.get('content','')}" for h in hits]
        return f"检索到 {result.get('count', len(hits))} 条相关片段：\n" + ("\n".join(lines) or "（无结果）")
    if "papers" in result:
        papers = result.get("papers") or []
        lines = [f"- {p.get('title','?')}（{p.get('year','')}）" for p in papers]
        return f"文献库共 {result.get('count', len(papers))} 篇：\n" + ("\n".join(lines) or "（空）")
    if "summary" in result:
        return f"总结：{result.get('summary','')}\n\n贡献：{result.get('contributions', [])}"
    if "found" in result:
        return f"解析结果：{result.get('title','?')}\n摘要：{result.get('abstract','')}"
    return str(result)


class DataAgent(SpecializedAgent):
    """实验数据处理：数据分析 / 统计。"""

    name = "data"
    label = "数据分析"

    def handle(self, text: str) -> dict:
        tool = get_tool("data_analyze")
        result = tool.run(self.ctx, {"question": text, "exec_code": True})
        answer = f"分析结果：{result.get('result','')}"
        if result.get("code"):
            answer += f"\n\n生成的代码：\n```python\n{result['code']}\n```"
        return {"answer": answer, "route_label": self.label}


class ExperimentAgent(SpecializedAgent):
    """实验流程：实验设计 / 方案。"""

    name = "experiment"
    label = "实验设计"

    def handle(self, text: str) -> dict:
        tool = get_tool("experiment_plan")
        result = tool.run(self.ctx, {"question": text, "top_k": 4})
        return {"answer": result.get("plan", str(result)), "route_label": self.label}


class WritingAgent(SpecializedAgent):
    """科研撰写：起草 / 续写 / 写入项目 / 引用。"""

    name = "writing"
    label = "科研撰写"

    def handle(self, text: str) -> dict:
        # 引用生成
        if any(k in text for k in ("引用", "参考文献", "citation", "GB7714", "APA")):
            tool = get_tool("citation_generate")
            result = tool.run(self.ctx, {"format": "GB7714", "text": text})
            refs = result.get("references") or []
            return {"answer": "\n".join(f"- {r}" for r in refs), "route_label": self.label}

        # 写入项目
        if any(k in text for k in ("写入", "保存到", "记到", "追加到", "append")):
            tool = get_tool("note_append")
            content = text.split("写入", 1)[-1].split("追加到", 1)[-1].strip()
            result = tool.run(self.ctx, {"project_id": "auto", "content": content or text})
            return {"answer": f"已写入写作项目（{result.get('project_id','')}）。", "route_label": self.label}

        # 默认：起草/续写
        if self.ctx.llm is None:
            return {"answer": f"（Mock 写作）针对「{text}」的草稿占位。", "route_label": self.label}
        draft = self._llm_or(
            [
                {"role": "system", "content": "你是科研写作助手。请根据用户指令起草或续写一段规范的学术文本，直接输出内容。"},
                {"role": "user", "content": text},
            ],
            fallback=f"（草稿占位）{text}",
        )
        return {"answer": draft, "route_label": self.label}


# 路由优先级表：(意图关键词列表, Agent 工厂)
def _build_intents() -> list[tuple[list[str], type]]:
    return [
        (["检索", "查找文献", "搜索文献", "文献库", "相关论文", "查一下", "find", "search", "rag"], RagAgent),
        (["数据分析", "数据处理", "统计", "显著性", "绘图", "图表", "分析一下", "analyze", "显著性差异"], DataAgent),
        (["实验设计", "实验方案", "实验流程", "设计实验", "实验怎么做", "experiment"], ExperimentAgent),
        (["写论文", "写作", "起草", "续写", "润色", "引用", "参考文献", "大纲", "write", "draft"], WritingAgent),
    ]


def build_agent(name: str, ctx: ToolContext) -> SpecializedAgent:
    for _kws, cls in _build_intents():
        if cls.name == name:
            return cls(ctx)
    return RagAgent(ctx)


def intents_for(text: str) -> type | None:
    """按关键词匹配返回命中的专用 Agent 类（无则返回 None）。"""
    for kws, cls in _build_intents():
        if any(k in text for k in kws):
            return cls
    return None