"""全局 Agent 路由：对话、智能推荐、模块目录、长期记忆、Skill 与 MCP 配置。

对应产品需求：
1. 全局权限 Agent（智能问答 + 工具调用）
2. 智能推荐（跳转模块 + 引导）
3. 工具调用（联网搜索 / 文件配置 / API 一键配置 / 问答）
4. Skill / MCP 自定义配置
5. 本地 MD 长期记忆（跨对话共享）
"""
import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.agent.top_agent import TopAgent
from app.agent.llm_adapter import LLMAdapter
from app.agent import memory as memory_mod
from app.agent import mcp_store
from app.agent import modules as modules_mod
from app.agent import skill_store
from app.agent import tools as tools_mod
from app.agent.plugin_manager import PluginError, get_plugin_manager
from app.services import settings_service

router = APIRouter(prefix="/agent", tags=["agent"])


def _build_llm(db: Session, user_id) -> LLMAdapter:
    try:
        cfg = settings_service.get_llm_config(db, str(user_id))
        return LLMAdapter.from_config(cfg)
    except Exception:  # noqa: BLE001
        return LLMAdapter.mock()


# ---- 请求/响应模型 ----

class AgentChatRequest(BaseModel):
    message: str
    use_library: bool = False
    web_search: bool = False
    # @ 引用上下文：[{"type": "skill|memory|tool|module", "name": "..."}]
    contexts: list[dict] = []
    # 可选多轮历史：[{"role": "user|assistant", "content": "..."}]
    history: list[dict] = []


class RecommendRequest(BaseModel):
    text: str


class MemoryWriteRequest(BaseModel):
    content: str
    append: bool = True


class SkillRegisterRequest(BaseModel):
    name: str
    description: str = ""
    trigger_keyword: list[str] = []
    category: str = "custom"
    prompt_template: str = ""
    constraints: str = ""
    enabled: bool = True


class McpSaveRequest(BaseModel):
    name: str
    type: str = "http"          # http | stdio
    url: str = ""
    command: str = ""
    args: list[str] = []
    enabled: bool = True
    tools: list[dict] = []
    description: str = ""


class GithubImportRequest(BaseModel):
    repo_url: str


class McpCallRequest(BaseModel):
    name: str
    arguments: dict = {}


# ---- 模块目录 & 智能推荐 ----

@router.get("/modules")
def agent_modules():
    """返回产品功能模块目录（供悬浮窗引导）。"""
    return {"modules": modules_mod.catalog()}


@router.post("/recommend")
def recommend(body: RecommendRequest):
    """智能推荐：识别功能意图，返回模块跳转建议与引导步骤。"""
    return modules_mod.recommend(body.text)


# ---- @ 引用上下文（Codex 风格 @ 语法） ----

@router.get("/contexts")
def agent_contexts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """返回可被 @ 引用的对象：Skill / 工具 / 记忆 / 模块。"""
    items: list[dict] = []
    # 1) Skills
    try:
        from research_skills.registry import get_registry

        for s in get_registry().all():
            if not s.get("enabled", True):
                continue
            items.append(
                {
                    "type": "skill",
                    "name": s.get("name", ""),
                    "label": f"技能 · {s.get('name','')}",
                    "description": (s.get("description") or ""),
                    "triggers": s.get("trigger_keyword") or [],
                }
            )
    except Exception:  # noqa: BLE001
        pass
    # 2) 工具
    for name, desc in tools_mod.tool_index():
        items.append(
            {
                "type": "tool",
                "name": name,
                "label": f"工具 · {name}",
                "description": desc,
                "triggers": [],
            }
        )
    # 3) 记忆文件
    memory_mod.ensure_exists(str(user.id))
    for f in memory_mod.list_memories(str(user.id)):
        items.append(
            {
                "type": "memory",
                "name": f["name"],
                "label": f"记忆 · {f['name']}",
                "description": f.get("preview") or "",
                "triggers": [],
            }
        )
    # 4) 模块
    for m in modules_mod.catalog():
        items.append(
            {
                "type": "module",
                "name": m.get("key", ""),
                "label": f"模块 · {m.get('name','')}",
                "description": m.get("description") or "",
                "triggers": m.get("keywords") or [],
            }
        )
    return {"count": len(items), "items": items}


@router.get("/capabilities")
def agent_capabilities(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """返回内置工具 + 已发现 MCP 工具的完整目录（供 Agent 中心展示）。"""
    try:
        from app.agent import mcp_runtime

        return {
            "builtin": tools_mod.tool_catalog(),
            "mcp": mcp_runtime.active_tool_catalog(),
            "total": len(tools_mod.TOOL_REGISTRY),
        }
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"读取工具目录失败：{e}")


# ---- 全局 Agent 对话 ----

@router.post("/chat")
def agent_chat(
    body: AgentChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """全局 Agent 对话（非流式）：记忆注入 + 工具调用 + 智能推荐。"""
    agent = TopAgent(db, user.id, llm=_build_llm(db, user.id))
    out = agent.handle(
        body.message,
        use_library=body.use_library,
        web_search=body.web_search,
        contexts=body.contexts,
        history=body.history,
    )
    return out


@router.post("/chat/stream")
def agent_chat_stream(
    body: AgentChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """全局 Agent 对话（SSE 流式）。

    事件序列：
      1. recommendation —— 智能推荐（关键词即时命中，无需等 LLM）
      2. tool_trace     —— 实际调用的工具轨迹
      3. delta          —— 回答文本分块
      4. done           —— 结束
    """
    agent = TopAgent(db, user.id, llm=_build_llm(db, user.id))
    # 先做即时智能推荐（不依赖 LLM，秒出）
    recommendation = modules_mod.recommend(body.message)

    def gen():
        yield f"data: {json.dumps({'recommendation': recommendation})}\n\n"
        try:
            out = agent.handle(
                body.message,
                use_library=body.use_library,
                web_search=body.web_search,
                contexts=body.contexts,
                history=body.history,
            )
        except Exception as exc:  # noqa: BLE001
            # 把真实错误作为 delta 输出，避免流中断后前端只显示笼统错误
            yield f"data: {json.dumps({'delta': f'⚠️ 处理失败：{exc}'})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
            return
        yield f"data: {json.dumps({'tool_trace': out.get('tool_trace') or []})}\n\n"
        full = out.get("answer", "")
        if not full:
            full = "（助手暂未生成回答）"
        for i in range(0, len(full), 8):
            yield f"data: {json.dumps({'delta': full[i : i + 8]})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/chat/events")
def agent_chat_events(
    body: AgentChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """全局 Agent 实时事件流：route / thinking / tool_start / tool_result / answer。"""
    agent = TopAgent(db, user.id, llm=_build_llm(db, user.id))
    recommendation = modules_mod.recommend(body.message)

    def gen():
        yield f"data: {json.dumps({'type': 'recommendation', 'recommendation': recommendation})}\n\n"
        try:
            for ev in agent.event_stream(
                body.message,
                use_library=body.use_library,
                web_search=body.web_search,
                contexts=body.contexts,
                history=body.history,
            ):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---- 长期记忆（本地 MD，跨对话共享） ----

@router.get("/memory")
def list_memory(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    memory_mod.ensure_exists(str(user.id))
    return {"files": memory_mod.list_memories(str(user.id))}


@router.get("/memory/{name}")
def get_memory(name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    content = memory_mod.read_memory(str(user.id), name)
    if not content:
        raise HTTPException(status_code=404, detail="记忆文件不存在或为空")
    return {"name": name, "content": content}


@router.post("/memory/{name}")
def write_memory(
    name: str,
    body: MemoryWriteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    info = memory_mod.write_memory(str(user.id), name, body.content, append=body.append)
    return {"ok": True, **info}


# ---- Skill 配置（自定义技能） ----

@router.get("/skills")
def list_skills(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出全部 Skill（内置 + 自定义）。"""
    try:
        from research_skills.registry import get_registry

        skills = get_registry().all()
        return {"count": len(skills), "skills": skills}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"读取 Skill 失败：{e}")


@router.post("/skills")
def register_skill(
    body: SkillRegisterRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """注册/更新一个自定义 Skill。"""
    try:
        from research_skills.registry import get_registry

        skill = {
            "name": body.name,
            "description": body.description,
            "trigger_keyword": body.trigger_keyword,
            "category": body.category,
            "prompt_template": body.prompt_template,
            "constraints": body.constraints,
            "enabled": body.enabled,
            "github_source": "custom",
        }
        reg = get_registry()
        reg.register(skill)
        return {"ok": True, "skill": skill}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"注册失败：{e}")


@router.delete("/skills/{name}")
def unregister_skill(name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        from research_skills.registry import get_registry

        ok = get_registry().unregister(name)
        if not ok:
            raise HTTPException(status_code=404, detail="Skill 不存在")
        return {"ok": True, "name": name}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"注销失败：{e}")


@router.post("/skills/upload")
async def upload_skill(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """上传 SKILL.md / 代码文件 / zip / tar.gz 压缩包并自动注册。"""
    try:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="文件为空")
        skills = skill_store.extract_skills(data, file.filename or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"解析失败：{e}")

    from research_skills.registry import get_registry

    reg = get_registry()
    registered = []
    for skill in skills:
        if not skill.get("github_source"):
            skill["github_source"] = "upload"
        reg.register(skill)
        registered.append(skill)
    return {"ok": True, "count": len(registered), "skills": registered}


@router.get("/skills/github/search")
def search_github_skills(
    q: str = "",
    limit: int = 8,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """搜索 GitHub 上符合 Agent Skills 规范的仓库。"""
    try:
        return {"items": skill_store.search_github(q, limit)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/skills/github/import")
def import_github_skill(
    body: GithubImportRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """从 GitHub 仓库自动导入并注册 Skill。"""
    try:
        skills = skill_store.import_github(body.repo_url)
        return {"ok": True, "count": len(skills), "skills": skills}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"导入失败：{e}")


# ---- MCP 配置 ----

@router.get("/mcp")
def list_mcp(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"servers": mcp_store.list_servers()}


@router.post("/mcp")
def save_mcp(body: McpSaveRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        server = mcp_store.save_server(body.model_dump())
        return {"ok": True, "server": server}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/mcp/{name}")
def delete_mcp(name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ok = mcp_store.remove_server(name)
    if not ok:
        raise HTTPException(status_code=404, detail="MCP 服务器不存在")
    return {"ok": True, "name": name}


@router.post("/mcp/test/{name}")
def test_mcp(name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return mcp_store.test_server(name)


@router.post("/mcp/{name}/discover")
def discover_mcp(name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """连接 MCP 服务器发现工具，并把动态工具注册进 Agent 工具表。"""
    from app.agent import mcp_runtime

    return mcp_runtime.refresh_server(name)


@router.get("/mcp/{name}/tools")
def list_mcp_tools(name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """返回某 MCP 服务器已缓存/已发现的工具清单。"""
    server = mcp_store.get_server(name)
    if not server:
        raise HTTPException(status_code=404, detail="MCP 服务器不存在")
    tools = server.get("tools") or []
    return {"name": name, "count": len(tools), "tools": tools}


@router.post("/mcp/{name}/call")
def call_mcp_tool(
    name: str,
    body: McpCallRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """直接调用 MCP 服务器上的某个工具（供界面/联调使用）。"""
    from app.agent import mcp_runtime

    return mcp_runtime.call_tool(name, body.name, body.arguments or {})


@router.post("/mcp/upload")
async def upload_mcp(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """上传 MCP 服务器 JSON 配置（.json / .mcp.json）并注册。"""
    try:
        raw = await file.read()
        cfg = json.loads(raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"不是有效的 JSON 配置：{e}")

    # 兼容多种格式：{mcpServers: {...}} / [server, ...] / {name, type, url, ...}
    servers: list[dict] = []
    if isinstance(cfg, dict):
        if "mcpServers" in cfg and isinstance(cfg["mcpServers"], dict):
            for name, s in cfg["mcpServers"].items():
                if isinstance(s, dict):
                    servers.append(_normalize_mcp(name, s))
        elif "name" in cfg:
            servers.append(_normalize_mcp(str(cfg.get("name", "mcp")), cfg))
        else:
            # 单服务器键值对（键为服务器名）
            for name, s in cfg.items():
                if isinstance(s, dict):
                    servers.append(_normalize_mcp(name, s))
    elif isinstance(cfg, list):
        for s in cfg:
            if isinstance(s, dict):
                servers.append(_normalize_mcp(str(s.get("name", "mcp")), s))

    if not servers:
        raise HTTPException(status_code=400, detail="配置中未找到 MCP 服务器定义")

    saved = []
    for s in servers:
        try:
            saved.append(mcp_store.save_server(s))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "count": len(saved), "servers": saved}


def _normalize_mcp(name: str, cfg: dict) -> dict:
    if isinstance(cfg.get("url"), str) or isinstance(cfg.get("base_url"), str):
        return {
            "name": name,
            "type": "http",
            "url": cfg.get("url") or cfg.get("base_url") or "",
            "command": "",
            "args": cfg.get("args") or [],
            "enabled": bool(cfg.get("enabled", True)),
            "tools": cfg.get("tools") or cfg.get("capabilities") or [],
            "description": cfg.get("description") or "",
        }
    return {
        "name": name,
        "type": "stdio",
        "url": "",
        "command": cfg.get("command") or "",
        "args": cfg.get("args") or [],
        "enabled": bool(cfg.get("enabled", True)),
        "tools": cfg.get("tools") or [],
        "description": cfg.get("description") or "",
    }


# ---- 插件生态 ----

@router.get("/plugins")
def list_plugins(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出全部已安装插件及其激活状态。"""
    return {"plugins": get_plugin_manager().list_plugins()}


@router.post("/plugins/install")
async def install_plugin(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """上传插件 zip 包并安装激活（zip 根或其唯一子目录需含 plugin.json）。"""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    try:
        result = get_plugin_manager().install_from_zip(data)
        return result
    except PluginError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"安装失败：{e}")


@router.post("/plugins/{name}/enable")
def enable_plugin(name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """启用并激活插件。"""
    try:
        info = get_plugin_manager().set_enabled(name, enabled=True)
        return {"ok": True, "name": name, **info}
    except PluginError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"启用失败：{e}")


@router.post("/plugins/{name}/disable")
def disable_plugin(name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """停用插件（反注册其技能/工具/MCP 配置）。"""
    try:
        info = get_plugin_manager().set_enabled(name, enabled=False)
        return {"ok": True, "name": name, **info}
    except PluginError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"停用失败：{e}")


@router.delete("/plugins/{name}")
def uninstall_plugin(name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """卸载插件（反注册全部能力并删除目录）。"""
    ok = get_plugin_manager().uninstall(name)
    if not ok:
        raise HTTPException(status_code=404, detail="插件不存在")
    return {"ok": True, "name": name}
