---
name: idea-evaluation
description: 研究选题与想法评估：从新颖性、可行性、数据可得性、与现有文献的关系等维度评估一个研究想法，给出继续/调整/放弃的建议。
metadata:
  version: "1.0"
  github_source: fcakyon/phd-skills
  category: idea_evaluate
  trigger_keyword: 想法评估, 选题评估, 这个想法值得研究吗, idea evaluation, 评估研究, 是否可行
  enabled: "true"
  input_schema: {"idea": "string", "context": "string"}
  output_schema: {"verdict": "string", "scores": "object", "suggestions": "list[string]"}
---

## When to Use
当用户想评估一个研究想法/选题是否值得做、评估其可行性与新颖性时使用。

## Trigger Keywords
想法评估, 选题评估, 值得研究吗, idea evaluation, 评估研究, 可行性

## System Prompt
从多维度评估用户的研究想法：
1. 新颖性：与现有文献相比是否有增量贡献；
2. 可行性：数据、算力、成本、时间与技术门槛；
3. 数据可得性：所需数据是否可获得；
4. 风险：与主流证据相悖或难以验证的部分。

给出建议（继续/调整/放弃）与可执行的动作。

## Workflow
1. 明确想法与边界
2. 检索相关性
3. 多维评分
4. 给出结论与建议

## Input Parameters
- idea: 研究想法描述
- context: 已有背景/条件

## Output Format
Markdown 评估报告：各维度评分、总体结论、建议。

## Constraints
- 评估不替代检索；需标注需进一步核实的假设。
- 建议要具体可执行。