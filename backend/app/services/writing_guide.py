"""学术写作规范库：融合 Glasman-Deal 英文科研写作方法与国内学术规范。"""

# 章节 -> 6 维 RAG 片段维度映射（用于素材检索）
SECTION_DIMENSIONS = {
    "introduction": "background",
    "related work": "background",
    "background": "background",
    "literature review": "background",
    "method": "method",
    "methods": "method",
    "methodology": "method",
    "materials and methods": "method",
    "experimental": "method",
    "model": "method",
    "results": "results",
    "experiments": "results",
    "discussion": "conclusion",
    "conclusion": "conclusion",
    "conclusions": "conclusion",
    "future work": "conclusion",
    "abstract": "title_keywords",
    "contributions": "contributions",
}

SECTION_DIMENSIONS_ZH = {
    "引言": "background",
    "绪论": "background",
    "研究背景": "background",
    "文献综述": "background",
    "相关工作": "background",
    "方法": "method",
    "研究方法": "method",
    "实验方法": "method",
    "模型": "method",
    "实验": "results",
    "结果": "results",
    "实验结果": "results",
    "讨论": "conclusion",
    "结论": "conclusion",
    "总结": "conclusion",
    "展望": "conclusion",
    "摘要": "title_keywords",
    "创新点": "contributions",
    "贡献": "contributions",
}


def dimension_for_section(title: str) -> str | None:
    """根据章节标题推断应优先检索的 6 维向量片段维度。"""
    t = (title or "").strip().lower()
    if t in SECTION_DIMENSIONS:
        return SECTION_DIMENSIONS[t]
    for key, dim in SECTION_DIMENSIONS_ZH.items():
        if key in t:
            return dim
    for keyword, dim in SECTION_DIMENSIONS.items():
        if keyword in t:
            return dim
    return None


def writing_guidance(language: str) -> str:
    """按目标语言返回正文写作规范提示。"""
    if language == "en":
        return (
            "Follow the research writing method in Glasman-Deal's Science Research Writing: "
            "write for the reader by wrapping information in a clear narrative; use the IMRaD structure "
            "(Introduction, Methods, Results, Discussion) plus Conclusion where appropriate; "
            "in the Introduction start general and narrow towards the gap and the present study; "
            "in the Discussion widen from the findings back to the field; "
            "give every paragraph and sentence a clear function; choose verb tenses that communicate that function; "
            "use vocabulary consistently; keep the title and abstract predictive and self-contained; "
            "write formal, concise, unambiguous academic English."
        )
    return (
        "遵循国内学术论文写作规范：正文采用引言（研究背景/问题/意义）、方法、结果、讨论、结论的结构；"
        "引言从宽泛背景逐步聚焦到研究空白与本文工作；讨论从研究结果展开回到领域意义；"
        "每个段落和句子都要承担明确功能；使用规范学术书面语，避免口语化；"
        "术语前后一致；图表随文出现并说明其作用；摘要需包含目的、方法、结果、结论四要素；"
        "参考文献按 GB/T 7714 格式著录。"
    )


def abstract_guidance(language: str) -> str:
    """按目标语言返回摘要写作规范提示。"""
    if language == "en":
        return (
            "Write a standalone abstract using the generic abstract model: background/context, "
            "gap or problem, aim, method, main results, and conclusion/significance. "
            "Keep it concise (150-250 words), use the active voice where natural, "
            "and ensure the abstract can be read independently of the paper. "
            "Provide 3-8 keywords that match the title and the paper content."
        )
    return (
        "撰写符合国内学术规范的摘要：包含研究目的、方法、主要结果和结论四要素，"
        "语言精炼、逻辑完整，可独立阅读；关键词 3-8 个，应与题目和正文核心内容一致。"
    )


def outline_sections(language: str) -> list[str]:
    """返回当前语言下的标准章节建议（用于提示模型）。"""
    if language == "en":
        return ["Introduction", "Methods", "Results", "Discussion", "Conclusion"]
    return ["引言", "方法", "结果", "讨论", "结论"]
