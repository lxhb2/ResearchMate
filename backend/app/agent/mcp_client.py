"""轻量 MCP 客户端：stdio 与 HTTP/SSE 两种传输的 JSON-RPC 实现。

不依赖 mcp SDK，用标准库 + httpx 完成最小可用握手：
- stdio：子进程标准输入输出逐行 JSON-RPC；
- http：Streamable HTTP POST（兼容 SSE 响应）；
- legacy SSE：URL 含 /sse 时先 GET 发现 endpoint，再 POST 调用。

仅实现 Agent 最需要的 initialize / tools/list / tools/call，
资源与提示模板暂不暴露为工具。
"""
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from typing import Any, Optional

import httpx

PROTOCOL_VERSION = "2025-06-18"
MAX_RESULT_CHARS = 40000


class McpError(Exception):
    """MCP 通信失败。"""


def _rpc_id() -> int:
    global _counter
    _counter += 1
    return _counter


_counter = 0


def _stderr_text(proc: subprocess.Popen) -> str:
    try:
        if proc.stderr is None or proc.poll() is None:
            return ""
        raw = proc.stderr.read().decode("utf-8", "replace").strip()
        return f" stderr: {raw[:500]}" if raw else ""
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# stdio 传输
# ---------------------------------------------------------------------------

class _StdioSession:
    """管理一个 MCP stdio 子进程的读写。"""

    def __init__(self, command: str, args: list[str]):
        resolved = shutil.which(command)
        if resolved is None and os.name == "nt":
            resolved = shutil.which(command + ".cmd") or shutil.which(command + ".bat")
        if resolved is None:
            raise McpError(f"命令不存在：{command}")
        self.proc = subprocess.Popen(
            [resolved, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=dict(os.environ),
        )
        self._q: "queue.Queue[tuple[str, Optional[str]]]" = queue.Queue()
        self._eof = False
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        try:
            if self.proc.stdout is not None:
                for line in self.proc.stdout:
                    self._q.put(("line", line))
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._q.put(("eof", None))

    def _drain_stderr(self) -> None:
        try:
            if self.proc.stderr is not None:
                for _line in self.proc.stderr:
                    pass
        except Exception:  # noqa: BLE001
            pass

    def send(self, payload: dict) -> None:
        if self.proc.stdin is None:
            raise McpError("MCP 子进程 stdin 不可用")
        self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: Optional[dict] = None, timeout: float = 10.0) -> dict:
        req_id = _rpc_id()
        self.send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                kind, line = self._q.get(timeout=max(0.05, deadline - time.monotonic()))
            except queue.Empty:
                break
            if kind == "eof":
                raise McpError(f"MCP 子进程提前退出{_stderr_text(self.proc)}")
            try:
                msg = json.loads(line or "")
            except json.JSONDecodeError:
                continue
            if msg.get("id") != req_id:
                continue
            if msg.get("error"):
                err = msg["error"]
                raise McpError(f"MCP 返回错误：{err.get('message') or err}")
            result = msg.get("result") or {}
            return result if isinstance(result, dict) else {"value": result}
        raise McpError(f"MCP 请求超时（{method}）{_stderr_text(self.proc)}")

    def notify(self, method: str, params: Optional[dict] = None) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def close(self) -> None:
        try:
            self.proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass


def _run_stdio(server: dict, method: str, params: Optional[dict] = None, timeout: float = 10.0) -> dict:
    command = (server.get("command") or "").strip()
    args = list(server.get("args") or [])
    if not command:
        raise McpError("MCP 服务器缺少 command")
    session = _StdioSession(command, args)
    try:
        session.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "ResearchMate", "version": "0.2.0"},
        }, timeout=timeout)
        session.notify("notifications/initialized", {})
        return session.request(method, params or {}, timeout=timeout)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# HTTP / SSE 传输
# ---------------------------------------------------------------------------

def _parse_sse_response(text: str) -> Optional[dict]:
    """从 SSE 文本中解析最后一条 JSON-RPC data。"""
    result: Optional[dict] = None
    data_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            if payload:
                data_lines.append(payload)
    for payload in data_lines:
        try:
            result = json.loads(payload)
        except json.JSONDecodeError:
            continue
    return result


def _parse_rpc_text(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise McpError("MCP HTTP 返回空响应")
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        body = _parse_sse_response(text)
    if not isinstance(body, dict):
        raise McpError(f"MCP HTTP 响应不是 JSON-RPC 对象：{text[:200]}")
    return body


def _sse_endpoint(url: str, timeout: float) -> str:
    """legacy SSE：GET 事件流并读取 endpoint 事件。"""
    headers = {"Accept": "text/event-stream", "User-Agent": "ResearchMate/0.2"}
    try:
        with httpx.stream("GET", url, headers=headers, timeout=timeout, follow_redirects=True) as resp:
            if resp.status_code >= 400:
                raise McpError(f"MCP SSE 连接失败：HTTP {resp.status_code}")
            event = ""
            for line in resp.iter_lines():
                line = (line or "").strip()
                if line.startswith("event:"):
                    event = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    data = line[len("data:"):].strip()
                    if event == "endpoint" and data:
                        return data if data.startswith("http") else _join_url(url, data)
    except httpx.HTTPError as e:
        raise McpError(f"MCP SSE 连接失败：{e}") from e
    raise McpError("MCP SSE 未返回 endpoint")


def _join_url(base: str, path: str) -> str:
    from urllib.parse import urljoin
    return urljoin(base, path)


def _http_request(
    url: str,
    payload: dict,
    session_id: Optional[str] = None,
    timeout: float = 10.0,
    allow_empty: bool = False,
) -> tuple[dict, Optional[str]]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "ResearchMate/0.2",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.post(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                raise McpError(f"MCP HTTP {resp.status_code}：{resp.text[:200]}")
            if not (resp.text or "").strip() and allow_empty:
                return {}, resp.headers.get("mcp-session-id") or session_id
            body = _parse_rpc_text(resp.text)
            new_sid = resp.headers.get("mcp-session-id") or session_id
            if body.get("error"):
                err = body["error"]
                raise McpError(f"MCP 返回错误：{err.get('message') or err}")
            result = body.get("result") or {}
            return (result if isinstance(result, dict) else {"value": result}), new_sid
    except httpx.HTTPError as e:
        raise McpError(f"MCP HTTP 请求失败：{e}") from e


def _http_initialize(server: dict, timeout: float = 10.0) -> tuple[str, Optional[str]]:
    """建立 Streamable HTTP / legacy SSE 会话，返回 (endpoint, session_id)。"""
    url = (server.get("url") or "").strip()
    if not url:
        raise McpError("MCP 服务器缺少 url")
    target = _sse_endpoint(url, timeout) if "/sse" in url.lower() else url
    result, session_id = _http_request(
        target,
        {
            "jsonrpc": "2.0",
            "id": _rpc_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "ResearchMate", "version": "0.2.0"},
            },
        },
        session_id=None,
        timeout=timeout,
    )
    _http_request(
        target,
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        },
        session_id=session_id,
        timeout=timeout,
        allow_empty=True,
    )
    return target, session_id


def _run_http_session(
    server: dict,
    method: str,
    params: Optional[dict] = None,
    timeout: float = 10.0,
) -> dict:
    """建立 HTTP 会话后执行一次 JSON-RPC 方法。"""
    target, session_id = _http_initialize(server, timeout=timeout)
    result, _new_sid = _http_request(
        target,
        {
            "jsonrpc": "2.0",
            "id": _rpc_id(),
            "method": method,
            "params": params or {},
        },
        session_id=session_id,
        timeout=timeout,
    )
    return result


def _run_http(server: dict, method: str, params: Optional[dict] = None, timeout: float = 10.0) -> dict:
    """兼容入口：直接执行一次方法（自动初始化会话）。"""
    return _run_http_session(server, method, params, timeout)


# ---------------------------------------------------------------------------
# 对外统一接口
# ---------------------------------------------------------------------------

def _normalize_tool(tool: dict) -> dict:
    """把 MCP 工具定义规范化为 ResearchMate Tool 参数。"""
    return {
        "name": str(tool.get("name") or "").strip(),
        "description": str(tool.get("description") or "").strip(),
        "inputSchema": tool.get("inputSchema") or tool.get("parameters") or {
            "type": "object",
            "properties": {},
            "required": [],
        },
    }


def list_tools(server: dict, timeout: float = 10.0) -> list[dict]:
    """发现 MCP 服务器的工具列表（name/description/inputSchema）。"""
    stype = server.get("type", "http")
    try:
        result = (
            _run_stdio(server, "tools/list", timeout=timeout)
            if stype == "stdio"
            else _run_http(server, "tools/list", timeout=timeout)
        )
    except McpError:
        raise
    raw = result.get("tools") or []
    return [_normalize_tool(t) for t in raw if isinstance(t, dict) and t.get("name")]


def call_tool(
    server: dict,
    tool_name: str,
    arguments: Optional[dict] = None,
    timeout: float = 60.0,
) -> dict:
    """调用 MCP 工具，返回统一的可读结果。"""
    stype = server.get("type", "http")
    try:
        result = (
            _run_stdio(server, "tools/call", {
                "name": tool_name,
                "arguments": arguments or {},
            }, timeout=timeout)
            if stype == "stdio"
            else _run_http(server, "tools/call", {
                "name": tool_name,
                "arguments": arguments or {},
            }, timeout=timeout)
        )
    except McpError:
        raise

    content = result.get("content") or []
    texts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            texts.append(str(item.get("text") or ""))
        elif item.get("type") == "resource":
            texts.append(json.dumps(item, ensure_ascii=False))
        else:
            texts.append(json.dumps(item, ensure_ascii=False))
    text = "\n".join(t for t in texts if t)
    if not text and result.get("structuredContent") is not None:
        text = json.dumps(result["structuredContent"], ensure_ascii=False)
    if result.get("isError"):
        return {"ok": False, "tool": tool_name, "error": text or "MCP 工具执行失败"}
    return {
        "ok": True,
        "tool": tool_name,
        "text": text[:MAX_RESULT_CHARS],
        "content": content,
    }


def test_server(server: dict, timeout: float = 10.0) -> dict:
    """完整握手测试：initialize + tools/list。"""
    try:
        tools = list_tools(server, timeout=timeout)
        return {"ok": True, "tool_count": len(tools), "tools": tools}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "tools": []}
