"""Skill 导入器：上传解析（SKILL.md / 代码文件 / zip / tar.gz）与 GitHub 搜索导入。

能力：
- 从上传的 SKILL.md 文本、代码文件、zip/tar.gz 压缩包中提取并解析 skill 定义；
- 从 GitHub 搜索符合 Agent Skills 规范的仓库，并把仓库里的 SKILL.md + 附属代码
  落地到本地 skills 目录后注册进注册表。
"""
import io
import os
import re
import tarfile
import zipfile

import httpx

from research_skills import parser, registry
from app.config import settings as app_settings

# 用户技能落地目录（与系统 storage 一致，便于打包/备份）
SKILLS_DIR = os.path.join(app_settings.STORAGE_DIR, "agent", "skills")


def ensure_dirs() -> None:
    os.makedirs(SKILLS_DIR, exist_ok=True)


def _safe_name(name: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", (name or "").strip().lower())
    return s[:60] or "skill"


def _parse_skill(md_text: str, default_name: str = "") -> dict:
    """解析 SKILL.md 文本，补齐默认字段。"""
    skill = parser.parse_skill_md_text(md_text, default_name)
    if not skill.get("name"):
        skill["name"] = default_name
    skill.setdefault("github_source", "upload")
    skill.setdefault("category", "custom")
    skill.setdefault("constraints", "")
    skill.setdefault("version", "")
    skill.setdefault("enabled", True)
    return skill


def extract_skills(data: bytes, filename: str = "") -> list[dict]:
    """从上传内容提取 skill 列表。

    支持：SKILL.md 文本 / 任意 .md 文本 / .zip / .tar.gz / .tgz。
    压缩包内可含多个 skill 目录（每个目录含 SKILL.md），也可含附属代码文件。
    """
    filename = (filename or "").lower()
    if data.startswith(b"---"):  # 直接是 SKILL.md 文本
        return [_parse_skill(data.decode("utf-8", "replace"))]

    if filename.endswith((".zip",)):
        return _extract_zip(data)
    if filename.endswith((".tar.gz", ".tgz", ".tar")):
        return _extract_tar(data)

    # 兜底：当成纯文本（可能是只有正文的 skill 定义）
    try:
        return [_parse_skill(data.decode("utf-8", "replace"))]
    except Exception:  # noqa: BLE001
        raise ValueError("无法识别的文件格式：请上传 SKILL.md、.md、.zip 或 .tar.gz")


def _extract_zip(data: bytes) -> list[dict]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("zip 文件损坏")
    return _extract_members(
        [(n, zf.read(n)) for n in zf.namelist() if not n.endswith("/")]
    )


def _extract_tar(data: bytes) -> list[dict]:
    try:
        tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    except tarfile.TarError:
        raise ValueError("tar 文件损坏")
    members = []
    for m in tf.getmembers():
        if m.isfile():
            f = tf.extractfile(m)
            members.append((m.name, f.read() if f else b""))
    return _extract_members(members)


def _extract_members(members: list[tuple[str, bytes]]) -> list[dict]:
    """从 (path, bytes) 列表提取 skill；同时把附属代码文件落地到本地 skills 目录。"""
    ensure_dirs()
    md_files = [(n, d) for n, d in members if n.lower().endswith(".md")]
    skills: list[dict] = []
    for name, content in md_files:
        try:
            text = content.decode("utf-8", "replace")
            default = re.sub(r"[\\/]", "-", name).split("-")[-1].replace(".md", "") or "skill"
            # 只解析真正的 skill 文件：文件名是 SKILL.md，或 .md 但含 name 前言
            if not _looks_like_skill(name, text):
                continue
            skill = _parse_skill(text, default)
            skills.append(skill)
            _persist_files(skill["name"], members)
        except parser.SkillParseError:
            continue
    if not skills:
        raise ValueError("压缩包内未找到 SKILL.md（请以每个技能一个目录、内含 SKILL.md 的方式打包）")
    return skills


def _looks_like_skill(filename: str, text: str) -> bool:
    """判断一个 .md 文件是否为真正的 skill 定义（避免把 README 等误当技能）。

    规则：文件名就是 SKILL.md，或含带 ``name`` 字段的 YAML 前言。
    """
    if os.path.basename(filename).lower() == "skill.md":
        return True
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return False
    return bool(re.search(r"(?m)^name\s*:", m.group(1)))


def _persist_files(skill_name: str, members: list[tuple[str, bytes]]) -> None:
    """把 skill 目录内附属代码文件（py/js/ts/json/...）落地到本地，供后续参考/执行。"""
    ensure_dirs()
    dest = os.path.join(SKILLS_DIR, _safe_name(skill_name))
    os.makedirs(dest, exist_ok=True)
    for name, content in members:
        # 只保留代码/配置类文件，跳过 README/说明
        if not re.search(r"\.(py|js|ts|tsx|json|yaml|yml|sh|txt|md)$", name, re.I):
            continue
        rel = name.strip("/").replace("\\", "/")
        # 去掉常见仓库根前缀（如 owner-repo-main/）
        parts = rel.split("/")
        if len(parts) > 1 and len(parts[0].split("-")) >= 2 and "-" in parts[0]:
            parts = parts[1:]
        # 防御路径穿越：拒绝绝对路径、盘符与 ../ 逃逸，非法成员直接跳过
        parts = [p for p in parts if p not in ("", ".")]
        if not parts or any(p == ".." for p in parts) or any(re.match(r"^[A-Za-z]:", p) for p in parts):
            continue
        target = os.path.join(dest, *parts)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(content)


# ---- GitHub 搜索 / 导入 ----

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"


def search_github(query: str, limit: int = 8) -> list[dict]:
    """搜索 GitHub 上符合 Agent Skills 规范的仓库。"""
    q = (query or "").strip() or "agent skill SKILL.md"
    params = {"q": q, "sort": "stars", "order": "desc", "per_page": min(max(limit, 1), 20)}
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ResearchMate-Agent"}
    try:
        resp = httpx.get(GITHUB_SEARCH_URL, params=params, headers=headers, timeout=15.0)
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"GitHub 搜索失败：{e}")

    out = []
    for it in items:
        out.append(
            {
                "full_name": it.get("full_name", ""),
                "html_url": it.get("html_url", ""),
                "description": (it.get("description") or "")[:200],
                "stars": it.get("stargazers_count", 0),
                "language": it.get("language"),
                "updated_at": (it.get("updated_at") or "")[:10],
            }
        )
    return out


def import_github(repo_url: str) -> list[dict]:
    """从 GitHub 仓库导入 skill：下载 zipball → 解包 → 解析 → 落地 → 注册。"""
    owner_repo = _repo_slug(repo_url)
    if not owner_repo:
        raise ValueError("无法解析 GitHub 仓库地址，请使用 https://github.com/owner/repo 格式")

    zip_url = f"https://codeload.github.com/{owner_repo}/zip/refs/heads/main"
    headers = {"User-Agent": "ResearchMate-Agent"}
    try:
        resp = httpx.get(zip_url, headers=headers, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPStatusError:
        # main 分支不存在时尝试 master
        zip_url = f"https://codeload.github.com/{owner_repo}/zip/refs/heads/master"
        try:
            resp = httpx.get(zip_url, headers=headers, timeout=30.0, follow_redirects=True)
            resp.raise_for_status()
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"GitHub 下载失败：{e}")
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"GitHub 下载失败：{e}")

    skills = _extract_zip(resp.content)
    if not skills:
        raise ValueError("该仓库中未找到 SKILL.md")
    reg = registry.get_registry()
    registered = []
    for skill in skills:
        skill["github_source"] = f"https://github.com/{owner_repo}"
        reg.register(skill)
        registered.append(skill)
    return registered


def _repo_slug(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    if m:
        return m.group(1)
    return ""
