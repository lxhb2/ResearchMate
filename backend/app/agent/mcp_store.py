"""MCP 配置存储：管理用户自定义的 MCP 服务器配置。

MCP（Model Context Protocol）允许 Agent 接入外部工具/数据源。本模块负责
- 在本地 JSON 文件（storage/agent/mcp.json）保存 MCP 服务器配置；
- 提供列表/增删改查与「测试连接」接口；
- 向 Agent 工具目录暴露已配置服务器及其声明的工具（供 LLM 判断可调用能力）。

真正的 MCP 客户端握手由 mcp_client / mcp_runtime 负责，这里聚焦配置管理、
工具发现缓存与连接测试。
"""
import json
import os
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
            # 覆盖配置时先清理旧的动态工具，避免改名/删工具后残留注册
            try:
                from app.agent import tools as tools_mod
                tools_mod.unregister_tools_by_source(f"mcp:{name}")
            except Exception:  # noqa: BLE001
                pass
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
    # 清理该服务器在工具注册表中的动态 MCP 工具
    try:
        from app.agent import tools as tools_mod
        tools_mod.unregister_tools_by_source(f"mcp:{name}")
    except Exception:  # noqa: BLE001
        pass
    return True


def server_tools(name: str) -> list[dict]:
    """返回某服务器声明的工具列表（来自配置的 tools 字段）。"""
    s = get_server(name)
    if not s:
        return []
    return s.get("tools", []) or []


def test_server(name: str) -> dict:
    """完整握手测试：initialize + tools/list，成功后缓存工具清单。"""
    s = get_server(name)
    if not s:
        return {"ok": False, "error": "服务器不存在"}
    from app.agent import mcp_client
    result = mcp_client.test_server(s)
    if result.get("ok"):
        refresh_tools(name, timeout=10.0)
    return result


def refresh_tools(name: str, timeout: float = 10.0) -> list[dict]:
    """连接服务器发现工具并缓存到配置，返回规范化工具列表。"""
    s = get_server(name)
    if not s:
        return []
    from app.agent import mcp_client
    tools = mcp_client.list_tools(s, timeout=timeout)
    s["tools"] = tools
    save_server(s)
    return tools
