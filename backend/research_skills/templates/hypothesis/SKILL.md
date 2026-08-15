---
name: hypothesis
description: 从文献线索与研究问题生成可追踪的研究假设，给出假设、机制解释与初步研究方案，并预留可证伪的检验路径。
metadata:
  version: "1.0"
  github_source: fcakyon/phd-skills
  category: idea_evaluate
  trigger_keyword: 假设生成, 研究假设, 提出假设, hypothesis, 机制解释, 研究问题
  enabled: "true"
  input_schema: {"question": "string", "evidence": "string"}
  output_schema: {"hypotheses": "list[object]", "plan": "string"}
---

## When to Use
当用户有多条线索想形成研究假设、或需要把研究问题拆成可检验的假设时使用。

## Trigger Keywords
假设生成, 研究假设, 提出假设, hypothesis, 机制解释, 研究问题

## System Prompt
从关键词、研究问题或论文线索出发：
1. 提取事实线索；
2. 形成候选假设与机制解释；
3. 给出初步研究方案；
4. 明确哪些结果会使假设受到质疑（可证伪性）。

## Workflow
1. 梳理线索
2. 形成候选假设
3. 设计初步验证方案
4. 标注可证伪条件

## Input Parameters
- question: 研究问题
- evidence: 已有线索/证据

## Output Format
Markdown：候选假设列表（含机制）与初步验证方案。

## Constraints
- 假设需可证伪，明确指出反证条件。
- 不编造支撑证据。