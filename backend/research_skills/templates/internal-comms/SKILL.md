---
name: internal-comms
description: "一套资源来帮助我使用我公司喜欢使用的格式来撰写各种内部通信。 克劳德每当被要求撰写某种内部通信(状况报告、领导层更新、3P更新、公司通讯、FAQs、事件报告、项目更新等)时，都应该使用这种技能。"
metadata:
  version: ""
  github_source: "https://github.com/anthropics/skills"
  category: research_closed_loop
  trigger_keyword:
    - internal-comms
    - internal comms
    - set
    - resources
    - write
    - all
    - kinds
    - internal
  enabled: "true"
---
## Trigger Keywords
internal-comms, internal comms, set, resources, write, all, kinds, internal

## System Prompt
## When to use this skill
To write internal communications, use this skill for:
- 3P updates (Progress, Plans, Problems)
- Company newsletters
- FAQ responses
- Status reports
- Leadership updates
- Project updates
- Incident reports

## How to use this skill

To write any internal communication:

1. **Identify the communication type** from the request
2. **Load the appropriate guideline file** from the `examples/` directory:
    - `examples/3p-updates.md` - For Progress/Plans/Problems team updates
    - `examples/company-newsletter.md` - For company-wide newsletters
    - `examples/faq-answers.md` - For answering frequently asked questions
    - `examples/general-comms.md` - For anything else that doesn't explicitly match one of the above
3. **Follow the specific instructions** in that file for formatting, tone, and content gathering

If the communication type doesn't match any existing guideline, ask for clarification or more context about the desired format.

## Keywords
3P updates, company newsletter, company comms, weekly update, faqs, common questions, updates, internal comms
