"""SKILL.md 标准格式解析器。

解析 Agent Skills 标准（YAML frontmatter + Markdown 正文），提取每个 skill 的：
  触发条件(trigger)、系统提示(system_prompt)、输入参数(input_schema)、
  输出格式(output_schema)、约束规则(constraints)。

不整仓引用外部仓库源码，只按本解析器约定读取每个 skill 目录下的 SKILL.md。
兼容两种来源：
  1. 本项目内置 templates/ 下的 SKILL.md（推荐，字段完整）；
  2. 用户从 GitHub 下载的任意符合 Agent Skills 规范的 SKILL.md 目录。
"""
import os
import re
from typing import Any


class SkillParseError(ValueError):
    pass


def split_frontmatter(text: str) -> tuple[dict, str]:
    """把 SKILL.md 文本拆成 (frontmatter_dict, body_markdown)。"""
    text = (text or "").lstrip("\ufeff")
    if not text.startswith("---"):
        return {}, text
    m = re.match(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?", text, re.S)
    if not m:
        return {}, text
    fm = m.group(1)
    body = text[m.end() :]
    return _parse_frontmatter(fm), body


def _parse_frontmatter(fm: str) -> dict:
    """极简 YAML 前置信息解析（支持嵌套块映射与块列表，够用于 SKILL.md 元数据）。"""
    try:
        import yaml  # type: ignore
    except ImportError:  # 无 PyYAML 时的降级
        return _mini_yaml(fm)
    try:
        data = yaml.safe_load(fm)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return _mini_yaml(fm)


def _mini_yaml(fm: str) -> dict:
    """无 PyYAML 的最小解析：处理 'key: value' 与带缩进的子项。"""
    out: dict = {}
    lines = fm.splitlines()
    stack: list[tuple[int, str, list]] = []  # (indent, key, container)
    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        if indent == 0:
            if ":" in line:
                k, v = line.split(":", 1)
                k, v = k.strip(), v.strip()
                if v:
                    out[k] = _scalar(v)
                    stack = []
                else:
                    out[k] = []
                    stack = [(0, k, out[k])]
            else:
                stack = []
        else:
            if stack:
                parent = stack[-1]
                if line.startswith("- "):  # 列表项
                    parent[2].append(_scalar(line[2:].strip()))
                elif ":" in line:
                    k, v = line.split(":", 1)
                    k, v = k.strip(), v.strip()
                    item = parent[2][-1] if parent[2] and isinstance(parent[2][-1], dict) else {}
                    if not isinstance(item, dict):
                        item = {}
                        parent[2].append(item)
                    item[k] = _scalar(v) if v else {}
    return out


def _scalar(v: str) -> Any:
    v = v.strip().strip("'\"")
    low = v.lower()
    if not v:
        return ""
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "none"):
        return None
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d+\.\d+", v):
        return float(v)
    # 内联列表 [a, b, c]
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1]
        return [x.strip() for x in inner.split(",") if x.strip()]
    return v


# ---- 正文 section 提取 ----

_SECTION_RE = re.compile(r"^#{1,4}\s+(.+?)\s*$", re.M)


def _sections(body: str) -> dict[str, str]:
    """按标题把正文切成 {标题: 内容}。"""
    matches = list(_SECTION_RE.finditer(body))
    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        out[title.lower()] = body[start:end].strip()
    return out


def _extract_trigger(body: str, sections: dict[str, str]) -> list[str]:
    """从 Trigger Keywords / When to Use 等段落提取触发关键词。"""
    keywords: list[str] = []
    for key in ("trigger keywords", "triggers", "when to use", "description"):
        sec = sections.get(key)
        if not sec:
            continue
        keywords.extend(re.findall(r"(?:^|\n)\s*[-*]\s*([^\n]+)", sec))
        # 也抓取逗号/顿号分隔的词
        for frag in re.findall(r"[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9_\- ]{1,40}", sec):
            frag = frag.strip()
            if 2 <= len(frag) <= 40 and frag not in keywords:
                keywords.append(frag)
    return [_k for _k in keywords if _k][:60]


def _find_section(sections: dict[str, str], *names: str) -> str:
    for n in names:
        for k, v in sections.items():
            if any(token in k for token in n.split()):
                return v
    return ""


def parse_skill_dir(path: str) -> dict:
    """解析一个 skill 目录（含 SKILL.md），返回标准化的 skill 元数据。"""
    md = os.path.join(path, "SKILL.md")
    if not os.path.isfile(md):
        raise SkillParseError(f"{path} 下缺少 SKILL.md")
    with open(md, encoding="utf-8") as f:
        text = f.read()
    fm, body = split_frontmatter(text)
    sections = _sections(body)

    name = str(fm.get("name") or os.path.basename(path)).strip()
    description = str(fm.get("description", "")).strip()
    metadata = fm.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    meta = {str(k): v for k, v in metadata.items()}

    # 触发条件：优先 frontmatter/metadata，其次正文
    trigger_raw = meta.get("trigger_keyword") or fm.get("trigger_keyword")
    if isinstance(trigger_raw, str):
        triggers = [t.strip() for t in re.split(r"[,，;；]", trigger_raw) if t.strip()]
    elif isinstance(trigger_raw, list):
        triggers = [str(t) for t in trigger_raw]
    else:
        triggers = _extract_trigger(body, sections)

    # 系统提示：正文 System Prompt 段，否则整段正文
    system_prompt = _find_section(sections, "system prompt", "instructions", "workflow")
    if not system_prompt:
        system_prompt = body.strip()

    return {
        "name": name,
        "github_source": str(meta.get("github_source", "")).strip(),
        "trigger_keyword": triggers,
        "description": description,
        "prompt_template": system_prompt,
        "input_schema": meta.get("input_schema") or _find_section(sections, "input parameters", "input"),
        "output_schema": meta.get("output_schema") or _find_section(sections, "output format", "output"),
        "category": str(meta.get("category", "research_closed_loop")).strip(),
        "constraints": _find_section(sections, "constraints", "constraint", "rules", "limitations"),
        "version": str(meta.get("version", "")),
        "enabled": str(meta.get("enabled", "true")).lower() not in ("false", "0", "no"),
    }


def parse_skill_md_text(text: str, default_name: str = "") -> dict:
    """从 SKILL.md 文本直接解析（供测试/调试）。"""
    fm, body = split_frontmatter(text)
    sections = _sections(body)
    name = str(fm.get("name") or default_name).strip()
    metadata = fm.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    meta = {str(k): v for k, v in metadata.items()}
    trigger_raw = meta.get("trigger_keyword") or fm.get("trigger_keyword")
    if isinstance(trigger_raw, str):
        triggers = [t.strip() for t in re.split(r"[,，;；]", trigger_raw) if t.strip()]
    elif isinstance(trigger_raw, list):
        triggers = [str(t) for t in trigger_raw]
    else:
        triggers = _extract_trigger(body, sections)
    return {
        "name": name,
        "github_source": str(meta.get("github_source", "")).strip(),
        "trigger_keyword": triggers,
        "description": str(fm.get("description", "")).strip(),
        "prompt_template": _find_section(sections, "system prompt", "instructions", "workflow") or body.strip(),
        "input_schema": meta.get("input_schema") or _find_section(sections, "input parameters", "input"),
        "output_schema": meta.get("output_schema") or _find_section(sections, "output format", "output"),
        "category": str(meta.get("category", "research_closed_loop")).strip(),
        "constraints": _find_section(sections, "constraints", "constraint", "rules", "limitations"),
        "version": str(meta.get("version", "")),
        "enabled": str(meta.get("enabled", "true")).lower() not in ("false", "0", "no"),
    }