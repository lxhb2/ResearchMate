"""MCP 配置存储：管理用户自定义的 MCP 服务器配置。

MCP（Model Context Protocol）允许 Agent 接入外部工具/数据源。本模块负责
- 在本地 JSON 文件（storage/agent/mcp.json）保存 MCP 服务器配置；
- 提供列表/增删改查与「测试连接」接口；
- 向 Agent 工具目录暴露已配置服务器及其声明的工具（供 LLM 判断可调用能力）。

真正的 MCP 客户端握手由前端/运行时负责，这里聚焦配置管理与目录能力。
"""
import json
import os
import subprocess
from typing import Any

from app.config import settings as app_settings

# MCP 服务器类型
TYPE_HTTP = "http"      # HTTP/SSE 远程服务器
TYPE_STDIO = "stdio"    # 本地命令式服务器（如 npx -y @modelcontextprotocol/server-xxx）


def _path() -> str:
    d = os.path.join(app_settings.STORAGE_DIR, "agent")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "mcp.json")


def _load() -> list[dict]:
    p = _path()
    if not os.path.isfile(p):
        return []
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save(servers: list[dict]) -> None:
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(servers, f, ensure_ascii=False, indent=2)


def list_servers() -> list[dict]:
    """返回全部 MCP 服务器（脱敏：不含密码字段）。"""
    return [
        {k: v for k, v in s.items() if k not in ("api_key", "secret")}
        for s in _load()
    ]


def get_server(name: str) -> dict | None:
    for s in _load():
        if s.get("name") == name:
            return s
    return None


def save_server(server: dict) -> dict:
    """新增或覆盖一个 MCP 服务器配置。"""
    name = str(server.get("name", "")).strip()
    if not name:
        raise ValueError("MCP 服务器必须有 name")
    servers = _load()
    for i, s in enumerate(servers):
        if s.get("name") == name:
            servers[i] = server
            _save(servers)
            return server
    servers.append(server)
    _save(servers)
    return server


def remove_server(name: str) -> bool:
    servers = _load()
    rest = [s for s in servers if s.get("name") != name]
    if len(rest) == len(servers):
        return False
    _save(rest)
    return True


def server_tools(name: str) -> list[dict]:
    """返回某服务器声明的工具列表（来自配置的 tools 字段）。"""
    s = get_server(name)
    if not s:
        return []
    return s.get("tools", []) or []


def test_server(name: str) -> dict:
    """测试 MCP 服务器连通性。

    - http/sse：发起一次 HEAD/GET 探测；
    - stdio：尝试启动命令并立即终止（验证命令是否存在可执行）。
    """
    s = get_server(name)
    if not s:
        return {"ok": False, "error": "服务器不存在"}
    stype = s.get("type", TYPE_HTTP)

    if stype == TYPE_HTTP:
        url = (s.get("url") or "").strip()
        if not url:
            return {"ok": False, "error": "缺少 url"}
        import httpx

        try:
            resp = httpx.get(url, timeout=8.0, follow_redirects=True)
            return {"ok": resp.status_code < 500, "status": resp.status_code, "url": url}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"连接失败：{e}", "url": url}

    if stype == TYPE_STDIO:
        command = (s.get("command") or "").strip()
        args = s.get("args") or []
        if not command:
            return {"ok": False, "error": "缺少 command"}
        try:
            proc = subprocess.run(
                [command, *args, "--help"],
                capture_output=True, timeout=8.0,
            )
            return {"ok": True, "exit_code": proc.returncode, "tip": "命令可执行（--help 探测）"}
        except FileNotFoundError:
            return {"ok": False, "error": f"命令不存在：{command}"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"启动失败：{e}"}

    return {"ok": False, "error": f"未知类型：{stype}"}
