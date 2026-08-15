"""本地 Skill 注册表管理。

skills_registry.json 保存每个 skill 的元数据：
  name / github_source / trigger_keyword / description / prompt_template /
  input_schema / output_schema / category。

能力：
- 构建时扫描 templates/ 下的 SKILL.md 解析入库；
- 支持动态注册、注销、禁用、启用单个 skill；
- 提供查询（按 name / category / 关键词匹配）。
"""
import copy
import json
import os

from research_skills import config, parser


# 五大科研分类（按产品方案约定）
CATEGORIES = ["literature", "paper_writing", "experiment_review", "idea_evaluate", "research_closed_loop"]


class Registry:
    def __init__(self, registry_path: str = "", templates_dir: str = ""):
        self.registry_path = registry_path or config.REGISTRY_PATH
        self.templates_dir = templates_dir or config.TEMPLATES_DIR
        self._skills: dict[str, dict] = {}
        self._loaded = False

    # ---- 加载 / 保存 ----

    def load(self, rebuild: bool = False) -> "Registry":
        """加载注册表。若注册表缺失或 rebuild=True，则从 templates/ 重新构建。"""
        if os.path.isfile(self.registry_path) and not rebuild:
            try:
                with open(self.registry_path, encoding="utf-8") as f:
                    data = json.load(f)
                self._skills = {s["name"]: s for s in data.get("skills", [])}
                self._loaded = True
                return self
            except (json.JSONDecodeError, KeyError, TypeError):
                pass  # 文件损坏 → 重建
        self._load_from_templates()
        self.save()
        return self

    def _load_from_templates(self) -> None:
        """递归扫描 templates/ 下所有 SKILL.md 并解析入库。"""
        self._skills = {}
        if not os.path.isdir(self.templates_dir):
            return
        for root, _dirs, files in os.walk(self.templates_dir):
            if "SKILL.md" not in files:
                continue
            try:
                skill = parser.parse_skill_dir(root)
            except parser.SkillParseError as exc:
                print(f"[research_skills] 跳过解析失败的 skill: {root} ({exc})")
                continue
            self._skills[skill["name"]] = skill
        self._loaded = True

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.registry_path) or ".", exist_ok=True)
        payload = {
            "schema_version": "1.0",
            "categories": CATEGORIES,
            "source_libraries": [
                "Imbad0202/academic-research-skills",
                "K-Dense-AI/scientific-agent-skills",
                "Yuan1z0825/nature-skills",
                "fcakyon/phd-skills",
                "Orchestra-Research/AI-research-SKILLs",
                "HKUSTDial/Supervisor-Skills",
            ],
            "skills": list(self._skills.values()),
        }
        with open(self.registry_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    # ---- 查询 ----

    def all(self) -> list[dict]:
        if not self._loaded:
            self.load()
        return [copy.deepcopy(s) for s in self._skills.values() if s.get("enabled", True)]

    def get(self, name: str) -> dict | None:
        if not self._loaded:
            self.load()
        s = self._skills.get(name)
        return copy.deepcopy(s) if s else None

    def by_category(self, category: str) -> list[dict]:
        return [s for s in self.all() if s.get("category") == category]

    def match(self, text: str) -> list[dict]:
        """按触发关键词匹配输入文本，返回命中并计分的 skill 列表。"""
        text = (text or "").lower()
        scored: list[tuple[int, dict]] = []
        for s in self.all():
            score = 0
            for kw in s.get("trigger_keyword", []) or []:
                kwl = str(kw).lower()
                if kwl and kwl in text:
                    score += max(1, len(kwl))
            if score > 0:
                scored.append((score, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [copy.deepcopy(s) for _, s in scored]

    # ---- 动态增删改 ----

    def register(self, skill: dict) -> dict:
        """注册（或覆盖）一个 skill。"""
        name = str(skill.get("name", "")).strip()
        if not name:
            raise ValueError("skill 必须有 name")
        self._skills[name] = skill
        self.save()
        return skill

    def unregister(self, name: str) -> bool:
        if name in self._skills:
            del self._skills[name]
            self.save()
            return True
        return False

    def set_enabled(self, name: str, enabled: bool) -> bool:
        if name not in self._skills:
            return False
        self._skills[name]["enabled"] = enabled
        self.save()
        return True


_registry: Registry | None = None


def get_registry() -> Registry:
    global _registry
    if _registry is None:
        _registry = Registry().load()
    return _registry