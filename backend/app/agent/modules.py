"""模块目录与智能推荐：把用户自然语言意图映射到产品功能模块。

- ``catalog()`` 返回全部模块（含关键词、说明），供前端悬浮窗引导/后端工具使用。
- ``recommend(text)`` 关键词打分，返回命中的模块、跳转路径、推荐理由与引导步骤，
  实现「用户查询功能时跳转到对应模块，并以向导形式协助操作」。
"""
import re

# 模块目录：key / 名称 / 前端路由 / 说明 / 触发关键词 / 引导步骤
MODULES: list[dict] = [
    {
        "key": "library",
        "name": "文献库",
        "path": "/library",
        "icon": "book",
        "desc": "导入、解析、检索、阅读与管理文献",
        "keywords": ["导入文献", "上传pdf", "添加论文", "文献库", "管理文献", "阅读文献", "解析pdf",
                     "import", "upload", "pdf", "论文", "文献", "library", "阅读器", "划词", "标注",
                     "总结文献", "检索文献", "搜索文献", "我的文献"],
        "steps": ["进入「文献库」页面", "点击「导入」选择 PDF 文件，系统自动解析", "在列表中打开论文进行阅读、划词标注与提问"],
    },
    {
        "key": "write",
        "name": "写作",
        "path": "/write",
        "icon": "edit",
        "desc": "论文写作、大纲组织、参考文献管理",
        "keywords": ["写论文", "写一篇论文", "撰写", "写作", "起草", "续写", "润色", "大纲", "论文大纲",
                     "参考文献", "引用格式", "写稿", "论文写作",
                     "write", "draft", "project", "写作项目", "参考文献管理"],
        "steps": ["进入「写作」页面", "新建或选择写作项目", "编辑大纲、正文，并可从对话中让助手起草/润色内容"],
    },
    {
        "key": "workflow",
        "name": "工作流",
        "path": "/workflow",
        "icon": "flow",
        "desc": "可视化编排多步科研流程（导入-翻译-对比-写入）",
        "keywords": ["工作流", "流程", "编排", "自动化", "workflow", "流水线", "pipeline", "节点"],
        "steps": ["进入「工作流」页面", "查看/创建可视化流程", "配置各节点工具与参数，运行查看结果"],
    },
    {
        "key": "chat",
        "name": "对话助手",
        "path": "/chat",
        "icon": "chat",
        "desc": "智能问答、文献提问、数据分析",
        "keywords": ["对话", "问答", "聊天", "咨询", "提问", "chat", "assistant", "助手", "答疑"],
        "steps": ["进入「对话」页面（或直接使用右下角悬浮助手）", "输入问题，助手可调用工具：检索文献/联网搜索/配置 API 等", "如助手推荐跳转模块，可直接点击跳转"],
    },
    {
        "key": "settings",
        "name": "设置",
        "path": "/settings",
        "icon": "setting",
        "desc": "LLM API 配置、主题设置、技能与 MCP 配置",
        "keywords": ["配置api", "设置api", "api配置", "密钥", "api key", "模型", "base url", "设置",
                     "settings", "theme", "主题", "技能", "skill", "mcp", "大模型配置"],
        "steps": ["进入「设置」页面", "填写 API 地址 / Key / 模型并测试连接", "保存后立即生效，也可让悬浮助手帮你一键配置"],
    },
]


def _score(text: str, keywords: list[str]) -> int:
    """关键词打分：命中越多分越高（含中英文大小写归一）。"""
    low = (text or "").lower()
    score = 0
    for kw in keywords:
        if kw and kw.lower() in low:
            score += max(1, len(kw))
    return score


def catalog() -> list[dict]:
    """返回模块目录（供前端与工具使用）。"""
    return [
        {
            "key": m["key"],
            "name": m["name"],
            "path": m["path"],
            "icon": m["icon"],
            "desc": m["desc"],
        }
        for m in MODULES
    ]


def get_module(key: str) -> dict | None:
    """按 key 取模块（含 desc/path/steps），供 @ 引用上下文注入。"""
    for m in MODULES:
        if m["key"] == key:
            return m
    return None


def recommend(text: str) -> dict:
    """智能推荐：返回命中的模块与引导步骤。

    返回结构：
      {"matched": bool, "module": {...}|None, "reason": str, "steps": []}
    """
    best: dict | None = None
    best_score = 0
    for m in MODULES:
        s = _score(text, m["keywords"])
        if s > best_score:
            best_score = s
            best = m

    if best is None or best_score <= 0:
        return {
            "matched": False,
            "module": None,
            "reason": "未能识别到明确的功能模块意图，可继续用对话完成。",
            "steps": [],
        }

    module_view = {
        "key": best["key"],
        "name": best["name"],
        "path": best["path"],
        "icon": best["icon"],
        "desc": best["desc"],
    }
    return {
        "matched": True,
        "module": module_view,
        "reason": f"根据你的描述，我推荐使用「{best['name']}」模块来协助你。",
        "steps": best["steps"],
    }
