"""Agent + 工作流调度引擎 离线演示脚本。

直接运行本脚本即可看到「科研指令 → 生成工作流 → 调度执行 → 得到结果」的完整链路。
默认使用 Mock 模型（无需真实 API Key / 数据库 / 外部服务），完全离线可运行。

运行方式：
    python scripts/demo_agent_workflow.py
"""
import json
import sys
import os

# 保证可独立运行（无论从 backend 目录或 scripts 目录启动）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent.agent import Agent
from app.agent.executor import Executor
from app.agent.llm_adapter import LLMAdapter
from app.agent.schema import Workflow
from app.agent.tools import ToolContext


def pretty(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def sep(title: str):
    print("\n" + "=" * 68)
    print(f"  {title}")
    print("=" * 68)


def demo_generate_and_run():
    """演示 1：输入科研指令 → Agent 生成工作流 → 执行。"""
    sep("演示 1：Agent 生成工作流 + 调度执行（离线 Mock）")

    llm = LLMAdapter.mock()  # 离线模型
    agent = Agent(llm)

    instruction = "导入新论文后，自动翻译摘要，和我标记重点的文献做方法对比，把对比表格写入写作项目"
    print(f"\n[用户指令] {instruction}\n")

    workflow, description = agent.generate_workflow(instruction)
    print(f"[Agent 任务拆解] {description}\n")
    print(f"[生成的工作流 JSON]\n{pretty(workflow.model_dump())}\n")

    ctx = ToolContext(llm=llm, mock=True)
    executor = Executor(llm=llm, auto_confirm=True)
    result = executor.run(workflow, ctx)

    print(f"[运行状态] {result.status}\n[节点执行日志]")
    for log in result.logs:
        print(f"  - {log.node_id:>4}  [{log.status:<8}]  {log.detail}")
    print(f"\n[最终输出]\n{pretty(result.final_output)}")
    return result


def demo_branch_and_confirm():
    """演示 2：条件分支 + 人工确认节点（直接提交手写工作流）。"""
    sep("演示 2：条件分支 + 人工确认节点")

    # 手写一个带 if 分支与人工确认的工作流
    workflow = Workflow.model_validate({
        "workflow_id": "wf_demo_branch",
        "name": "分支与确认演示",
        "description": "演示 condition 分支与 confirm 确认节点",
        "start": "n1",
        "nodes": {
            "n1": {
                "id": "n1", "type": "tool", "tool": "rag_search",
                "description": "检索文献", "retry": 1,
                "args": {"query": "方法对比", "top_k": 2}, "next": "n2",
            },
            "n2": {
                "id": "n2", "type": "condition",
                "description": "判断是否检索到结果",
                "condition": {"variable": "results.n1.count", "operator": ">", "value": 0},
                "next_if_true": "n3", "next_if_false": "n4",
            },
            "n3": {"id": "n3", "type": "tool", "tool": "llm_compare",
                   "description": "生成对比表格", "args": {"query": "方法对比"}, "next": "n5"},
            "n4": {"id": "n4", "type": "confirm", "description": "未检索到结果，请人工确认", "next": "n5"},
            "n5": {"id": "n5", "type": "end"},
        },
        "output": "n3",
    })

    llm = LLMAdapter.mock()
    ctx = ToolContext(llm=llm, mock=True)

    # 2a. 自动确认：mock 检索到结果(count>0)，走真分支
    res_auto = Executor(llm=llm, auto_confirm=True).run(workflow, ctx, run_id="demo-branch-auto")
    print("\n[auto_confirm=True] 状态:", res_auto.status)
    for log in res_auto.logs:
        print(f"  - {log.node_id:>4}  [{log.status:<8}]  {log.detail}")

    # 2b. 关闭自动确认：若命中 confirm 节点则暂停
    res_wait = Executor(llm=llm, auto_confirm=False).run(workflow, ctx, run_id="demo-branch-wait")
    print("\n[auto_confirm=False] 状态:", res_wait.status,
          "| 待确认节点:", res_wait.pending_confirm_nodes)
    for log in res_wait.logs:
        print(f"  - {log.node_id:>4}  [{log.status:<8}]  {log.detail}")


def demo_retry():
    """演示 3：单节点失败重试。"""
    sep("演示 3：单节点失败自动重试")

    # 构造一个会先失败再成功的工具
    from app.agent.tools import Tool, TOOL_REGISTRY

    attempts = {"n": 0}

    def flaky(ctx, args):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("模拟偶发失败")
        return {"ok": True, "attempts": attempts["n"]}

    flaky_tool = Tool("flaky_tool", "先失败再成功的工具", {}, flaky)
    tools = dict(TOOL_REGISTRY)
    tools["flaky_tool"] = flaky_tool

    workflow = Workflow.model_validate({
        "workflow_id": "wf_demo_retry",
        "name": "重试演示",
        "start": "n1",
        "description": "演示单节点失败重试",
        "nodes": {
            "n1": {"id": "n1", "type": "tool", "tool": "flaky_tool", "args": {},
                   "description": "一个会失败两次的工具", "retry": 3, "next": "n2"},
            "n2": {"id": "n2", "type": "end"},
        },
        "output": "n1",
    })

    ctx = ToolContext(mock=True)
    result = Executor(tools=tools, auto_confirm=True).run(workflow, ctx, run_id="demo-retry")
    print("\n[运行状态]", result.status, "| 实际尝试次数:", attempts["n"])
    for log in result.logs:
        print(f"  - {log.node_id:>4}  [{log.status:<8}]  重试 {log.retries} 次 | {log.detail}")
    print("\n[节点输出]", result.results.get("n1"))


if __name__ == "__main__":
    demo_generate_and_run()
    demo_branch_and_confirm()
    demo_retry()
    sep("全部演示完成")