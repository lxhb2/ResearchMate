# Research Skills 集成说明（README-SKILLS.md）

本模块把 GitHub 上 6 套高星科研 Skill 库，以「**解析 SKILL.md 标准格式 → 本地注册表 → 调度层 → 执行器 → 评审后置**」的方式集成进本项目，**不整仓 clone / 不硬拷贝外部源码**，只提取每个 skill 的触发条件、系统提示、输入参数、输出格式与约束规则。

集成来源：

| 仓库 | 说明 |
| --- | --- |
| `Imbad0202/academic-research-skills` | deep-research / academic-paper / academic-paper-reviewer / academic-pipeline |
| `K-Dense-AI/scientific-agent-skills` | 133 个科研/科学技能（文献综述、科学写作、同行评审等） |
| `Yuan1z0825/nature-skills` | 科研技能集 |
| `fcakyon/phd-skills` | 博士阶段科研技能（选题、假设、实验、写作） |
| `Orchestra-Research/AI-research-SKILLs` | autoresearch 编排 + findings.md / research-log.md / research-state.yaml 持久记忆 |
| `HKUSTDial/Supervisor-Skills` | 评审后置：缺陷诊断 / 可行性评估 / 风险提示 |

> 说明：以上为注册表 `source_libraries` 中声明的来源。其中 Imbad0202、K-Dense-AI、fcakyon、Orchestra-Research 已核实存在；Yuan1z0825、HKUSTDial 按其名在注册表中作为来源标注，实际能力以本模块内置的解析模板为准。

## 目录结构

```
backend/
├── main.py                     # CLI 入口（--research / --feed / --list-skills 等）
├── research_skills/
│   ├── __init__.py
│   ├── config.py               # 路径 / LLM 提供方配置
│   ├── llm.py                  # Ollama / OpenAI 兼容 / 离线 Mock
│   ├── parser.py               # SKILL.md 标准格式解析器
│   ├── registry.py             # 注册表（skills_registry.json）构建/增删/匹配
│   ├── scheduler.py            # 调度层：科研意图识别与分发
│   ├── executor.py             # 执行器：skill + 输入 → Markdown 产物
│   ├── memory.py               # 持久记忆：findings.md / research-log.md / research-state.yaml
│   ├── supervisor.py           # 评审后置模块
│   ├── templates/              # 内置 SKILL.md（覆盖 5 大分类）
│   │   ├── deep-research/SKILL.md
│   │   ├── literature-review/SKILL.md
│   │   ├── academic-paper/SKILL.md
│   │   ├── scientific-writing/SKILL.md
│   │   ├── experiment-review/SKILL.md
│   │   ├── peer-review/SKILL.md
│   │   ├── idea-evaluation/SKILL.md
│   │   ├── hypothesis/SKILL.md
│   │   ├── research-closed-loop/SKILL.md
│   │   └── supervisor/SKILL.md
│   └── skills_registry.json    # 本地 skill 注册表
└── output/
    ├── research/               # 科研产物（本模块）
    │   ├── <skill>/<时间戳>-<skill>.md
    │   ├── _review/            # Supervisor 评审产物
    │   ├── findings.md
    │   ├── research-log.md
    │   └── research-state.yaml
    └── feed/                   # 原情报采集产物（隔离，本模块不写）
```

## 五大科研分类

| 分类 | 说明 | 内置 skill |
| --- | --- | --- |
| `literature` | 文献调研与证据梳理 | deep-research, literature-review |
| `paper_writing` | 论文与科学写作 | academic-paper, scientific-writing |
| `experiment_review` | 实验与评审 | experiment-review, peer-review |
| `idea_evaluate` | 选题与假设评估 | idea-evaluation, hypothesis |
| `research_closed_loop` | 研究闭环编排 + 评审后置 | research-closed-loop, supervisor |

## 调用示例

```bash
cd backend
.venv/bin/python main.py --research "文献综述：一人公司商业模型，结合OPC概念"
.venv/bin/python main.py --research "写一篇关于强化学习的论文" --skill academic-paper
.venv/bin/python main.py --research "实验方案：对比两种特征选择方法" --review
.venv/bin/python main.py --research "评估'用图网络做药物组合预测'这个想法" --project my-idea
.venv/bin/python main.py --feed        # 原有情报采集模式（预留入口）
.venv/bin/python main.py --list-skills
```

调度规则：科研意图（命中触发词 / 弱科研信号）→ 匹配 skill 并产出到 `output/research/`；非科研任务（如资讯、RSS、日报）→ 返回 `feed` 标记，继续走原有情报链路，互不干扰。

## LLM 配置（默认离线可用）

| 提供方 | 方式 |
| --- | --- |
| Ollama（本地，推荐） | `export RESEARCH_LLM_PROVIDER=ollama`，默认 `http://localhost:11434`，模型 `llama3`（可用 `RESEARCH_OLLAMA_MODEL` 改） |
| OpenAI 兼容 | `export RESEARCH_LLM_PROVIDER=openai` + `RESEARCH_OPENAI_API_KEY` / `RESEARCH_OPENAI_BASE_URL` / `RESEARCH_OPENAI_MODEL` |
| 离线 Mock（默认） | 不配置任何 Key 时自动降级为确定性占位输出，保证示例可跑通 |

CLI 也可用 `--provider ollama|openai|mock` 临时指定。产物路径可用 `RESEARCH_SKILL_OUTPUT_DIR`、`RESEARCH_OUTPUT_DIR` 覆盖。

## 如何新增一个 Skill

1. 在 `research_skills/templates/<skill-name>/` 新建 `SKILL.md`，遵循 Agent Skills 标准格式：

```markdown
---
name: my-skill
description: 这个 skill 做什么、何时使用。
metadata:
  version: "1.0"
  github_source: owner/repo
  category: literature            # 必填：五大分类之一
  trigger_keyword: 关键词1, 关键词2   # 逗号分隔，用于调度匹配
  enabled: "true"
  input_schema: {"user_text": "string"}
  output_schema: {"body": "markdown"}
---

## Trigger Keywords
关键词1, 关键词2

## System Prompt
告诉模型怎么干（方法/工作流）。

## Constraints
- 约束规则。

## Input Parameters
按需说明。

## Output Format
按需说明。
```

2. 重建注册表并验证：

```bash
.venv/bin/python main.py --rebuild-registry
.venv/bin/python main.py --list-skills
.venv/bin/python main.py --research "你的测试指令" --skill my-skill
```

## 如何禁用 / 启用 / 注销一个 Skill

- **禁用**：编辑 `skills_registry.json`，把该 skill 的 `"enabled"` 改为 `false`；或改 `SKILL.md` 的 `metadata.enabled` 后重建注册表。
- **启用**：把 `"enabled"` 改回 `true`。
- **注销**：从 `skills_registry.json` 的 `skills` 数组删除该条目，或调用注册表 API：

```python
from research_skills.registry import get_registry
r = get_registry()
r.set_enabled("deep-research", False)   # 禁用
r.unregister("deep-research")           # 注销
r.register({"name": "my-skill", ...})   # 动态注册
```

## 调试单个 Skill

1. 直接解析某个 SKILL.md 看提取结果：

```python
from research_skills import parser
s = parser.parse_skill_md_text(open("templates/academic-paper/SKILL.md", encoding="utf-8").read())
import json; print(json.dumps(s, ensure_ascii=False, indent=2))
```

2. 指定单 skill 跑一次（离线 mock 验证调度与产物落盘）：

```bash
.venv/bin/python main.py --provider mock --research "..." --skill my-skill
```

3. 查看产物与持久记忆：

```bash
find output/research -type f
cat output/research/research-state.yaml          # 中央状态
cat output/research/research-log.md              # 决策时间线
cat output/research/findings.md                  # 叙事综合
```

## 最小侵入说明

- 本模块全部位于 `backend/research_skills/`，不 import `app.*`，可独立运行。
- 未改动原有 `app/` 下任何采集/情报逻辑；`--feed` 为原链路预留入口。
- 依赖仅复用项目已有的 `litellm`（可选），Ollama 走标准库 `urllib`，无第三方新增项。