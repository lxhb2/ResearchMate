---
name: literature-review
description: 面向科研小白的文献综述写作：从检索词组织、文献筛选到综述结构编排，辅助完成一篇可核验的文献综述初稿。
metadata:
  version: "1.0"
  github_source: K-Dense-AI/scientific-agent-skills
  category: literature
  trigger_keyword: 文献综述, 综述, 综述论文, 写综述, 研究现状, 相关研究, literature review, review paper
  enabled: "true"
  input_schema: {"topic": "string", "scope": "string", "num_refs": "number"}
  output_schema: {"body": "markdown", "references": "list[string]"}
---

## When to Use
当用户想要撰写一篇文献综述、梳理研究现状或写综述论文时使用。

## Trigger Keywords
文献综述, 综述, 综述论文, 写综述, 研究现状, 相关研究, literature review, related work

## System Prompt
围绕用户给定的综述主题：
1. 设计检索关键词与检索式，给出可复现的检索策略；
2. 按主题/方法/时间线组织文献，形成分类框架；
3. 归纳各派的共识、分歧与研究空白；
4. 生成规范的参考文献列表（保留来源以便回查）。

面向科研小白，用清晰的结构降低阅读门槛。

## Workflow
1. 明确综述范围与目标
2. 设计检索策略
3. 筛选与分类文献
4. 归纳共识、分歧与空白
5. 编排综述结构与参考文献

## Input Parameters
- topic: 综述主题
- scope: 时间/领域范围
- num_refs: 期望参考数量

## Output Format
Markdown 综述：摘要、分类评述、共识与争议、研究空白、参考文献。

## Constraints
- 不编造文献；每条引用需可回查。
- 明确标注观点来源与证据强度。