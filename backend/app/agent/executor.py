"""工作流调度执行引擎。

加载 Agent 生成的 JSON 工作流，按拓扑顺序执行节点，支持：
- 串行执行（next 指针）
- 简单 if 分支（condition 节点）
- 单节点失败重试（retry）
- 人工确认节点（confirm，暂停等待审批）

执行过程维护一个全局状态（state），其中 ``results.<node_id>`` 存放各工具节点的
中间结果，供条件判断与参数模板（``$results.nodeX.output``）引用。

借鉴 DeepSeek Harness 把「工作流定义」与「执行调度」分离的思想，但为独立实现。
"""
import json
import re
import time
import uuid
from typing import Any, Optional

from app.agent.llm_adapter import LLMAdapter
from app.agent.schema import NodeLog, RunResult, Workflow, WorkflowNode
from app.agent.tools import TOOL_REGISTRY, Tool, ToolContext

_TEMPLATE_RE = re.compile(r"\$([\w.]+)")


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并两个字典，override 优先；用于把恢复的初始状态并入默认状态。"""
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class WorkflowExecutionError(Exception):
    """工作流执行失败。"""


class Executor:
    """按节点顺序调度执行一个工作流。"""

    def __init__(
        self,
        tools: Optional[dict[str, Tool]] = None,
        llm: Optional[LLMAdapter] = None,
        auto_confirm: bool = True,
    ):
        self.tools = tools or TOOL_REGISTRY
        self.llm = llm
        self.auto_confirm = auto_confirm

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def run(
        self,
        workflow: Workflow,
        ctx: ToolContext,
        run_id: Optional[str] = None,
        user_vars: Optional[dict] = None,
        initial_state: Optional[dict] = None,
        start_node: Optional[str] = None,
        resume_node: Optional[str] = None,
    ) -> RunResult:
        """执行工作流，返回 RunResult（日志 + 中间结果 + 最终输出）。

        user_vars 为运行期用户输入（如主题、数据），通过 ``$user.<key>`` 在
        节点参数中被引用，是模板复用与迭代运行的主要入口。

        迭代/恢复支持：
        - ``start_node``   从指定节点开始执行（用于恢复）。
        - ``resume_node``  恢复时对该 confirm 节点自动放行一次（即用户已确认该关卡）。
        - ``initial_state`` 恢复时注入此前暂停保存的全局状态（results/user）。
        """
        run_id = run_id or uuid.uuid4().hex
        result = RunResult(run_id=run_id, workflow_id=workflow.workflow_id, status="running")

        # 全局状态：results.<node_id> 存放工具输出，user 存放运行期用户输入
        state: dict[str, Any] = {"results": {}, "user": user_vars or {}}
        if initial_state:
            state = _deep_merge({"results": {}, "user": user_vars or {}}, initial_state)
        logs: dict[str, NodeLog] = {}
        visited: set[str] = set()

        current = start_node or workflow.start
        try:
            while current is not None:
                if current in visited:
                    raise WorkflowExecutionError(f"检测到循环引用，节点 '{current}' 重复访问")
                visited.add(current)
                node = workflow.nodes[current]

                if node.type == "end":
                    result.final_output = self._collect_output(workflow, state)
                    result.status = "success"
                    break

                if node.type == "tool":
                    self._run_tool_node(node, workflow, ctx, state, logs, result)
                elif node.type == "condition":
                    self._run_condition_node(node, workflow, state, logs, result, current)
                elif node.type == "confirm":
                    # 恢复时对该关卡自动放行一次（用户已在上一轮确认）
                    auto_ok = resume_node is not None and node.id == resume_node
                    confirmed = True if auto_ok else self._handle_confirm(node, ctx, logs, result)
                    if not confirmed:
                        # 等待人工确认：暂停运行，保存可恢复状态
                        result.status = "awaiting_confirm"
                        result.pending_confirm_nodes.append(node.id)
                        result.state = state
                        result.current_node = node.id
                        break
                    else:
                        logs.setdefault(node.id, NodeLog(node_id=node.id, status="success"))
                        logs[node.id].detail = f"{node.description or '人工确认'}：已确认通过"
                        logs[node.id].finished_at = _now_iso()

                current = self._next_node(node, current, state)

            # 正常结束（遇到 end 或执行完）
            if result.status == "running":
                result.status = "success"
                result.final_output = self._collect_output(workflow, state)

        except Exception as e:  # noqa: BLE001
            result.status = "failed"
            result.error = str(e)

        result.logs = list(logs.values())
        result.results = state.get("results", {})
        return result

    # ------------------------------------------------------------------
    # 节点执行
    # ------------------------------------------------------------------
    def _run_tool_node(
        self,
        node: WorkflowNode,
        workflow: Workflow,
        ctx: ToolContext,
        state: dict,
        logs: dict,
        result: RunResult,
    ) -> None:
        """执行工具节点，带重试。"""
        tool = self.tools.get(node.tool or "")
        if tool is None:
            raise WorkflowExecutionError(f"未知工具: {node.tool}")

        log = logs.setdefault(node.id, NodeLog(node_id=node.id, status="running"))
        log.detail = node.description or f"调用工具 {node.tool}"
        log.retries = 0
        started = time.time()

        # 解析参数模板：$results.nX.output -> 实际值
        args = self._resolve_templates(node.args, state)

        # 注入适配器
        if ctx.llm is None and self.llm is not None:
            ctx = ToolContext(
                db=ctx.db, user_id=ctx.user_id,
                llm=self.llm, mock=ctx.mock, extra=ctx.extra,
            )

        last_err: Optional[str] = None
        for attempt in range(node.retry + 1):
            if attempt > 0:
                log.retries = attempt
                log.detail = f"{node.description or node.tool}（第 {attempt} 次重试）"
                if node.retry_delay > 0:
                    time.sleep(node.retry_delay)
            try:
                output = tool.run(ctx, args)
                state["results"][node.id] = output
                log.status = "success"
                log.detail = f"{node.description or node.tool} 执行成功"
                log.finished_at = _now_iso()
                log.duration_ms = round((time.time() - started) * 1000, 1)
                return
            except Exception as e:  # noqa: BLE001
                last_err = str(e)

        # 重试耗尽：按节点错误策略处理（借鉴 n8n On Error / Dify 默认值策略）
        if node.on_error == "continue":
            log.status = "success"
            log.detail = (
                f"{node.description or node.tool} 执行失败（{last_err}），"
                f"已按预设策略使用默认值继续"
            )
            log.finished_at = _now_iso()
            log.duration_ms = round((time.time() - started) * 1000, 1)
            state["results"][node.id] = node.default_value
            state.setdefault("degraded", {})[node.id] = last_err
            return

        log.status = "failed"
        log.finished_at = _now_iso()
        log.detail = f"{node.description or node.tool} 执行失败: {last_err}"
        raise WorkflowExecutionError(f"节点 '{node.id}' 执行失败: {last_err}")

    def _run_condition_node(
        self,
        node: WorkflowNode,
        workflow: Workflow,
        state: dict,
        logs: dict,
        result: RunResult,
        current: str,
    ) -> None:
        """执行 if 条件节点，并把结果写入 state 供分支选择。"""
        cond = node.condition
        if cond is None:
            raise WorkflowExecutionError(f"condition 节点 '{node.id}' 缺少 condition")
        val = self._resolve_path(state, cond.variable)
        matched = self._eval_condition(cond.operator, val, cond.value)
        state.setdefault("conditions", {})[node.id] = matched

        log = logs.setdefault(node.id, NodeLog(node_id=node.id, status="success"))
        log.detail = f"{node.description or '分支判断'}：{cond.variable} {'成立' if matched else '不成立'}"
        log.finished_at = _now_iso()

    def _handle_confirm(
        self,
        node: WorkflowNode,
        ctx: ToolContext,
        logs: dict,
        result: RunResult,
    ) -> bool:
        """处理人工确认节点。返回是否确认通过。"""
        log = logs.setdefault(node.id, NodeLog(node_id=node.id, status="confirm_wait"))
        log.detail = node.description or "等待人工确认"
        log.finished_at = _now_iso()

        if ctx.extra.get("auto_confirm", self.auto_confirm):
            log.status = "success"
            log.detail = f"{node.description or '人工确认'}：已自动通过"
            return True
        return False

    # ------------------------------------------------------------------
    # 流转与取值
    # ------------------------------------------------------------------
    def _next_node(self, node: WorkflowNode, current: str, state: dict) -> Optional[str]:
        """根据节点类型决定下一节点。"""
        if node.type == "condition":
            matched = state.get("conditions", {}).get(node.id, False)
            return node.next_if_true if matched else node.next_if_false
        return node.next

    def _collect_output(self, workflow: Workflow, state: dict) -> Any:
        """汇总最终输出。优先取 output 节点，否则返回全部节点结果。"""
        if workflow.output:
            return state.get("results", {}).get(workflow.output)
        return state.get("results", {})

    # ------------------------------------------------------------------
    # 工具函数
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_path(state: dict, path: str) -> Any:
        """从状态树按点号路径取值，例如 results.n3.count。"""
        cur: Any = state
        for part in path.split("."):
            if isinstance(cur, dict):
                if part not in cur:
                    return None
                cur = cur[part]
            elif hasattr(cur, part):
                cur = getattr(cur, part)
            else:
                return None
        return cur

    def _resolve_templates(self, obj: Any, state: dict) -> Any:
        """递归解析参数中的 ``$path`` 模板引用。"""
        if isinstance(obj, str):
            def _repl(m: "re.Match") -> str:
                val = self._resolve_path(state, m.group(1))
                return json.dumps(val, ensure_ascii=False) if not isinstance(val, str) else val
            return _TEMPLATE_RE.sub(_repl, obj)
        if isinstance(obj, dict):
            return {k: self._resolve_templates(v, state) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._resolve_templates(v, state) for v in obj]
        return obj

    @staticmethod
    def _eval_condition(operator: str, val: Any, expected: Any) -> bool:
        """按运算符对已解析的变量值进行求值。"""
        if operator == "exists":
            return val is not None
        if val is None:
            return False
        try:
            if operator == "==":
                return val == expected
            if operator == "!=":
                return val != expected
            if operator == ">":
                return val > expected
            if operator == "<":
                return val < expected
            if operator == ">=":
                return val >= expected
            if operator == "<=":
                return val <= expected
            if operator == "contains":
                return expected in val
            if operator == "not_contains":
                return expected not in val
            if operator == "in":
                return val in expected
            if operator == "not_in":
                return val not in expected
        except TypeError:
            return False
        return False


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")