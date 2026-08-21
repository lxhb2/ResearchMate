# ResearchMate API Key、Skill、MCP 与插件配置指南

> 适用版本：ResearchMate v0.3.2  
> 编写依据：本项目完整源码（backend / frontend / plugins / electron）实际代码分析  
> 操作入口：应用内「设置」页，部分高级配置可写 `.env` 或直接管理本地存储文件

---

## 一、项目架构速览

ResearchMate 是本地化科研助手，核心链路如下：

```text
React 前端（Vite + Ant Design）
        │  /api/v1
        ▼
FastAPI 后端
  ├── routers/     HTTP 接口（settings / agent / papers / chat ...）
  ├── services/    业务服务（LLM / Embedding / 搜索 / 导入导出 ...）
  ├── agent/       顶层 Agent、Skill 导入、MCP 存储、插件管理
  ├── research_skills/  Skill 解析、注册表、调度、执行、评审
  └── models/      SQLAlchemy ORM（app_settings 等）
        │
        ▼
SQLite 单文件（backend/researchmate.db）
```

与本次配置相关的关键代码位置：

| 配置项 | 主要代码 |
| --- | --- |
| LLM API Key / Base URL / 模型 | `backend/app/routers/settings.py`、`backend/app/services/settings_service.py` |
| Skill 注册 / 上传 / GitHub 导入 | `backend/app/agent/skill_store.py`、`backend/app/routers/agent.py`、`backend/research_skills/registry.py` |
| MCP 服务器配置 | `backend/app/agent/mcp_store.py`、`backend/app/routers/agent.py` |
| 插件安装 / 启用 / 卸载 | `backend/app/agent/plugin_manager.py`、`backend/app/routers/agent.py` |
| 前端操作界面 | `frontend/src/pages/SettingsPage.tsx`、`frontend/src/pages/AgentCenterPage.tsx` |

> （此处需要插图：ResearchMate 配置相关模块架构图）

---

## 二、启动项目与进入配置页

1. Windows 双击 `start.bat`，或源码运行：

   ```bash
   cd backend
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   set FRONTEND_DIST=..\frontend\dist
   uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

2. 浏览器访问 `http://localhost:8000`。
3. 默认单用户自动登录：`researcher / researchmate`。
4. 点击左侧导航「设置」，进入配置页。

> （此处需要插图：应用首页与左侧导航截图，标出「设置」入口）

配置页包含四个主要 Tab：

| Tab | 配置内容 |
| --- | --- |
| 模型与主题 | LLM API Key、Base URL、模型、Embedding、主题色 |
| 助手中心 | Skill、MCP 服务器、长期记忆 |
| 插件 | 插件 zip 安装、启用 / 停用 / 卸载 |
| 版本与更新 | 检查更新 |

---

## 三、API Key 配置流程

### 3.1 推荐方式：应用内「设置」页

1. 打开「设置」→「模型与主题」。
2. 在「国内大模型预设」下拉框选择一个厂商，可自动填充 Base URL 和模型名；也可手动填写。
3. 填写以下字段：
   - `API Base URL`：OpenAI 兼容接口根地址，例如 `https://dashscope.aliyuncs.com/compatible-mode/v1`
   - `API Key`：厂商控制台创建的密钥
   - `聊天模型名称`：例如 `qwen-plus`、`glm-4-flash`、`deepseek-chat`
4. 在「向量嵌入模型」区域填写 Embedding 模型名称和向量维度（可选，留空时检索会降级为关键词匹配）。
5. 点击「测试连接」，后端会发送一次最小化对话请求，成功返回模型回复。
6. 点击页面底部「保存设置」。

> （此处需要插图：设置页「模型与主题」完整表单截图）

安全与覆盖规则：

- 已保存的 API Key 不会明文回显，只显示脱敏值，例如 `sk-1****abcd`。
- API Key 输入框留空再保存，表示保持原 Key 不变。
- 输入新 Key 再保存，表示替换旧 Key。
- 保存后后端会清空 LLM 熔断状态，新配置立即生效。

### 3.2 环境变量方式：`.env`

源码运行在 `backend/.env`，绿色打包版会优先读取可执行文件同目录的 `.env`，环境变量优先级最高。复制模板：

```bash
cd backend
copy .env.example .env
```

至少配置：

```ini
LLM_API_KEY=sk-你的真实Key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536
```

> 注意：应用内设置页保存的值优先级高于 `.env`。若 `.env` 改了但界面仍显示旧值，进入设置页重新保存一次即可覆盖。

### 3.3 CLI 科研 Skill 的独立 LLM 配置

CLI 科研任务使用独立的 `RESEARCH_*` 配置：

```bash
# 本地 Ollama
RESEARCH_LLM_PROVIDER=ollama RESEARCH_OLLAMA_MODEL=qwen2.5 python main.py --research "文献综述：..."

# OpenAI 兼容
RESEARCH_LLM_PROVIDER=openai RESEARCH_OPENAI_API_KEY=sk-xxx python main.py --research "..."

# 离线占位
RESEARCH_LLM_PROVIDER=mock python main.py --research "..."
```

### 3.4 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| 对话返回 Mock 占位内容 | 未配置有效 Key；去设置页填写并测试 |
| 测试连接提示默认占位 Key | 当前 Key 是 `sk-xxx`，需填写真实 Key |
| 文献语义检索没结果 | 未配置 Embedding，自动使用关键词检索；配置后重新处理文献 |
| 修改 `.env` 不生效 | 环境变量或设置页已保存值优先级更高，重启并检查 |

> （此处需要插图：API Key 配置成功后的脱敏展示与测试回复截图）

---

## 四、Skill 配置流程

### 4.1 Skill 是什么

Skill 是助手可执行的工作流模板，包含触发词、描述、系统提示词、输入输出格式和约束规则。用户在对话中说一句话，顶层 Agent 命中触发词后自动调用 Skill。

项目默认内置 Skill 注册表，且支持三种自定义方式：

| 方式 | 适用场景 |
| --- | --- |
| 注册技能 | 快速录入一个简单自定义 Skill |
| 上传文件 | 上传 `SKILL.md`、代码文件、zip 或 tar.gz |
| GitHub 导入 | 从 GitHub 搜索符合 Agent Skills 规范的仓库并一键导入 |

### 4.2 进入 Skill 管理

1. 打开「设置」→「助手中心」。
2. 点击「技能 Skills」Tab。

> （此处需要插图：助手中心「技能 Skills」列表截图）

### 4.3 注册自定义 Skill

1. 点击「注册技能」。
2. 填写：
   - 技能名称：如 `my-research`
   - 描述：说明这个技能做什么
   - 触发关键词：逗号分隔，如 `综述,文献调研`
   - 分类：自定义 / 文献 / 写作 / 实验 / 选题
   - 提示词模板：指导助手如何执行
   - 约束规则：输出格式等限制
3. 点击「注册」，技能写入注册表后立即可用。

> （此处需要插图：注册技能弹窗截图）

### 4.4 上传 SKILL.md 或压缩包

1. 在「技能 Skills」页点击「上传 SKILL.md / 代码 / 压缩包」。
2. 选择单个 `SKILL.md`、代码文件，或包含多个 Skill 目录的 `.zip` / `.tar.gz` / `.tgz`。
3. 系统自动解析并注册，上传代码会保存到 `storage/agent/skills/<skill-name>/`。

推荐目录格式：

```text
my-skill/
└── SKILL.md
```

也可将附属代码放在同目录：

```text
my-skill/
├── SKILL.md
└── helper.py
```

### 4.5 从 GitHub 导入 Skill

1. 在「技能 Skills」页搜索 GitHub 技能仓库，例如 `arxiv paper review`。
2. 点击仓库右侧「导入」，或直接粘贴 `https://github.com/owner/repo` 到导入输入框。
3. 系统下载仓库 zip、解析 `SKILL.md` 并注册。

> 网络不可用时 GitHub 导入会失败，请检查代理或改用本地上传。

> （此处需要插图：GitHub 搜索与导入结果截图）

### 4.6 SKILL.md 标准格式

项目解析 Agent Skills 标准格式：

```markdown
---
name: my-skill
description: 这个技能做什么、何时使用。
metadata:
  version: "1.0"
  github_source: owner/repo
  category: literature
  trigger_keyword: 综述, 文献调研
  enabled: "true"
  input_schema: {"user_text": "string"}
  output_schema: {"body": "markdown"}
---

## Trigger Keywords
综述, 文献调研

## System Prompt
告诉模型怎么执行这个技能。

## Constraints
- 约束规则。

## Input Parameters
按需说明输入参数。

## Output Format
按需说明输出格式。
```

核心字段说明：

| 字段 | 说明 |
| --- | --- |
| `name` | Skill 唯一名称 |
| `description` | 给助手看的用途描述 |
| `metadata.category` | 分类：`literature`、`paper_writing`、`experiment_review`、`idea_evaluate`、`research_closed_loop` 等 |
| `metadata.trigger_keyword` | 调度触发词，逗号分隔 |
| `metadata.enabled` | `true` / `false` |
| `metadata.prompt_mode` | 为 `full` 时整段正文作为系统提示 |
| System Prompt / 正文 | 执行方法或工作流 |

### 4.7 在对话中使用 Skill

- 直接说包含触发词的句子，顶层 Agent 自动路由到对应 Skill。
- 在对话输入框使用 `@` 引用 Skill，可显式指定上下文。

> （此处需要插图：对话中 `@` 选择 Skill 的输入框截图）

### 4.8 CLI 查看与调试 Skill

```bash
cd backend
python main.py --list-skills
python main.py --research "文献综述：..." --skill my-skill
python main.py --rebuild-registry
```

### 4.9 存储位置

| 数据 | 位置 |
| --- | --- |
| Skill 注册表 | `backend/research_skills/skills_registry.json` |
| 内置 Skill 模板 | `backend/research_skills/templates/<skill-name>/SKILL.md` |
| 上传 Skill 附属代码 | `storage/agent/skills/<skill-name>/` |
| 插件 Skill | `storage/agent/plugins/<plugin-name>/skills/` |

---

## 五、MCP 配置流程

### 5.1 MCP 是什么

MCP（Model Context Protocol）服务器让 Agent 接入外部工具和数据源。本项目支持两种类型：

| 类型 | 说明 | 示例 |
| --- | --- | --- |
| `http` | HTTP / SSE 远程服务器 | `https://mcp.example.com/sse` |
| `stdio` | 本地命令式服务器 | `npx -y @modelcontextprotocol/server-filesystem /tmp` |

MCP 配置保存在本地 `storage/agent/mcp.json`，列表接口会隐藏 `api_key` / `secret` 字段。

### 5.2 界面添加 MCP 服务器

1. 打开「设置」→「助手中心」→「MCP 服务器」。
2. 点击「添加服务器」。
3. 填写名称，选择类型：
   - `HTTP/SSE（远程）`：填写 URL，例如 `https://mcp.example.com/sse`
   - `stdio（本地命令）`：填写命令和参数，例如 `npx` 和 `-y @modelcontextprotocol/server-filesystem /tmp`
4. 填写描述，点击「保存」。
5. 列表中点「发现」执行真实握手（`initialize` → `tools/list`），成功后工具会缓存到服务器配置并注册进 Agent 工具表。
6. 点「测试」可再次验证连通性；发现/测试成功后，到「工具 Tools」页确认工具已出现。
7. 在对话中，Agent 可直接调用注册后的 MCP 工具，工具名为 `mcp__<服务器名>__<工具名>`。

> （此处需要插图：添加 MCP 服务器弹窗，分别展示 HTTP 与 stdio 两种表单）

### 5.3 上传 MCP JSON 配置

支持三种 JSON 格式：

格式一：`mcpServers` 对象

```json
{
  "mcpServers": {
    "github": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/",
      "enabled": true,
      "description": "GitHub MCP"
    }
  }
}
```

格式二：服务器列表

```json
[
  {
    "name": "filesystem",
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    "enabled": true,
    "description": "本地文件系统工具"
  }
]
```

格式三：单个服务器对象

```json
{
  "name": "arxiv",
  "type": "http",
  "url": "https://arxiv.org/mcp/sse",
  "tools": [
    {
      "name": "search_papers",
      "description": "搜索 arXiv 论文"
    }
  ]
}
```

在「MCP 服务器」页选择 `.json` 文件上传，系统自动解析并批量注册。

> （此处需要插图：MCP JSON 上传入口与服务器列表截图）

### 5.4 相关接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/agent/mcp` | 列出 MCP 服务器 |
| POST | `/api/v1/agent/mcp` | 新增 / 覆盖服务器 |
| DELETE | `/api/v1/agent/mcp/{name}` | 删除服务器 |
| POST | `/api/v1/agent/mcp/test/{name}` | 测试连通性 |
| POST | `/api/v1/agent/mcp/{name}/discover` | 发现并注册服务器工具 |
| GET | `/api/v1/agent/mcp/{name}/tools` | 查看已发现工具 |
| POST | `/api/v1/agent/mcp/{name}/call` | 直接调用某个 MCP 工具 |
| POST | `/api/v1/agent/mcp/upload` | 上传 JSON 批量注册 |
| GET | `/api/v1/agent/capabilities` | 内置工具 + MCP 工具完整目录 |

---

## 六、插件配置流程

### 6.1 插件是什么

插件以 zip 包安装，可同时提供三类能力：

| 能力 | 目录 | 说明 |
| --- | --- | --- |
| Skill | `skills/<dir>/SKILL.md` | Agent Skills 标准技能 |
| 工具 | `tools/<module>.py` | 自包含 Python 工具模块 |
| MCP | `mcp.json` | 插件附带的 MCP 服务器配置 |

官方示例插件 `feed-digest` 已预装，提供 `rss_fetch` 工具与 `feed-digest` 技能，CLI `--feed` 依赖它。

### 6.2 界面安装插件

1. 打开「设置」→「插件」。
2. 点击「上传插件 zip 安装」。
3. 选择插件 zip 包，系统自动识别 `plugin.json`，安装并立即激活。
4. 安装成功后，列表显示插件名称、版本、状态以及注册的能力数量（技能 / 工具 / MCP）。

> （此处需要插图：插件管理页上传按钮与插件列表截图）

### 6.3 启用 / 停用 / 卸载

- 启用：插件默认启用；点击开关可停用后再次启用。
- 停用：反注册该插件的全部 Skill、工具和 MCP 配置，目录保留。
- 卸载：反注册全部能力并删除插件目录。

### 6.4 插件目录结构

```text
my-plugin/
├── plugin.json
├── skills/
│   └── my-skill/
│       └── SKILL.md
├── tools/
│   └── my_tools.py
└── mcp.json
```

### 6.5 plugin.json 清单

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "display_name": "我的插件",
  "description": "插件说明",
  "author": "you",
  "provides": {
    "skills": ["skills"],
    "tools": ["tools/my_tools.py"],
    "mcp": ["mcp.json"]
  }
}
```

校验规则：

- `name` 必须与插件目录名一致，仅允许字母、数字、连字符、下划线，不超过 64 字符。
- zip 根目录或其唯一子目录内必须包含 `plugin.json`。
- `provides` 中声明的路径均相对于插件根目录。

### 6.6 工具模块契约

```python
TOOLS = [
    {
        "name": "my_tool",
        "description": "工具说明（给 LLM 看）",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "查询内容"}
            },
            "required": ["query"]
        },
        "handler": lambda ctx, args: {"result": "ok", "query": args.get("query")},
    }
]
```

工具模块必须自包含，不要 import 应用内部代码。

### 6.7 mcp.json 示例

```json
{
  "mcpServers": {
    "my-server": {
      "type": "http",
      "url": "https://mcp.example.com/sse",
      "enabled": true,
      "description": "插件提供的 MCP 服务器"
    }
  }
}
```

### 6.8 手动放置插件目录（可选）

源码运行时可把插件目录直接放到：

```text
storage/agent/plugins/<plugin-name>/
```

重启后端后自动装载；确保 `plugin.json` 中 `name` 与目录名一致。

### 6.9 相关接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/agent/plugins` | 列出插件 |
| POST | `/api/v1/agent/plugins/install` | 上传 zip 安装 |
| POST | `/api/v1/agent/plugins/{name}/enable` | 启用 |
| POST | `/api/v1/agent/plugins/{name}/disable` | 停用 |
| DELETE | `/api/v1/agent/plugins/{name}` | 卸载 |

> （此处需要插图：插件启停开关与卸载确认弹窗截图）

---

## 七、配置验证清单

按以下顺序自检：

1. 设置页保存 API Key 后，点击「测试连接」应返回模型回复。
2. 在对话中输入 Skill 触发词，应看到路由标签或工具轨迹，而不是 Mock 占位。
3. MCP 服务器「测试」应返回正常。
4. 插件列表应显示「已激活」，并列出注册的技能 / 工具 / MCP 数量。
5. 上传的 Skill 能在「技能 Skills」列表中看到，且可用 `@` 引用。

---

## 八、常见问题

### API Key

- 保存后输入框显示脱敏串属正常，留空保存不会覆盖旧 Key。
- 若填了 Key 但对话仍返回 Mock，检查模型名是否与厂商控制台完全一致，并重新保存。

### Skill

- Skill 不触发时，检查 `trigger_keyword` 是否覆盖用户措辞，以及 `enabled` 是否为 `true`。
- 上传压缩包失败时，确认包内含 `SKILL.md`，文件名必须是 `SKILL.md`（大写）。
- GitHub 导入需要能访问 `api.github.com` 和 `codeload.github.com`。

### MCP

- 「测试」会执行完整 MCP 握手并列出工具，不是简单的 URL/命令可达性检查。
- stdio 服务器需保证命令在 PATH 中可执行（Windows 下 `npx` 会尝试 `npx.cmd`）。
- 删除 MCP 服务器后，其工具会从 Agent 工具目录自动移除。

### 插件

- 安装失败最常见原因是 `plugin.json` 缺失、`name` 不合法或与目录名不一致。
- 停用插件后能力立即反注册；卸载会删除目录，无法恢复。
- 手动修改 `storage/agent/plugins/` 下文件后需重启后端。

---

## 九、配置持久化位置汇总

| 配置 | 持久化位置 |
| --- | --- |
| LLM API Key / Base URL / 模型 / Embedding | 数据库 `app_settings` 表（界面保存）或 `.env` |
| 自定义 Skill | `backend/research_skills/skills_registry.json` |
| 上传 Skill 附属代码 | `storage/agent/skills/` |
| MCP 服务器 | `storage/agent/mcp.json` |
| 插件 | `storage/agent/plugins/<plugin-name>/` |
| CLI 科研 LLM | 环境变量 `RESEARCH_LLM_PROVIDER` 等 |

> 应用内「备份 / 恢复」只覆盖 SQLite 数据库与 PDF 文件；Skill 注册表、MCP 配置、插件目录和 `.env` 需另外复制迁移。

---

## 十、结论

ResearchMate 的四类配置全部围绕本地存储设计：

- API Key 通过设置页或 `.env` 配置，无 Key 也能降级运行；
- Skill 通过注册表管理，支持界面注册、文件上传和 GitHub 导入；
- MCP 通过 `storage/agent/mcp.json` 管理，支持 HTTP/SSE 与 stdio；
- 插件通过 zip 安装，把 Skill、工具、MCP 三类能力统一挂载到 Agent。

按照本指南完成配置后，建议先做第七节的验证清单，再开始实际科研任务。
