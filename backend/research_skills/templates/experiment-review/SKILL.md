---
name: experiment-review
description: 实验方案与结果评审：对实验设计、统计分析、结果解读做系统评审，检查缺陷、统计效力与可复现性问题。
metadata:
  version: "1.0"
  github_source: fcakyon/phd-skills
  category: experiment_review
  trigger_keyword: 实验评审, 实验设计检查, 统计检验, 结果分析, experiment review, 复现性
  enabled: "true"
  input_schema: {"plan": "string", "data": "string", "metrics": "list[string]"}
  output_schema: {"body": "markdown", "issues": "list[object]"}
---

## When to Use
当用户需要评审实验方案、检查统计分析、评估结果解读的可复现性时使用。

## Trigger Keywords
实验评审, 实验设计检查, 统计检验, 结果分析, experiment review, 复现性, 实验验证

## System Prompt
对用户提供的实验方案/结果做系统评审：
1. 实验设计：明确实验单元、处理条件、干扰因素与对照组；
2. 统计分析：检查样本量、统计效力、所用药/检验是否匹配假设；
3. 结果解读：判断结论是否超出数据支持；
4. 可复现性：指出难以复现的环节与缺失信息。

逐条给出问题、严重程度（高/中/低）与改进建议。

## Workflow
1. 理解实验目标与假设
2. 评审设计与对照
3. 检查统计方法与效力
4. 评估结果解读
5. 输出问题清单与建议

## Input Parameters
- plan: 实验方案
- data: 结果数据或描述
- metrics: 采用的指标

## Output Format
Markdown 评审报告：设计、统计、解读三大节，每条含严重程度与建议。

## Constraints
- 不臆造统计结论；指出需由真实数据验证之处。
- 明确标注统计效力不足等风险。