# ResearchMate 科研助手

面向科研人员的**本地化 AI 学术助手**：文献库管理、语义检索、智能阅读、写作辅助、对话问答、工作流编排与科研 Skill 集成。**单机单用户、数据完全本地存储、轻量化**，无云端、无服务器依赖。

---

## ✨ 功能特性

- **文献库**：上传 PDF，本地解析并自动拆分为 **6 个语义维度**（标题关键词 / 背景 / 方法 / 结果 / 结论 / 创新点）
- **语义检索**：6 维向量语义搜索（内存余弦计算）+ 关键词降级，无 Embedding API 也能用
- **智能阅读器**：PDF 阅读、划词翻译/解释/高亮、笔记批注；「论文分析」页合并 AI 拆分维度 + 你的阅读笔记
- **写作助手**：写作项目管理、笔记追加、引用生成（GB7714 等）
- **对话（顶层 Agent）**：统一对话入口，自动路由——科研 Skill / 专用 Agent（文献/数据/实验/写作）/ 智能问答
- **翻译 / 术语**：论文翻译、术语查询
- **Agent 工作流**：模板库（默认固定模板 + 自定义模板）、对话式执行、白板式拖拽、自然语言生成工作流
- **科研 Skill 集成**：**337 个内置 Skill**（综述/写作/评审/选题/实验等，整合 anthropics/skills 与 6 大科研技能仓库），注册表管理 + 调度 + 持久记忆 + 评审，支持 GitHub 一键导入
- **插件生态**：zip 包安装插件，扩展技能 / 工具 / MCP 服务器配置；启用、停用、卸载全生命周期管理
- **备份 / 恢复**：SQLite + PDF 一键打包备份
- **CLI**：`python main.py --research "..."` 直接跑科研任务

---

## 📁 目录结构

```
ResearchMate/
├── backend/                后端（FastAPI + SQLAlchemy + SQLite）
│   ├── app/                应用代码（路由 / 服务 / Agent 工作流 / 顶层Agent / 插件管理）
│   ├── research_skills/    科研 Skill 模块（注册表 / 调度 / 记忆 / 评审，自包含）
│   ├── main.py             CLI 入口
│   ├── requirements.txt    依赖清单
│   └── .env.example        配置模板
├── frontend/               前端（React + Vite + TS + Ant Design）
│   └── dist/               构建产物（绿色包/单端口模式使用）
├── start.sh                Linux / macOS 启动脚本
└── start.bat               Windows 启动脚本
```

---

## 🚀 快速开始

### 方式一：绿色便携包（推荐，无需环境）

解压后在项目根目录：

- **Windows**：双击 `start.bat`，浏览器访问 `http://localhost:8000/`
- **Linux / macOS**：
  ```bash
  chmod +x start.sh
  ./start.sh
  ```
  首次运行自动创建虚拟环境、安装依赖。

### 方式二：源码运行

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 单端口（后端 + 前端 dist 一起托管）
FRONTEND_DIST=../frontend/dist uvicorn app.main:app --host 127.0.0.1 --port 8000
```

> 换端口：设环境变量 `PORT`（如 `PORT=8012`），或改 start 脚本里的端口。

---

## ⚙️ 配置教程

### 1. 数据库（默认零配置）

轻量化默认使用 **SQLite 单文件** `backend/researchmate.db`，**无需** PostgreSQL / pgvector / GROBID。首次启动自动建表、自动建默认用户。

### 2. 大模型（LLM）配置

有两种方式，**运行时「设置」页 优先**：

#### 方式 A：应用内「设置」页（推荐，可随时改）
打开应用 → 顶部/侧边「设置」→ 填写：
- **接口地址（Base URL）**、**API Key**、**模型名称**
- 点「连接测试」验证 → 保存

支持一切 OpenAI 兼容接口（OpenAI、DeepSeek、通义、Kimi、本地 vLLM/Ollama 兼容层等）。

#### 方式 B：环境变量 `.env`（默认值）
复制后端配置模板并在其中填写：
```bash
cd backend
cp .env.example .env
# 编辑 .env，至少设置：
LLM_API_KEY=sk-你的key
LLM_BASE_URL=https://api.openai.com/v1   # 兼容接口地址
LLM_MODEL=gpt-4o
```

> **不配置也能用**：无 Key 时自动降级为**离线 Mock 模式**；文献检索自动降级为**关键词匹配**。

### 3. 使用本地 Ollama（可选）

- 安装并启动 Ollama：`ollama pull llama3`（或 qwen2.5 等）
- 在「设置」页填：Base URL `http://localhost:11434`、模型 `llama3`
- 或 `.env` 中：
  ```bash
  LLM_BASE_URL=http://localhost:11434
  LLM_MODEL=llama3
  ```

### 4. 科研 Skill 模块的 LLM（CLI 用）

CLI 科研任务走 `RESEARCH_LLM_PROVIDER`（`ollama | openai | mock | auto`）：
```bash
# 本地 Ollama
RESEARCH_LLM_PROVIDER=ollama RESEARCH_OLLAMA_MODEL=llama3 python main.py --research "..."
# OpenAI 兼容
RESEARCH_LLM_PROVIDER=openai RESEARCH_OPENAI_API_KEY=sk-xxx python main.py --research "..."
# 离线占位（无需 Key）
RESEARCH_LLM_PROVIDER=mock python main.py --research "..."
```

### 5. 自动化测试

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest -q
```

CI 已配置：每次 push/PR 自动运行后端 pytest 与前端构建（`.github/workflows/ci.yml`）。

### 6. 其他常用配置（`.env`）

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `AUTO_LOGIN` | 自动登录（单机部署跳过登录页） | `true` |
| `AUTO_LOGIN_USERNAME` / `_PASSWORD` | 默认账号 | `researcher` / `researchmate` |
| `DATABASE_URL` | 数据库地址 | `sqlite:///./researchmate.db` |
| `FRONTEND_DIST` | 前端 dist 目录（单端口托管时设） | 空 |
| `SECRET_KEY` | JWT 密钥（生产请改） | 占位 |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` | 向量模型与维度 | `text-embedding-3-small` / `1536` |
| `ANYSEARCH_ENABLED` | 启用 AnySearch 匿名联网搜索（Apache-2.0 开源项目，公开 API） | `true` |
| `ANYSEARCH_API_KEY` | AnySearch 免费 API Key，提高限流（可选） | 空 |
| `SEARXNG_URL` | 自建 SearXNG 地址，配置后优先使用（开源免费、本地化） | 空 |

### 7. 可选：整篇 PDF 翻译（pdf2zh-next / BabelDOC）

阅读器「整篇翻译」按钮默认优先使用 **pdf2zh-next（PDFMathTranslate-next）**，
保持原版式输出双语 PDF，支持上百页长文献；未安装时自动回退 BabelDOC。
推荐安装方式（隔离环境，不影响主程序依赖）：

```bash
cd backend
.\scripts\install_pdf2zh.ps1
```

或手动执行：

```bash
py -3.12 -m venv .venv-pdf2zh
.venv-pdf2zh\Scripts\python -m pip install -r requirements-pdf2zh.txt
```

整篇翻译的引擎选择：默认使用 **SiliconFlow Free** 免费服务（零配置），
也可在 `.env` 配置 `PDF2ZH_SILICONFLOW_API_KEY`、`PDF2ZH_ENGINE=siliconflow|openai|deepl`。

### 8. 可选：DeepL 翻译加速

配置 `DEEPL_API_KEY`（与 `DEEPL_API_URL`，默认免费版地址）后，短句/术语翻译会优先走 DeepL，速度比 LLM 更快；未配置时自动回退 LLM。

划词翻译还会自动使用 pdf2zh-next 同款的 SiliconFlow Free 服务加速短句/段落；
如需关闭，在 `.env` 设置 `TRANSLATION_FREE_SERVICE=0`。

---

## 🖥️ CLI 用法

```bash
cd backend
python main.py --list-skills                 # 列出已注册的科研 Skill
python main.py --research "文献综述：一人公司商业模型，结合OPC概念" --provider mock
python main.py --feed                         # 情报采集（feed-digest 插件，抓 RSS 落盘 output/feed/）
python main.py --research "..." --provider ollama   # 指定 LLM 提供方
python main.py --research "..." --review      # 执行后用 Supervisor 评审
python main.py --rebuild-registry             # 从 templates/ 重建 Skill 注册表
```

---

## 💾 数据存储位置

| 数据 | 位置 |
| --- | --- |
| 数据库 | `backend/researchmate.db`（SQLite 单文件） |
| PDF 文件 | `backend/storage/pdfs/` |
| 科研产物（Markdown） | `backend/output/research/`（含 findings.md / research-state.yaml 记忆） |
| 情报产物 | `backend/output/feed/` |

> 备份 = 复制以上文件；应用内置「备份/恢复」可一键打包为 ZIP。

---

## ❓ FAQ

- **启动后浏览器打不开？** 确认端口未被占用，或改 `PORT` 后重开。
- **文献检索没结果？** 未配 Embedding Key 时为关键词检索，可先上传并处理论文再检索。
- **对话一直返回 Mock 占位？** 说明未配置可用 LLM，去「设置」页填 Key/模型。
- **科研 Skill 输出是占位符？** 用 `--provider openai` 或 `--provider ollama` 配置真实模型。

  ==本项目由AI编程实现==

---

## 🧩 插件生态

后续新增能力优先以**插件**方式接入（无需改主程序）。在「设置 → 插件」页上传 zip 安装，即刻生效。

插件目录结构：

```
my-plugin/
├── plugin.json          # 清单（必需）
├── skills/<dir>/SKILL.md    # 技能（Agent Skills 标准）
├── tools/my_tools.py        # 工具模块（定义 TOOLS 列表）
└── mcp.json                 # MCP 服务器配置（可选）
```

`plugin.json` 清单：

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

工具模块契约（自包含，不 import 应用内部代码）：

```python
TOOLS = [
    {
        "name": "my_tool",
        "description": "工具说明（给 LLM 看）",
        "parameters": {"type": "object", "properties": {...}, "required": [...]},
        "handler": lambda ctx, args: {"result": ...},   # ctx: ToolContext
    },
]
```

- **安装**：上传 zip（根目录或唯一子目录含 `plugin.json`），自动注册技能 / 工具 / MCP
- **停用**：反注册全部能力，目录保留，可随时再启用
- **卸载**：反注册并删除目录
- 管理接口：`GET/POST /api/v1/agent/plugins`（详见 `/docs`）
- **官方示例插件**：`feed-digest`（RSS 情报采集，源码见 `plugins/feed-digest/`）已预装——提供 `rss_fetch` 工具与 `feed-digest` 技能，CLI `--feed` 即走此插件

---

## 🛠️ 开发说明

- 架构分层：`app/routers`（API）→ `app/services`（业务）→ `app/agent`（Agent/工作流）→ `research_skills`（Skill 模块，自包含）
- 前端构建：`cd frontend && npm install && npm run build`（产物在 `frontend/dist`）
- 交互式 API 文档：后端启动后访问 `http://localhost:8000/docs`
