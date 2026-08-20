"""Agent MCP 集成测试：真实 stdio JSON-RPC 握手、动态工具注册与多轮上下文。"""

import json
import os
import sys
import tempfile

from app.agent import mcp_client, mcp_store, mcp_runtime
from app.agent.tools import get_tool
from app.agent.top_agent import TopAgent


def _fake_mcp_script() -> str:
    code = r"""
import json
import sys

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    method = msg.get("method")
    rid = msg.get("id")
    if method == "initialize":
        print(json.dumps({
            "jsonrpc": "2.0", "id": rid,
            "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "serverInfo": {"name": "fake-mcp", "version": "1.0.0"},
            },
        }), flush=True)
    elif method == "notifications/initialized":
        continue
    elif method == "tools/list":
        print(json.dumps({
            "jsonrpc": "2.0", "id": rid,
            "result": {
                "tools": [{
                    "name": "echo",
                    "description": "Echo the input text",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                }],
            },
        }), flush=True)
    elif method == "tools/call":
        args = msg.get("params", {}).get("arguments", {}) or {}
        text = args.get("text", "")
        print(json.dumps({
            "jsonrpc": "2.0", "id": rid,
            "result": {"content": [{"type": "text", "text": text}]},
        }), flush=True)
"""
    fd, path = tempfile.mkstemp(suffix=".py", prefix="fake_mcp_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(code)
    return path


def _server_config(script_path: str) -> dict:
    return {
        "name": "fake",
        "type": "stdio",
        "command": sys.executable,
        "args": [script_path],
        "enabled": True,
        "tools": [],
    }


def test_mcp_stdio_list_and_call() -> None:
    script = _fake_mcp_script()
    try:
        server = _server_config(script)
        tools = mcp_client.list_tools(server)
        assert tools and tools[0]["name"] == "echo"

        result = mcp_client.call_tool(server, "echo", {"text": "hello mcp"})
        assert result["ok"] is True
        assert result["text"] == "hello mcp"
    finally:
        os.remove(script)


def test_mcp_runtime_registers_dynamic_tool() -> None:
    script = _fake_mcp_script()
    try:
        mcp_store.remove_server("fake")
        mcp_store.save_server(_server_config(script))
        info = mcp_runtime.refresh_server("fake")
        assert info["ok"] is True
        assert info["tool_count"] == 1

        tool = get_tool("mcp__fake__echo")
        assert tool is not None
        result = tool.run(None, {"text": "agent call"})
        assert result["ok"] is True
        assert result["text"] == "agent call"
    finally:
        mcp_runtime.unregister_server("fake")
        mcp_store.remove_server("fake")
        os.remove(script)


def test_top_agent_system_prompt_includes_history() -> None:
    agent = TopAgent(db=None, user_id="user-1", mock=True)
    prompt = agent._system_prompt(
        "再总结一下",
        use_library=False,
        web_search=False,
        contexts=None,
        history=[
            {"role": "user", "content": "帮我检索 transformer 相关文献"},
            {"role": "assistant", "content": "已为你找到 3 篇相关文献。"},
        ],
    )
    assert "当前对话历史" in prompt
    assert "帮我检索 transformer 相关文献" in prompt
    assert "已为你找到 3 篇相关文献" in prompt
