"""Agent 任务生成器。

接收用户自然语言科研指令，将其拆解为标准化 JSON 工作流（Workflow 模型）。
借鉴 DeepSeek Harness「自然语言生成工作流」的设计思想，但为独立实现：
Agent 通过一个简化的 ReAct 循环（推理 -> 行动 -> 校验反馈）把用户意图映射到
内置工具序列，产出自定义 schema 的工作流，支持串行、if 分支与人工确认节点。
"""
import json
from typing import Optional

from pydantic import ValidationError

from app.agent.llm_adapter import LLMAdapter
from app.agent.schema import Workflow
from app.agent.tools import tool_descriptions

# 最大生成重试轮数（ReAct 循环上限）
MAX_ATTEMPTS = 3

# 工作流 schema 说明（写入系统提示，指导模型输出）
WORKFLOW_SCHEMA_HINT = """请根据用户指令，输出一个 JSON 工作流对象，结构如下：
{
  "workflow_id": "wf_xxx",
  "name": "工作流名称",
  "description": "任务拆解说明（简述每一步做什么）",
  "start": "n1",
  "nodes": {
    "n1": {
      "id": "n1",
      "type": "tool",            // tool | condition | confirm | end
      "description": "节点作用说明",
      "tool": "rag_search",       // type=tool 时必填
      "args": {"query": "..."},  // 工具入参，见工具说明
      "next": "n2",              // 默认下一节点
      "retry": 1                 // 失败重试次数（可选）
    },
    "n2": {
      "id": "n2",
      "type": "condition",        // 简单 if 分支
      "condition": {"variable": "results.n1.count", "operator": ">", "value": 0},
      "next_if_true": "n3",
      "next_if_false": "n4"
    },
    "n3": {"id": "n3", "type": "tool", "tool": "llm_compare", "args": {}, "next": "n5"},
    "n4": {"id": "n4", "type": "confirm", "description": "人工确认", "next": "n5"},
    "n5": {"id": "n5", "type": "end"}
  },
  "output": "n3"
}
要求：
- 节点 id 必须唯一，且被引用的节点必须存在。
- 只输出 JSON，不要额外文字。
"""


def _build_dimensions_desc() -> str:
    """生成 6 维度向量表的说明文本（供 Agent 系统提示使用）。

    从 search_service 读取唯一定义，避免与工具/拆分逻辑重复维护。
    """
    try:
        from app.services.search_service import DIMENSIONS, DIMENSION_LABELS
        lines = [
            f"- {d}：{DIMENSION_LABELS.get(d, d)}" for d in DIMENSIONS
        ]
        return "\n".join(lines)
    except Exception:  # noqa: BLE001
        return "- title_keywords/background/method/results/conclusion/contributions"


class WorkflowGenerationError(Exception):
    """工作流生成失败。"""


class Agent:
    """把自然语言指令转化为可执行的工作流。"""

    def __init__(self, llm: LLMAdapter):
        self.llm = llm
        self.tools_desc = tool_descriptions()
        # 6 维度向量表说明：供系统提示描述可供检索的语义维度
        self.dimensions_desc = _build_dimensions_desc()

    def generate_workflow(self, user_prompt: str) -> tuple[Workflow, str]:
        """生成工作流。

        返回 (Workflow, 任务拆解说明)。
        """
        system = (
            "你是一个科研助手 Agent 的工作流规划器。你会把用户的中文科研指令拆解为"
            "一个可执行的工作流，选择合适的内置工具编排节点顺序。\n\n"
            "可用工具如下：\n"
            f"{self.tools_desc}\n\n"
            "文献库按 6 个语义维度向量化存储，检索文献相关片段时可选维度：\n"
            f"{self.dimensions_desc}\n"
            "（rag_search 的 dimension 参数、experiment_plan、llm_compare 的 dimensions 参数均可使用）\n\n"
            f"工作流输出规范：\n{WORKFLOW_SCHEMA_HINT}"
        )
        user = f"用户指令：{user_prompt}"

        last_error: Optional[str] = None
        for attempt in range(MAX_ATTEMPTS):
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            if last_error:
                messages.append(
                    {"role": "assistant", "content": last_error}
                )
                messages.append(
                    {"role": "user", "content": "上次生成的工作流校验失败，请修正后重新输出完整 JSON。"}
                )
            try:
                data = self.llm.chat_json(messages, temperature=0.4)
            except Exception as e:  # noqa: BLE001
                last_error = f"JSON 解析失败: {e}"
                continue

            try:
                workflow = Workflow.model_validate(data)
                return workflow, workflow.description
            except ValidationError as e:
                last_error = f"工作流结构校验失败: {e}"

        raise WorkflowGenerationError(
            f"连续 {MAX_ATTEMPTS} 次生成工作流均失败。最后一次错误: {last_error}"
        )