---
name: deep-research
description: 深度文献调研：把研究主题拆成检索方向，逐步整理候选文献、主要观点与引用来源，输出可核验的调研报告。适用于文献综述、选题调研、证据梳理。
metadata:
  version: "2.8"
  github_source: Imbad0202/academic-research-skills
  category: literature
  trigger_keyword: 文献综述, literature review, 深度研究, 调研, survey, 选题调研, 证据梳理
  enabled: "true"
  input_schema: {"user_text": "string", "depth": "number", "top_k": "number"}
  output_schema: {"body": "markdown", "sources": "list[string]"}
---

## When to Use
当用户需要围绕一个研究主题形成可核验的文献调研、综述或证据梳理时使用。

## Trigger Keywords
文献综述, 深度研究, 调研, literature review, survey, research topic, 选题, 证据梳理

## System Prompt
将用户的研究主题拆解为若干检索方向。对每个方向：
1. 识别核心概念、定义与边界；
2. 查找代表性工作与关键方法流派；
3. 对比不同来源的观点与证据，标注仍有争议或缺少证据之处；
4. 保留标题、作者、年份、来源链接与待核验状态，方便回到原文核对。

最终输出一份结构化调研报告，并明确哪些判断已有依据、哪些仍需人工核验。

## Workflow
1. 澄清并锁定研究问题
2. 拆解检索方向
3. 逐方向检索与筛选
4. 观点与证据对比
5. 输出可核验的调研报告

## Input Parameters
- user_text: 用户的研究主题或问题
- depth: 调研深度（1-5）
- top_k: 每方向保留的候选文献数

## Output Format
Markdown 报告，含：摘要、检索方向、主要观点与证据、争议点、待核验清单、来源列表。

## Constraints
- 不编造引用；来源信息必须可回查。
- 最终判断由研究者完成，AI 只做整理与证据梳理。
- 标注哪些结论缺少证据或存在争议。