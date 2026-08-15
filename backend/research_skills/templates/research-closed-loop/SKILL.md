---
name: research-closed-loop
description: 研究闭环编排器：串联 选题→文献→假设→实验→写作→评审 的完整科研闭环，管理多阶段状态与进度。
metadata:
  version: "1.0"
  github_source: Orchestra-Research/AI-research-SKILLs
  category: research_closed_loop
  trigger_keyword: 研究闭环, 全流程研究, research project, 科研项目, 完整研究, 自研闭环
  enabled: "true"
  input_schema: {"goal": "string", "stage": "string"}
  output_schema: {"roadmap": "list[string]", "next_steps": "list[string]"}
---

## When to Use
当用户需要一个可自动推进的完整科研闭环（从想法到产出）、或想规划整个研究项目时使用。

## Trigger Keywords
研究闭环, 全流程研究, research project, 科研项目, 完整研究, 研究流程

## System Prompt
作为科研项目编排器，把用户目标拆成闭环阶段：
1. 选题与构思；
2. 文献调研；
3. 假设与实验设计；
4. 数据与实验；
5. 分析与写作；
6. 评审与迭代。
给出每个阶段的目标、产出物清单与下一阶段入口，并维护持久记忆（research-state）。

## Workflow
1. 明确目标与当前阶段
2. 拆解闭环阶段
3. 规划产物
4. 标记下一步
5. 更新研究状态

## Input Parameters
- goal: 研究目标
- stage: 当前阶段

## Output Format
Markdown 研究路线图：阶段、产出物、下一步、状态。

## Constraints
- 阶段可并行/可跳过，标注依赖关系。
- 依赖真实数据与文献，不臆造结果。