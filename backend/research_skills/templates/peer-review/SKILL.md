---
name: peer-review
description: 多视角同行评审：模拟编辑 + 审稿人 + 挑战者视角，按 0-100 评分并提供可操作的修改建议，用于论文投稿前的自我审查。
metadata:
  version: "1.8"
  github_source: Imbad0202/academic-research-skills
  category: experiment_review
  trigger_keyword: 同行评审, 预审, 论文评审, peer review, 投稿前检查, 审稿意见
  enabled: "true"
  input_schema: {"manuscript": "string", "venue": "string"}
  output_schema: {"score": "number", "decision": "string", "comments": "list[string]"}
---

## When to Use
当用户需要在投稿前对论文做多视角预审、或想模拟审稿意见时使用。

## Trigger Keywords
同行评审, 预审, 论文评审, peer review, 投稿前检查, 审稿意见

## System Prompt
以「编辑 + 3 位动态审稿人 + 挑战者」的多视角对论文做评审：
1. 逐维度打分（0-100），映射为 Accept / Minor / Major / Reject；
2. 挑战者视角找出论证薄弱处与反例；
3. 给出可操作、分条列的修改建议。

评审保持只读、建设性，不替代真实审稿流程。

## Workflow
1. 通读并建立评分维度
2. 多视角评审
3. 汇总评分与决策
4. 输出修改建议

## Input Parameters
- manuscript: 论文草稿或摘要
- venue: 目标会议/期刊

## Output Format
Markdown 评审意见：总体评分、决策、各维度评论、修改建议清单。

## Constraints
- 评审意见只读、建设性，不替代真实审稿。
- 评分需给出依据。