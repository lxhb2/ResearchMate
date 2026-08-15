---
name: scientific-writing
description: 科学写作与表达：把研究结果整理成规范的科学文本，包括图表措辞、方法描述与结果解读，提升可读性与可复现性。
metadata:
  version: "1.1"
  github_source: K-Dense-AI/scientific-agent-skills
  category: paper_writing
  trigger_keyword: 科学写作, 结果解读, 方法描述, 生成图表说明, scientific writing, 写作润色
  enabled: "true"
  input_schema: {"draft": "string", "audience": "string", "style": "string"}
  output_schema: {"body": "markdown"}
---

## When to Use
当用户需要把研究结果/草稿整理成规范的科学写作、生成图表说明或方法描述时使用。

## Trigger Keywords
科学写作, 结果解读, 方法描述, 图表说明, scientific writing, 写作润色

## System Prompt
面向科研写作，将用户输入整理为：
1. 精确的方法描述（可复现）；
2. 客观的结果解读（不过度推断）；
3. 规范的图表说明（figure/table caption）；
4. 适合目标读者的语言与结构。

## Workflow
1. 明确目标读者与文体
2. 拆解方法 / 结果 / 讨论
3. 逐段改写与润色
4. 生成图表说明
5. 一致性检查

## Input Parameters
- draft: 待整理的草稿或结果
- audience: 目标读者（专家/同行/跨学科）
- style: 目标文体

## Output Format
Markdown 整理后的科学文本与图表说明。

## Constraints
- 结果解读不得超出数据要求，避免过度推断。
- 方法描述须可复现。