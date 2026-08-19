"""工作流数据模型（Pydantic 强校验）。

借鉴 DeepSeek Harness「自然语言生成工作流 + 工具编排」的设计思想，
但为独立实现。本模块仅负责定义工作流各个节点的数据结构与校验，
不包含任何执行逻辑。

支持四种节点类型：
- tool      : 调用内置工具（paper_parse / rag_search / llm_translate / note_append / llm_compare / citation_generate）
- condition : 简单 if 分支，按变量条件选择下一节点
- confirm   : 人工确认节点（暂停等待审批）
- end       : 终止节点
"""
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# 内置工具白名单
TOOL_NAMES = {
    "paper_parse",
    "rag_search",
    "llm_translate",
    "note_append",
    "llm_compare",
    "citation_generate",
    "paper_summarize",
    "library_list",
    "data_analyze",
    "experiment_plan",
}

# 条件运算符白名单
CONDITION_OPERATORS = {
    "==", "!=", ">", "<", ">=", "<=",
    "contains", "not_contains", "in", "not_in", "exists",
}


class Condition(BaseModel):
    """if 分支的判断条件。

    variable 为带点号的变量路径，例如 ``results.node_2.found``，
    在执行时从全局状态中解析取值后与 value 比较。
    """
    variable: str = Field(..., description="变量路径，如 results.node_2.count")
    operator: Literal["==", "!=", ">", "<", ">=", "<=",
                      "contains", "not_contains", "in", "not_in", "exists"] = Field(
        default="exists", description="比较运算符"
    )
    value: Any = Field(default=None, description="比较的右值（exists 运算符可忽略）")

    @field_validator("operator")
    @classmethod
    def _check_operator(cls, v: str) -> str:
        if v not in CONDITION_OPERATORS:
            raise ValueError(f"不支持的运算符: {v}")
        return v


class WorkflowNode(BaseModel):
    """单个工作流节点。"""
    id: str = Field(..., description="节点 ID，工作流内唯一")
    type: Literal["tool", "condition", "confirm", "end"] = Field(
        ..., description="节点类型"
    )
    description: str = Field(default="", description="节点作用说明（供日志/展示）")

    # ---- 新手引导 / 阶段分组（教学型工作流）----
    guide: Optional[str] = Field(default=None, description="面向新手的步骤讲解/操作提示（展示用）")
    stage: Optional[str] = Field(default=None, description="所属阶段名，用于前端分组展示")

    # ---- tool 节点字段 ----
    tool: Optional[str] = Field(default=None, description="工具名（type=tool 时必填）")
    args: dict[str, Any] = Field(default_factory=dict, description="工具入参")

    # ---- condition 节点字段 ----
    condition: Optional[Condition] = Field(default=None, description="判断条件")
    next_if_true: Optional[str] = Field(default=None, description="条件成立时跳转节点")
    next_if_false: Optional[str] = Field(default=None, description="条件不成立时跳转节点")

    # ---- 通用流转 / 重试 / 错误处理 ----
    next: Optional[str] = Field(default=None, description="默认下一节点")
    retry: int = Field(default=0, ge=0, description="失败重试次数")
    retry_delay: float = Field(default=0.0, ge=0.0, description="重试间隔秒数")
    timeout: Optional[float] = Field(default=None, ge=0, description="单次执行超时秒数")
    # 错误处理策略（借鉴 n8n On Error / Dify Error Handling）：
    # - stop（默认）    ：失败时抛错终止整个工作流
    # - continue        ：失败时用 default_value 作为节点输出，流程继续
    on_error: Literal["stop", "continue"] = Field(default="stop", description="失败策略")
    default_value: Optional[Any] = Field(default=None, description="on_error=continue 时的默认输出")

    @field_validator("tool")
    @classmethod
    def _check_tool(cls, v: Optional[str]) -> Optional[str]:
        # 内置工具做白名单校验；同时允许自定义/接入外部服务的新工具名，
        # 具体是否可用由执行器在运行时校验（工具预留接口）。
        return v

    @model_validator(mode="after")
    def _check_required(self) -> "WorkflowNode":
        """按节点类型校验必填字段的完整性（跨字段校验）。"""
        if self.type == "tool" and not self.tool:
            raise ValueError(f"tool 节点 '{self.id}' 必须指定 tool 字段")
        if self.type == "condition" and self.condition is None:
            raise ValueError(f"condition 节点 '{self.id}' 必须指定 condition 字段")
        return self


class Workflow(BaseModel):
    """完整工作流：节点表 + 起始节点 + 输出说明。"""
    workflow_id: str = Field(default="", description="工作流 ID")
    name: str = Field(default="", description="工作流名称")
    description: str = Field(default="", description="任务拆解说明（Agent 生成）")
    start: str = Field(..., description="起始节点 ID")
    nodes: dict[str, WorkflowNode] = Field(..., description="节点表，key 为节点 ID")
    output: Optional[str] = Field(default=None, description="最终输出节点 ID")

    @model_validator(mode="after")
    def _check_graph(self) -> "Workflow":
        """图结构校验：节点 ID 与 key 一致、跳转目标存在、起始节点存在。"""
        nodes = self.nodes
        for nid, node in nodes.items():
            if nid != node.id:
                raise ValueError(f"节点 key '{nid}' 与节点 id '{node.id}' 不一致")
            for target in (node.next, node.next_if_true, node.next_if_false):
                if target is not None and target not in nodes:
                    raise ValueError(f"节点 '{nid}' 引用了不存在的节点 '{target}'")
        if self.start not in nodes:
            raise ValueError(f"起始节点 '{self.start}' 不存在")
        return self


# ---- 运行结果模型（供执行器输出）----


class NodeLog(BaseModel):
    """单节点执行日志。"""
    node_id: str
    status: Literal["pending", "running", "success", "failed", "skipped", "confirm_wait"] = "pending"
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_ms: Optional[float] = None
    detail: str = Field(default="", description="日志说明")
    retries: int = Field(default=0, ge=0)


class RunResult(BaseModel):
    """一次工作流执行的完整结果。"""
    run_id: str
    workflow_id: str = ""
    status: Literal["running", "success", "failed", "awaiting_confirm"] = "running"
    logs: list[NodeLog] = Field(default_factory=list)
    results: dict[str, Any] = Field(default_factory=dict, description="各节点中间结果")
    final_output: Any = Field(default=None, description="最终输出")
    error: Optional[str] = Field(default=None, description="整体错误信息")
    pending_confirm_nodes: list[str] = Field(default_factory=list, description="待人工确认的节点")
    # 暂停时可序列化的执行状态（供恢复/迭代）
    state: dict[str, Any] = Field(default_factory=dict, description="执行到暂停时的全局状态")
    current_node: Optional[str] = Field(default=None, description="暂停时所在节点 ID")