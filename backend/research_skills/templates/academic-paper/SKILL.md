---
name: academic-paper
description: 学术论文写作：从配置访谈、结构规划、论证构建到分段起草与引用检查，辅助完成符合 IMRaD 结构与引用规范的论文初稿。
metadata:
  version: "3.2.0"
  github_source: Imbad0202/academic-research-skills
  category: paper_writing
  trigger_keyword: 写论文, 学术论文, 论文大纲, 写摘要, 修改论文, write paper, academic paper, paper outline
  enabled: "true"
  input_schema: {"topic": "string", "paper_type": "string", "citation_format": "string", "sections": "list[string]"}
  output_schema: {"body": "markdown", "references": "list[string]", "abstract": "string"}
---

## When to Use
当用户要撰写论文、论文大纲、摘要、修改论文或检查引用时使用。

## Trigger Keywords
写论文, 学术论文, 论文大纲, 写摘要, 修改论文, write paper, academic paper, paper outline, 论文写作

## System Prompt
按学术论文写作流程推进：
1. 配置访谈：明确论文类型、学科、引用格式、输出格式；
2. 结构规划：设计论文结构与各章节篇幅分配；
3. 论证构建：建立「主张－证据」链，确保逻辑连贯；
4. 分段起草：逐节推进，并做语言润色；
5. 引用合规 + 双语摘要（并行）；
6. 自查：五维评分并给出修改建议。

学科规范优先于个人风格；不写无证据支撑的断言。

## Workflow
1. 配置访谈
2. 结构规划
3. 论证构建
4. 分段起草
5. 引用检查 + 摘要
6. 自评与修改建议

## Input Parameters
- topic: 论文主题
- paper_type: 论文类型（期刊/会议/学位论文等）
- citation_format: 引用格式（如 GB/T 7714、APA）
- sections: 需要覆盖的章节列表

## Output Format
Markdown 论文初稿（含摘要、章节正文、参考文献），结尾附自评与修改建议。

## Constraints
- 不编造数据与引用；引用需可回查。
- 学科/期刊规范优先于写作风格。
- 明确标注待补充的实验数据与验证环节。