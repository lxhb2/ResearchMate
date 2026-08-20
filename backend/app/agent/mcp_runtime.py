"""MCP 运行时：把已配置服务器发现为真实可调用的 Agent 工具。

策略（借鉴 CrewAI / Agentica 的 MCP 接入方式）：
- 每个服务器发现出的工具以 ``mcp__<server>__<tool>`` 注册进全局工具表；
- 工具描述带服务器名，参数直接使用 MCP 的 inputSchema；
- 调用时按配置临时发起 stdio / HTTP 会话，不长期占用进程；
- 服务器禁用/删除时自动注销全部动态工具。
"""
import re
from typing import Any, Callable, Optional

from app.agent import mcp_store
from app.agent import mcp_client
from app.agent import tools as tools_mod

MCP_SOURCE_PREFIX = "mcp:"


def _tool_name(server_name: str, tool_name: str) -> str:
    safe_server = re.sub(r"[^A-Za-z0-9_-]+", "_", server_name).strip("_") or "server"
    safe_tool = re.sub(r"[^A-Za-z0-9_-]+", "_", tool_name).strip("_") or "tool"
    return f"mcp__{safe_server}__{safe_tool}"


def _make_handler(server_name: str, tool_name: str) -> Callable[[tools_mod.ToolContext, dict], Any]:
    def handler(ctx: tools_mod.ToolContext, args: dict) -> Any:
        return call_tool(server_name, tool_name, args or {})
    return handler


def _register(server: dict, mcp_tools: list[dict]) -> list[str]:
    """注册某服务器的全部动态工具，返回工具名列表。"""
    unregister_server(server["name"])
    names: list[str] = []
    for t in mcp_tools:
        tool_name = str(t.get("name") or "").strip()
        if not tool_name:
            continue
        full_name = _tool_name(server["name"], tool_name)
        schema = t.get("inputSchema") or {"type": "object", "properties": {}, "required": []}
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}, "required": []}
        description = (
            f"[MCP:{server['name']}] {t.get('description') or tool_name}。"
            "调用参数遵循该 MCP 工具的 JSON Schema。"
        )
        tools_mod.register_tool(
            tools_mod.Tool(
                name=full_name,
                description=description,
                parameters=schema,
                handler=_make_handler(server["name"], tool_name),
                source=f"{MCP_SOURCE_PREFIX}{server['name']}",
            ),
            source=f"{MCP_SOURCE_PREFIX}{server['name']}",
        )
        names.append(full_name)
    return names


def refresh_server(name: str, timeout: float = 10.0) -> dict:
    """发现并注册单个服务器；失败时返回 {ok, error}。"""
    server = mcp_store.get_server(name)
    if not server:
        return {"ok": False, "error": "服务器不存在", "tools": []}
    if not server.get("enabled", True):
        unregister_server(name)
        return {"ok": False, "error": "服务器已禁用", "tools": []}
    try:
        mcp_tools = mcp_store.refresh_tools(name, timeout=timeout)
        names = _register(server, mcp_tools)
        return {"ok": True, "server": name, "tool_count": len(names), "tools": mcp_tools}
    except Exception as e:  # noqa: BLE001
        unregister_server(name)
        return {"ok": False, "error": str(e), "tools": []}


def refresh_all(timeout: float = 8.0) -> dict:
    """启动/按需刷新全部启用的 MCP 服务器，返回汇总。"""
    servers = mcp_store.list_servers()
    enabled = [s for s in servers if s.get("enabled", True)]
    ok, failed = [], []
    for s in enabled:
        result = refresh_server(s["name"], timeout=timeout)
        if result.get("ok"):
            ok.append(result)
        else:
            failed.append({"name": s["name"], "error": result.get("error")})
    return {"ok_count": len(ok), "failed_count": len(failed), "ok": ok, "failed": failed}


def unregister_server(name: str) -> int:
    """注销某服务器注册的全部动态工具，返回数量。"""
    return len(tools_mod.unregister_tools_by_source(f"{MCP_SOURCE_PREFIX}{name}"))


def call_tool(server_name: str, tool_name: str, arguments: dict) -> dict:
    """调用 MCP 工具；配置不存在/失败时返回可读错误而非抛异常。"""
    server = mcp_store.get_server(server_name)
    if not server:
        return {"ok": False, "error": f"MCP 服务器 {server_name} 不存在"}
    try:
        return mcp_client.call_tool(server, tool_name, arguments or {})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"MCP 调用失败：{e}"}


def active_tool_catalog() -> list[dict]:
    """返回当前已注册的 MCP 工具目录（供前端/工具面板展示）。"""
    servers = mcp_store.list_servers()
    out: list[dict] = []
    for s in servers:
        for t in s.get("tools", []) or []:
            out.append(
                {
                    "name": _tool_name(s["name"], str(t.get("name") or "")),
                    "server": s["name"],
                    "mcp_name": t.get("name"),
                    "description": t.get("description") or "",
                    "parameters": t.get("inputSchema") or {},
                }
            )
    return out
