"""把已安装的真实技能固化为默认模板，并清理注册表/存储中的垃圾条目。

背景：早期从 GitHub 导入 anthropics/skills 仓库做验证时，除约 19 个真实技能外，
还把大量文档碎片（api / streaming / README / THIRD_PARTY_NOTICES 等无 description、
无触发词的非技能 .md）和一个 test-skill 测试产物写进了注册表。本脚本：

1. 识别真实技能 = 内置科研技能 + 有 description 的 anthropics 技能；
2. 把 anthropics 真实技能持久化为 templates/<name>/SKILL.md（重建注册表时也会默认加载）；
3. 重写 skills_registry.json，仅保留真实技能；
4. 清理 storage/agent/skills 下的垃圾目录。

用法：.venv/bin/python scripts/default_skills.py
"""
import json
import os
import re
import shutil
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

REGISTRY_PATH = os.path.join(BACKEND, "research_skills", "skills_registry.json")
TEMPLATES_DIR = os.path.join(BACKEND, "research_skills", "templates")
STORAGE_SKILLS = os.path.join(BACKEND, "storage", "agent", "skills")

BUILTIN_SRC = {
    "Imbad0202/academic-research-skills",
    "K-Dense-AI/scientific-agent-skills",
    "Yuan1z0825/nature-skills",
    "fcakyon/phd-skills",
    "Orchestra-Research/AI-research-SKILLs",
    "HKUSTDial/Supervisor-Skills",
}
# 明确的非技能文件名（仓库说明/法务/模板骨架）
EXPLICIT_JUNK = {"test-skill", "template-skill", "spec", "readme", "third_party_notices"}


def _safe(name: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff-]+", "-", (name or "").strip().lower())[:60] or "skill"


# 推导触发词时忽略的高频无意义词
_STOP_WORDS = {
    "use", "used", "using", "this", "that", "these", "those", "skill", "skills",
    "whenever", "when", "the", "a", "an", "and", "or", "of", "to", "in", "on",
    "for", "with", "from", "into", "such", "as", "it", "its", "is", "are", "be",
    "you", "your", "user", "users", "wants", "want", "needs", "need", "any",
    "anything", "something", "includes", "include", "including", "via", "by",
    "at", "if", "then", "also", "can", "will", "should", "help", "helps",
}


def _derive_triggers(skill: dict) -> list[str]:
    """为缺触发词的技能从 name + description 推导关键词，保证可被 @ / 关键词命中。"""
    trig = [t for t in (skill.get("trigger_keyword") or []) if str(t).strip()]
    if trig:
        return trig[:12]
    out: list[str] = []
    name = (skill.get("name") or "").strip()
    if name:
        out.append(name.lower())
        # 连字符/下划线名拆成词组，如 web-artifacts-builder -> web artifacts builder
        if "-" in name or "_" in name:
            out.append(re.sub(r"[-_]", " ", name).lower())
    desc = (skill.get("description") or "").strip().lower()
    # 按完整单词提取（词边界），过滤停用词，避免截断出 "ting text" 这类碎片
    for w in re.findall(r"\b[a-z][a-z0-9\-]{2,}\b", desc):
        if w in _STOP_WORDS:
            continue
        if w not in out:
            out.append(w)
        if len(out) >= 8:
            break
    return out[:12]


def _yaml_str(v: str) -> str:
    """把字符串安全地写成 YAML 值（含特殊字符时加引号）。"""
    v = (v or "").replace("\r", " ").strip()
    if not v:
        return '""'
    if re.search(r'[:#\[\]{},&*!|>\'"%@`]', v) or v != v.strip():
        return json.dumps(v, ensure_ascii=False)
    return v


def _to_skill_md(skill: dict) -> str:
    """把注册表里的 skill dict 还原为 SKILL.md 文本。"""
    name = skill.get("name", "skill")
    desc = (skill.get("description") or "").strip()
    src = skill.get("github_source") or ""
    category = skill.get("category") or "research_closed_loop"
    version = skill.get("version") or ""
    triggers = _derive_triggers(skill)
    prompt = (skill.get("prompt_template") or "").strip()

    lines = ["---"]
    lines.append(f"name: {name}")
    lines.append(f"description: {_yaml_str(desc)}")
    lines.append("metadata:")
    lines.append(f'  version: {_yaml_str(version)}')
    lines.append(f'  github_source: {_yaml_str(src)}')
    lines.append(f'  category: {_yaml_str(category)}')
    if triggers:
        lines.append("  trigger_keyword:")
        for t in triggers:
            lines.append(f"    - {_yaml_str(str(t))}")
    lines.append('  enabled: "true"')
    lines.append("---")
    lines.append("")
    if triggers:
        lines.append("## Trigger Keywords")
        lines.append(", ".join(str(t) for t in triggers))
        lines.append("")
    lines.append("## System Prompt")
    lines.append(prompt or desc)
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        data = json.load(f)
    skills = data.get("skills", [])

    builtin, genuine, junk = [], [], []
    for s in skills:
        src = s.get("github_source") or ""
        name = (s.get("name") or "").strip()
        desc = (s.get("description") or "").strip()
        if src in BUILTIN_SRC:
            builtin.append(s)
        elif _safe(name) in EXPLICIT_JUNK or name.lower() in EXPLICIT_JUNK or not desc:
            junk.append(s)
        else:
            genuine.append(s)

    print(f"内置科研技能: {len(builtin)}")
    print(f"真实已安装技能(anthropics): {len(genuine)}")
    print(f"垃圾条目(将移除): {len(junk)}")

    # 1) 持久化真实 anthropics 技能为默认模板
    written = 0
    for s in genuine:
        name = _safe(s.get("name", ""))
        tdir = os.path.join(TEMPLATES_DIR, name)
        os.makedirs(tdir, exist_ok=True)
        with open(os.path.join(tdir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(_to_skill_md(s))
        written += 1
    print(f"已写入默认模板: {written}")

    # 2) 重写注册表：仅保留真实技能（内置 + genuine），并补齐触发词
    keep = []
    for s in builtin + genuine:
        s = dict(s)
        s["trigger_keyword"] = _derive_triggers(s)
        s.setdefault("enabled", True)
        keep.append(s)
    data["skills"] = keep
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"注册表已重写，保留技能: {len(keep)}")

    # 3) 清理 storage/agent/skills 垃圾目录（保留与真实技能同名的目录）
    keep_dirs = {_safe(s.get("name", "")) for s in keep}
    removed = 0
    if os.path.isdir(STORAGE_SKILLS):
        for d in os.listdir(STORAGE_SKILLS):
            full = os.path.join(STORAGE_SKILLS, d)
            if os.path.isdir(full) and d not in keep_dirs:
                shutil.rmtree(full, ignore_errors=True)
                removed += 1
    print(f"已清理存储垃圾目录: {removed}")

    # 汇总
    print("\n=== 默认技能清单 ===")
    for s in keep:
        print(f"  - {s['name']:<26} [{s.get('category','')}] trig={len(s.get('trigger_keyword') or [])}")


if __name__ == "__main__":
    main()
