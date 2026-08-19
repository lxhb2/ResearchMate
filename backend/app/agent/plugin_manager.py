"""插件生态管理器：发现 / 安装 / 启用 / 卸载插件，并把插件能力接入 Agent。

插件目录结构（storage/agent/plugins/<name>/）：

  plugin.json          插件清单（必需）
  skills/<dir>/SKILL.md        插件提供的技能（Agent Skills 标准）
  tools/<module>.py            插件提供的工具模块
  mcp.json                     插件附带的 MCP 服务器配置

plugin.json 清单格式：

  {
    "name": "my-plugin",             // 唯一标识（目录名）
    "version": "1.0.0",
    "display_name": "我的插件",
    "description": "插件说明",
    "author": "…",
    "provides": {
      "skills": ["skills"],          // 相对插件根的技能目录（递归扫描 SKILL.md）
      "tools": ["tools/my_tools.py"],// 相对插件根的工具模块
      "mcp": ["mcp.json"]            // 相对插件根的 MCP 配置文件
    }
  }

工具模块契约（不 import 应用内部代码，保持自包含）：

  TOOLS = [
      {
          "name": "my_tool",
          "description": "工具说明（给 LLM 看）",
          "parameters": {…JSON Schema…},
          "handler": lambda ctx, args: {...},   # ctx: ToolContext, args: dict
      },
  ]

生命周期：
  install(zip|dir) -> 复制到插件目录并激活
  activate()   -> 注册技能（registry）/ 工具（TOOL_REGISTRY）/ MCP（mcp_store）
  deactivate() -> 反注册以上全部
  set_enabled()/uninstall()
"""
import importlib.util
import json
import os
import re
import shutil
import zipfile
from typing import Any, Optional

from app.config import settings as app_settings

PLUGINS_DIR = os.path.join(app_settings.STORAGE_DIR, "agent", "plugins")

# 注册表中标记「来自插件」的字段
PLUGIN_SOURCE_FIELD = "plugin_source"


class PluginError(ValueError):
    """插件操作失败（清单缺失/格式错误/目录非法等）。"""


def _plugin_dir(name: str) -> str:
    return os.path.join(PLUGINS_DIR, name)


def _read_manifest(pdir: str) -> dict:
    mf = os.path.join(pdir, "plugin.json")
    if not os.path.isfile(mf):
        raise PluginError("缺少 plugin.json 清单文件")
    try:
        with open(mf, encoding="utf-8") as f:
            m = json.load(f)
    except json.JSONDecodeError as e:
        raise PluginError(f"plugin.json 不是合法 JSON：{e}") from e
    name = str(m.get("name", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-_]{0,63}", name):
        raise PluginError("清单 name 非法（仅允许字母数字连字符下划线，≤64 字符）")
    if name != os.path.basename(pdir.rstrip("/")):
        raise PluginError("清单 name 必须与插件目录名一致")
    m.setdefault("version", "0.0.0")
    m.setdefault("display_name", name)
    m.setdefault("description", "")
    m.setdefault("author", "")
    m.setdefault("provides", {})
    if not isinstance(m["provides"], dict):
        raise PluginError("provides 必须是对象")
    m.setdefault("enabled", True)
    return m


# ---------------------------------------------------------------------------
# 插件能力激活：技能 / 工具 / MCP
# ---------------------------------------------------------------------------

def _plugin_skills(pdir: str, manifest: dict) -> list[str]:
    """扫描插件声明的技能目录，返回技能名列表（不注册）。"""
    from research_skills import parser as skill_parser

    names = []
    for rel in manifest["provides"].get("skills", []) or []:
        base = os.path.join(pdir, rel)
        if not os.path.isdir(base):
            continue
        for root, _dirs, files in os.walk(base):
            if "SKILL.md" not in files:
                continue
            try:
                skill = skill_parser.parse_skill_dir(root)
                names.append(skill["name"])
            except skill_parser.SkillParseError:
                continue
    return names


def _activate_skills(pdir: str, manifest: dict) -> list[str]:
    """把插件技能注册进 Skill 注册表（带 plugin_source 标记）。"""
    from research_skills import parser as skill_parser
    from research_skills.registry import get_registry

    reg = get_registry()
    registered: list[str] = []
    for rel in manifest["provides"].get("skills", []) or []:
        base = os.path.join(pdir, rel)
        if not os.path.isdir(base):
            continue
        for root, _dirs, files in os.walk(base):
            if "SKILL.md" not in files:
                continue
            try:
                skill = skill_parser.parse_skill_dir(root)
            except skill_parser.SkillParseError:
                continue
            skill[PLUGIN_SOURCE_FIELD] = manifest["name"]
            skill.setdefault("category", "plugin")
            reg.register(skill)
            registered.append(skill["name"])
    return registered


def _deactivate_skills(manifest: dict) -> list[str]:
    """反注册某插件的全部技能。"""
    from research_skills.registry import get_registry

    reg = get_registry()
    removed = [
        s["name"]
        for s in reg.all()
        if s.get(PLUGIN_SOURCE_FIELD) == manifest["name"]
    ]
    for name in removed:
        reg.unregister(name)
    return removed


def _load_tool_module(path: str):
    """以独立模块名导入插件工具模块（不污染 sys.modules 常驻命名）。"""
    mod_name = "plugin_tool_" + re.sub(r"\W+", "_", path)
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise PluginError(f"无法加载工具模块：{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _activate_tools(pdir: str, manifest: dict) -> list[str]:
    """把插件工具注册进工具注册表。返回工具名列表。"""
    from app.agent import tools as tools_mod

    registered: list[str] = []
    for rel in manifest["provides"].get("tools", []) or []:
        path = os.path.join(pdir, rel)
        if not os.path.isfile(path):
            continue
        try:
            mod = _load_tool_module(path)
        except Exception as e:  # noqa: BLE001
            raise PluginError(f"工具模块加载失败 {rel}：{e}") from e
        tool_defs = getattr(mod, "TOOLS", None)
        if not isinstance(tool_defs, list):
            raise PluginError(f"工具模块 {rel} 未定义 TOOLS 列表")
        for td in tool_defs:
            try:
                tool = tools_mod.Tool(
                    name=str(td["name"]),
                    description=str(td.get("description", "")),
                    parameters=td.get("parameters") or {"type": "object", "properties": {}, "required": []},
                    handler=td["handler"],
                )
            except (KeyError, TypeError) as e:
                raise PluginError(f"工具定义不完整 {rel}：{e}") from e
            tools_mod.register_tool(tool, source=manifest["name"])
            registered.append(tool.name)
    return registered


def _deactivate_tools(manifest: dict) -> list[str]:
    """反注册某插件的全部工具。"""
    from app.agent import tools as tools_mod

    return tools_mod.unregister_tools_by_source(manifest["name"])


def _activate_mcp(pdir: str, manifest: dict) -> list[str]:
    """把插件附带的 MCP 服务器配置合并进 MCP 存储（带 plugin 标记）。"""
    from app.agent import mcp_store

    saved: list[str] = []
    for rel in manifest["provides"].get("mcp", []) or []:
        path = os.path.join(pdir, rel)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise PluginError(f"MCP 配置不合法 {rel}：{e}") from e
        servers: list[tuple[str, dict]] = []
        if isinstance(data.get("mcpServers"), dict):
            # {"mcpServers": {"名称": {...}}}：名称是字典键
            servers = list(data["mcpServers"].items())
        elif isinstance(data, list):
            servers = [(str(s.get("name", "")), s) for s in data if isinstance(s, dict)]
        elif isinstance(data, dict):
            servers = [(str(data.get("name", "")), data)]
        for server_name, s in servers:
            if not isinstance(s, dict):
                continue
            s = dict(s)
            s.setdefault("name", server_name)
            if not s.get("name"):
                continue
            s[PLUGIN_SOURCE_FIELD] = manifest["name"]
            mcp_store.save_server(s)
            saved.append(s["name"])
    return saved


def _deactivate_mcp(manifest: dict) -> list[str]:
    """移除某插件提供的全部 MCP 服务器配置。"""
    from app.agent import mcp_store

    removed = []
    for s in mcp_store.list_servers():
        if s.get(PLUGIN_SOURCE_FIELD) == manifest["name"]:
            if mcp_store.remove_server(s["name"]):
                removed.append(s["name"])
    return removed


# ---------------------------------------------------------------------------
# PluginManager
# ---------------------------------------------------------------------------

class PluginManager:
    """插件生命周期管理（进程内单例）。"""

    def __init__(self, plugins_dir: str = ""):
        self.plugins_dir = plugins_dir or PLUGINS_DIR
        self._activated: dict[str, dict] = {}  # name -> {"skills": [...], "tools": [...], "mcp": [...]}

    # ---- 查询 ----

    def list_plugins(self) -> list[dict]:
        """列出全部插件及其状态（含激活的能力清单）。"""
        out: list[dict] = []
        if not os.path.isdir(self.plugins_dir):
            return out
        for name in sorted(os.listdir(self.plugins_dir)):
            pdir = _plugin_dir(name) if self.plugins_dir == PLUGINS_DIR else os.path.join(self.plugins_dir, name)
            if not os.path.isdir(pdir):
                continue
            try:
                m = _read_manifest(pdir)
            except PluginError as e:
                out.append({"name": name, "valid": False, "error": str(e), "enabled": False})
                continue
            out.append(
                {
                    "name": m["name"],
                    "valid": True,
                    "version": m["version"],
                    "display_name": m["display_name"],
                    "description": m["description"],
                    "author": m["author"],
                    "enabled": bool(m.get("enabled", True)),
                    "active": m["name"] in self._activated,
                    "skills": self._activated.get(m["name"], {}).get("skills", []),
                    "tools": self._activated.get(m["name"], {}).get("tools", []),
                    "mcp_servers": self._activated.get(m["name"], {}).get("mcp", []),
                    "error": self._activated.get(m["name"], {}).get("error"),
                }
            )
        return out

    def get_plugin(self, name: str) -> Optional[dict]:
        for p in self.list_plugins():
            if p["name"] == name:
                return p
        return None

    # ---- 生命周期 ----

    def install_from_zip(self, zip_bytes: bytes) -> dict:
        """从 zip 安装插件（zip 根或其唯一子目录需含 plugin.json）。"""
        os.makedirs(self.plugins_dir, exist_ok=True)
        import io

        try:
            zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        except zipfile.BadZipFile as e:
            raise PluginError(f"不是合法 zip：{e}") from e
        names = [n for n in zf.namelist() if not n.endswith("/")]
        if not names:
            raise PluginError("zip 为空")
        # 定位 plugin.json 所在根
        roots = {n.split("/")[0] for n in names}
        manifest_paths = [n for n in names if n.endswith("plugin.json")]
        if not manifest_paths:
            raise PluginError("zip 中未找到 plugin.json")
        mp = min(manifest_paths, key=len)  # 最浅层的那份
        root = os.path.dirname(mp)  # 插件根（相对 zip）
        # 校验清单
        tmp = os.path.join(self.plugins_dir, ".tmp_install")
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        try:
            zf.extractall(tmp)
            src = os.path.join(tmp, root) if root else tmp
            manifest = _read_manifest(src)
            dest = _plugin_dir(manifest["name"])
            if os.path.isdir(dest):
                self.uninstall(manifest["name"])
            shutil.copytree(src, dest)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self._save_manifest_flag(manifest["name"], enabled=True)
        info = self.activate(manifest["name"])
        return {"ok": True, "name": manifest["name"], **info}

    def uninstall(self, name: str) -> bool:
        pdir = _plugin_dir(name)
        if not os.path.isdir(pdir):
            return False
        self.deactivate(name)
        shutil.rmtree(pdir, ignore_errors=True)
        return True

    def set_enabled(self, name: str, enabled: bool) -> dict:
        if enabled:
            self._save_manifest_flag(name, enabled=True)
            return self.activate(name)
        info = self.deactivate(name)
        self._save_manifest_flag(name, enabled=False)
        return info

    # ---- 激活 / 停用 ----

    def activate(self, name: str) -> dict:
        """激活插件：注册其技能 / 工具 / MCP 配置。"""
        pdir = _plugin_dir(name)
        manifest = _read_manifest(pdir)
        if not manifest.get("enabled", True):
            raise PluginError("插件已被禁用，请先启用")
        if name in self._activated:
            return self._activated[name]
        try:
            skills = _activate_skills(pdir, manifest)
            tools = _activate_tools(pdir, manifest)
            mcp = _activate_mcp(pdir, manifest)
        except PluginError as e:
            # 激活失败回滚已注册项
            _deactivate_skills(manifest)
            _deactivate_tools(manifest)
            _deactivate_mcp(manifest)
            self._activated[name] = {"error": str(e)}
            raise
        info = {"skills": skills, "tools": tools, "mcp": mcp, "error": None}
        self._activated[name] = info
        return info

    def deactivate(self, name: str) -> dict:
        pdir = _plugin_dir(name)
        manifest = _read_manifest(pdir)
        info = self._activated.pop(name, {"skills": [], "tools": [], "mcp": []})
        info["skills"] = _deactivate_skills(manifest) or info.get("skills", [])
        info["tools"] = _deactivate_tools(manifest) or info.get("tools", [])
        info["mcp"] = _deactivate_mcp(manifest) or info.get("mcp", [])
        return info

    # ---- 启动装载 ----

    def load_all(self) -> dict:
        """应用启动时装载全部插件（清理孤儿注册后按清单重建）。"""
        os.makedirs(self.plugins_dir, exist_ok=True)
        # 清理上次运行遗留的插件注册（技能注册表持久化在 JSON 里）
        self._prune_orphan_registrations()
        ok, failed = 0, []
        for p in self.list_plugins():
            if not p.get("valid") or not p.get("enabled", True):
                continue
            try:
                self.activate(p["name"])
                ok += 1
            except PluginError as e:
                failed.append({"name": p["name"], "error": str(e)})
        return {"loaded": ok, "failed": failed}

    def _prune_orphan_registrations(self) -> None:
        """移除已不存在插件的遗留注册（技能 / 工具 / MCP）。"""
        from research_skills.registry import get_registry

        reg = get_registry()
        live = {
            p["name"] for p in self.list_plugins() if p.get("valid") and p.get("enabled", True)
        }
        for s in reg.all():
            src = s.get(PLUGIN_SOURCE_FIELD)
            if src and src not in live:
                reg.unregister(s["name"])

        from app.agent import tools as tools_mod, mcp_store

        for t in tools_mod.tools_by_source():
            if t["source"] not in live:
                tools_mod.unregister_tools_by_source(t["source"])
        for s in mcp_store.list_servers():
            src = s.get(PLUGIN_SOURCE_FIELD)
            if src and src not in live:
                mcp_store.remove_server(s["name"])

    # ---- 内部 ----

    def _save_manifest_flag(self, name: str, enabled: bool) -> None:
        pdir = _plugin_dir(name)
        mf = os.path.join(pdir, "plugin.json")
        with open(mf, encoding="utf-8") as f:
            m = json.load(f)
        m["enabled"] = bool(enabled)
        with open(mf, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)


_manager: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    global _manager
    if _manager is None:
        _manager = PluginManager()
    return _manager
