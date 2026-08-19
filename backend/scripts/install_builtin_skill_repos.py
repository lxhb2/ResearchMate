"""把 6 个官方 Skill 仓库安装为 Agent 自带（内置默认）技能。

用法：
  .venv/bin/python scripts/install_builtin_skill_repos.py

流程：
  1. 读取 /tmp/skill_repos 下已下载的仓库 zip（缺失的自动跳过并提示）；
  2. 解析每个仓库的 SKILL.md（Agent Skills 标准 frontmatter），写入
     research_skills/templates/<name>/SKILL.md —— 成为「内置默认技能」，
     重建注册表（--rebuild-registry）时也会自动加载；
  3. 命名冲突：已存在的内置技能名优先，仓库版加 `-<repo标记>` 后缀；
  4. 补齐触发关键词（中英双语映射）与五大科研分类，重建注册表。

官方 Skill 仓库（按集成顺序）：
  1. Imbad0202/academic-research-skills      （42.9k star）
  2. K-Dense-AI/scientific-agent-skills      （33.8k star）
  3. Yuan1z0825/nature-skills                （34k star）
  4. fcakyon/phd-skills                      （368 star）
  5. Orchestra-Research/AI-research-SKILLs   （11.8k star）
  6. HKUSTDial/Supervisor-Skills             （5.7k star）
"""
import json
import os
import re
import sys
import zipfile

import yaml

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

TEMPLATES_DIR = os.path.join(BACKEND, "research_skills", "templates")
REPO_ZIP_DIR = os.environ.get("SKILL_REPO_ZIP_DIR", "/tmp/skill_repos")

# (GitHub 仓库, zip 文件名, 冲突后缀标记)
REPOS = [
    ("Imbad0202/academic-research-skills", "Imbad0202_academic-research-skills.zip", "ars"),
    ("K-Dense-AI/scientific-agent-skills", "K-Dense-AI_scientific-agent-skills.zip", "sas"),
    ("Yuan1z0825/nature-skills", "Yuan1z0825_nature-skills.zip", "nature"),
    ("fcakyon/phd-skills", "fcakyon_phd-skills.zip", "phd"),
    ("Orchestra-Research/AI-research-SKILLs", "Orchestra-Research_AI-research-SKILLs.zip", "orch"),
    ("HKUSTDial/Supervisor-Skills", "HKUSTDial_Supervisor-Skills.zip", "sup"),
]

# 英文关键词 -> 中文触发词映射（让英文技能可被中文查询命中）
_CN_KEYWORDS = {
    "paper": ["论文"], "writing": ["写作"], "write": ["写作"], "draft": ["起草"],
    "manuscript": ["稿件"], "abstract": ["摘要"], "polish": ["润色"], "revise": ["修改"],
    "review": ["评审", "审稿"], "peer": ["同行评审"], "referee": ["审稿"],
    "literature": ["文献"], "search": ["检索"], "citation": ["引用", "参考文献"],
    "cite": ["引用"], "reader": ["阅读"], "read": ["阅读"],
    "experiment": ["实验"], "ablation": ["消融实验"], "baseline": ["基线"],
    "reproduce": ["复现"], "reproducib": ["复现"],
    "hypothesis": ["假设"], "idea": ["选题", "想法"], "topic": ["选题"],
    "evaluate": ["评估"], "evaluation": ["评估"],
    "data": ["数据"], "dataset": ["数据集"], "statistics": ["统计"], "statistical": ["统计"],
    "figure": ["图表", "绘图"], "chart": ["图表"], "plot": ["绘图"],
    "ppt": ["幻灯片"], "slides": ["幻灯片"], "presentation": ["演示"],
    "translate": ["翻译"], "translation": ["翻译"],
    "proposal": ["开题", "申请书"], "grant": ["基金申请"],
    "publish": ["投稿"], "submission": ["投稿"], "submit": ["投稿"],
    "research": ["科研"], "survey": ["综述"], "综述": ["综述"],
    "downloader": ["下载"], "download": ["下载"],
    "patent": ["专利"], "response": ["答辩", "回复审稿"],
    "training": ["训练"], "fine-tun": ["微调"], "finetun": ["微调"],
    "interpret": ["可解释性"], "tokeniz": ["分词"],
}

# 分类启发：关键词 -> 五大科研分类
_CATEGORY_RULES = [
    ("literature", ["literature", "search", "citation", "cite", "reader", "survey",
                    "arxiv", "download", "文献", "检索", "引用"]),
    ("paper_writing", ["writing", "write", "draft", "manuscript", "paper", "abstract",
                       "polish", "revise", "proposal", "grant", "latex", "ppt", "slide",
                       "presentation", "figure", "chart", "plot", "patent", "response",
                       "writing", "论文", "写作", "投稿"]),
    ("experiment_review", ["review", "referee", "experiment", "ablation", "baseline",
                           "reproduce", "verify", "verification", "debug", "评审", "实验", "复现"]),
    ("idea_evaluate", ["hypothesis", "idea", "topic", "evaluate", "evaluation",
                       "选题", "假设", "评估"]),
]

_STOP_WORDS = {
    "use", "used", "using", "this", "that", "these", "those", "skill", "skills",
    "whenever", "when", "the", "a", "an", "and", "or", "of", "to", "in", "on",
    "for", "with", "from", "into", "such", "as", "it", "its", "is", "are", "be",
    "you", "your", "user", "users", "wants", "want", "needs", "need", "any",
    "anything", "something", "includes", "include", "including", "via", "by",
    "at", "if", "then", "also", "can", "will", "should", "help", "helps",
    "when", "how", "what", "why", "which", "who", "turn", "into", "any",
}


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff-]+", "-", (name or "").strip().lower())[:60] or "skill"


def _derive_category(name: str, description: str) -> str:
    text = f"{name} {description}".lower()
    for category, kws in _CATEGORY_RULES:
        if any(k in text for k in kws):
            return category
    return "research_closed_loop"


def _derive_triggers(name: str, description: str) -> list[str]:
    """从技能名与描述推导双语触发词（保证 @ 引用 / 中文关键词可命中）。"""
    out: list[str] = []
    if name:
        out.append(name.lower())
        if "-" in name or "_" in name:
            out.append(re.sub(r"[-_]", " ", name).lower())
    text = f"{name} {description}".lower()
    # 中文触发词映射
    for en, cn_terms in _CN_KEYWORDS.items():
        if en in text:
            for cn in cn_terms:
                if cn not in out:
                    out.append(cn)
    # 英文实义词
    for w in re.findall(r"\b[a-z][a-z0-9\-]{2,}\b", description.lower()):
        if w in _STOP_WORDS or w in out:
            continue
        out.append(w)
        if len(out) >= 12:
            break
    return out[:12]


def _iter_repo_skills(zip_path: str):
    """产出 zip 内 (相对路径, SKILL.md 文本)。跳过明显非技能目录。"""
    zf = zipfile.ZipFile(zip_path)
    for n in sorted(zf.namelist()):
        if not n.endswith("SKILL.md"):
            continue
        low = n.lower()
        if any(seg in low for seg in ("node_modules/", ".github/", "__pycache__/", "docs/", "example")):
            # example 目录里可能是示例技能骨架，跳过避免噪音
            if "example" in low:
                continue
        yield n, zf.read(n).decode("utf-8", "replace")


def install_repo(repo: str, zip_path: str, tag: str, taken: set[str]) -> tuple[int, list[str]]:
    """安装一个仓库的全部技能，返回 (成功数, 被改名的技能)。"""
    from research_skills import parser

    installed, renamed = 0, []
    for path, text in _iter_repo_skills(zip_path):
        fm, body = parser.split_frontmatter(text)
        if not isinstance(fm, dict):
            fm = {}
        raw_name = str(fm.get("name") or "").strip()
        if not raw_name:
            # 从路径取：xxx/SKILL.md 的上级目录名
            raw_name = path.split("/")[-2] if "/" in path else "skill"
        name = _safe_name(raw_name)
        # 命名冲突：加仓库标记后缀
        final = name
        if final in taken:
            final = _safe_name(f"{name}-{tag}")
            if final in taken:
                continue
            renamed.append(f"{name} -> {final}")
        taken.add(final)

        desc = str(fm.get("description") or "").strip()
        fm["name"] = final
        fm["description"] = desc
        fm.pop("trigger_keyword", None)
        fm["metadata"] = {
            "github_source": f"https://github.com/{repo}",
            "category": _derive_category(name, desc),
            "trigger_keyword": _derive_triggers(name, desc),
            # 上游仓库技能的正文即完整指令文档：解析时保留全文作为 prompt
            "prompt_mode": "full",
            "enabled": "true",
        }

        tdir = os.path.join(TEMPLATES_DIR, final)
        os.makedirs(tdir, exist_ok=True)
        front = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, width=10**6, default_flow_style=False)
        with open(os.path.join(tdir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("---\n" + front + "---\n\n" + body.strip() + "\n")
        installed += 1
    return installed, renamed


def _remove_previously_installed(taken: set[str]) -> int:
    """移除此前由本脚本安装的仓库技能模板（幂等重装），返回移除数。

    识别方式：frontmatter.metadata.github_source 是本脚本的完整 URL 形式
    （https://github.com/<repo>），与手写模板的裸仓库名（owner/repo）区分。
    """
    import shutil

    from research_skills import parser

    repo_urls = {f"https://github.com/{r}" for r, _t, _s in REPOS}
    removed = 0
    for d in sorted(taken):
        md = os.path.join(TEMPLATES_DIR, d, "SKILL.md")
        if not os.path.isfile(md):
            continue
        try:
            fm, _body = parser.split_frontmatter(open(md, encoding="utf-8").read())
            meta = fm.get("metadata") or {}
            if isinstance(meta, dict) and str(meta.get("github_source", "")) in repo_urls:
                shutil.rmtree(os.path.join(TEMPLATES_DIR, d), ignore_errors=True)
                removed += 1
        except Exception:  # noqa: BLE001
            continue
    return removed


def main() -> None:
    taken = {
        d for d in os.listdir(TEMPLATES_DIR)
        if os.path.isfile(os.path.join(TEMPLATES_DIR, d, "SKILL.md"))
    }
    reset = "--reset" in sys.argv
    if reset:
        removed = _remove_previously_installed(taken)
        taken = {
            d for d in os.listdir(TEMPLATES_DIR)
            if os.path.isfile(os.path.join(TEMPLATES_DIR, d, "SKILL.md"))
        }
        print(f"已移除此前安装的仓库技能模板: {removed} 个")
    print(f"已有内置模板: {len(taken)} 个")

    total, missing = 0, []
    for repo, zip_name, tag in REPOS:
        zip_path = os.path.join(REPO_ZIP_DIR, zip_name)
        print(f"\n=== {repo} ===")
        if not os.path.isfile(zip_path):
            print("  ⚠️ zip 未下载，跳过（可重新下载后重跑）")
            missing.append(repo)
            continue
        try:
            installed, renamed = install_repo(repo, zip_path, tag, taken)
        except zipfile.BadZipFile:
            print("  ⚠️ zip 损坏/未下载完整，跳过")
            missing.append(repo)
            continue
        total += installed
        print(f"  安装 {installed} 个技能" + (f"，改名 {len(renamed)} 个" if renamed else ""))
        for r in renamed:
            print(f"    冲突改名: {r}")

    # 重建注册表（templates 为唯一事实来源）
    from research_skills.registry import get_registry
    reg = get_registry().load(rebuild=True)
    print(f"\n注册表已重建: {len(reg.all())} 个技能（新装 {total} 个）")
    if missing:
        print(f"未安装的仓库: {missing}")


if __name__ == "__main__":
    main()
