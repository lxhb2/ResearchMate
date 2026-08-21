# ResearchMate 优化与功能路线图

> 版本：v0.3.4（2026-08-21）
> 范围：全项目代码扫描 + 成熟项目/开源生态调研 + 统一优化清单
> 状态：P0 / P1 / P2 与 Agent 强化项全部落地

---

## 一、项目现状结论

ResearchMate 的定位是「本地优先的科研 AI 助手」，当前已经具备文献管理、PDF 解析、六维语义拆分、语义检索、智能阅读、对话问答、写作助手、Agent 工作流、Skill 与插件生态等能力，整体架构清晰、单机部署简单。

扫描后发现的主要问题集中在四类：

1. **安全性**：插件 zip 与 Skill 压缩包存在 Zip Slip / 路径穿越风险；Agent 代码执行沙箱是「名义沙箱」，并非真正的隔离；MCP 目前只保存配置，没有真实客户端。
2. **可靠性**：后台论文解析任务进程内执行，应用重启后任务丢失；备份不完整（漏掉 `storage/agent/`）；DOI 全局唯一约束在多用户/多来源导入时可能冲突。
3. **性能与扩展性**：文献列表先全表加载再 Python 分页；语义检索每次全量扫描 + 内存余弦，文献规模上千篇后会变慢。
4. **产品闭环**：已有 Zotero 导入，但缺少在线元数据补全、全文检索、引用样式（CSL）、收藏/笔记本组织、附件导出等成熟文献管理器的常见能力。

---

## 二、全项目扫描结果

### 2.1 安全风险

| 级别 | 问题 | 位置 | 建议 |
| --- | --- | --- | --- |
| P0 | 插件 zip 安装使用 `zf.extractall()`，恶意包可越过目标目录写文件 | `backend/app/agent/plugin_manager.py` | 逐成员校验后解压（已修复） |
| P0 | Skill 压缩包落地文件时未校验相对路径，`../` 可写出任意外部目录 | `backend/app/agent/skill_store.py` | 规范化路径并限制在目标目录内（已修复） |
| P1 | `sandbox_service` 继承宿主环境变量、可访问网络和文件，不是真实沙箱 | `backend/app/services/sandbox_service.py` | 本地优先用受限子进程 / 可选容器隔离；至少屏蔽危险环境变量 |
| P1 | MCP 只有 `mcp_store` 配置与 `_mcp_tools` 清单，没有真正发起 MCP 调用 | `backend/app/agent/tools.py`、`backend/app/agent/mcp_store.py` | 接入 MCP Python SDK，将远程工具映射为 Agent 工具 |
| P1 | 默认 `SECRET_KEY` 是固定占位值，生产环境存在 JWT 伪造风险 | `backend/app/config.py` | 首启生成随机密钥并写入 `.env`，或要求显式配置 |
| P2 | 备份/恢复只覆盖数据库与 PDF，Agent 技能、插件、MCP 配置、长期记忆不在其中 | `backend/app/routers/backup.py` | 纳入 `storage/agent/`（已修复）并提示重启生效 |

### 2.2 可靠性与任务生命周期

| 级别 | 问题 | 位置 | 建议 |
| --- | --- | --- | --- |
| P0 | 后台解析任务使用 FastAPI `BackgroundTasks`，进程重启即丢失；任务崩溃后 `processing` 永远卡住 | `backend/app/routers/papers.py`、`backend/app/main.py` | 启动时扫描 `processing` / `pending` 并重放（已修复）；长期引入 SQLite 任务队列 |
| P1 | 多用户/多来源导入时 `Paper.doi` 唯一约束是全局的，不是按用户 | `backend/app/models/paper.py` | 迁移为 `(user_id, doi)` 复合唯一索引 |
| P1 | 无 PDF 的条目把 `full_text` 写为摘要，可能与后续“全文检索”语义混淆 | `backend/app/routers/imports.py` | 增加 `is_full_text` / `content_source` 标记 |
| P2 | 工作流任务运行状态只在内存，中断不可恢复 | `backend/app/routers/agent_workflow.py` | 已落地 `WorkflowRun` 持久化记录与恢复接口，执行仍为同步模式 |

### 2.3 性能与规模

| 级别 | 问题 | 位置 | 建议 |
| --- | --- | --- | --- |
| P0 | 文献列表 `q.all()` 后 Python 切片，页数大时浪费内存 | `backend/app/routers/papers.py` | SQL `count + offset/limit`（已修复）；标签过滤保留 Python 兜底 |
| P1 | 语义检索每次全量扫描 `paper_chunks` 并在内存算余弦 | `backend/app/services/search_service.py` | 可选 `sqlite-vec` 或缓存向量矩阵；FTS5 全文检索做召回 |
| P1 | `paper.full_text` 存 TEXT，无全文索引，关键词搜索无法走数据库 | `backend/app/services/search_service.py` | SQLite FTS5 建立全文索引，搜索 `LIKE` 改为 FTS |
| P2 | 大 PDF 全文解析、向量化都在一个后台线程串行 | `backend/app/services/paper_service.py` | 进程池 + 并发数限制 + 进度持久化 |

### 2.4 产品体验与数据闭环

- 阅读器已有 PDF、划词翻译、标注、AI 问答，且已支持**标注/笔记导出**（Markdown / JSON / Zotero RDF）。
- 导入支持 Zotero、BibTeX、RIS，且已支持**在线元数据补全**（DOI / arXiv ID / 标题，Crossref / arXiv / OpenAlex / Semantic Scholar）。
- 已有单篇问答和批量综述，但没有**跨文献笔记本/专题**组织入口。
- 引用目前只支持 BibTeX / GB7714 简化版，缺少完整 CSL 样式体系。

---

## 三、成熟项目与开源生态调研

### 3.1 文献管理器对标

| 项目 | 可借鉴点 |
| --- | --- |
| Zotero | RDF/SQLite/API 导入、附件管理、CSL 引文、浏览器抓取、插件生态 |
| JabRef | BibTeX 为中心、重复检测、在线元数据补全（Crossref / arXiv / PubMed） |
| Paperlib | 本地优先、PDF 全文检索、AI 摘要、快捷导入 DOI/arXiv |
| Mendeley | 全文搜索、标注同步、引用插件 |

结论：ResearchMate 已补齐**在线目录检索**（Crossref / arXiv / OpenAlex / Semantic Scholar）与**全文检索**（FTS5）；CSL 引用按需求不纳入当前路线图。

### 3.2 自托管科研助手对标

| 项目 | 可借鉴点 |
| --- | --- |
| Open Notebook（MIT） | 多笔记本、PDF/视频/音频/网页多源导入、全文 + 向量混合检索、带引用的对话、18+ LLM 提供商、REST API 与 MCP 集成 |
| PaperQuay | 桌面文献管理、翻译、AI 论文概览、Agent 工作台 |

结论：ResearchMate 的“对话 + 检索 + 引用溯源”思路与 Open Notebook 一致；多笔记本/多源导入按需求移除，真实 MCP 客户端与工具调用已落地。

### 3.3 可复用技术栈

- **GROBID**：PDF 元数据/章节/引用抽取，可做可选增强（当前轻量规则解析已够用）。
- **citeproc-py / citeproc-js**：CSL 引文样式渲染。
- **sqlite-vec + FTS5**：本地向量检索与全文检索，无需外部服务。
- **arxiv-mcp / zotero-mcp / research-mcp**：可接入 Agent 的现成 MCP 生态。
- **Zotero 7 本地 API**：只读访问 Zotero 库，可做增量同步与附件监听。

---

## 四、统一优化与功能清单

### 4.1 P0：立即修复（本批次已落地）

- [x] 插件 zip 解压安全：逐成员校验，禁止绝对路径 / `..` 逃逸。
- [x] Skill 压缩包路径穿越防护：目标路径必须落在技能目录内。
- [x] 启动自愈：应用启动时重放卡在 `processing` / `pending` 的论文任务。
- [x] 备份完整性：备份/恢复包含 `storage/agent/`（技能、插件、MCP、长期记忆）。
- [x] 文献列表分页：SQL `count + offset/limit`，避免全表加载。

### 4.2 P1：近期优化

- [x] 真实 MCP 客户端：stdio + HTTP/SSE 握手、工具发现、动态注册进 Agent 工具表。
- [x] Agent 多轮上下文：全局助手注入当前会话最近对话历史，支持追问与连续任务。
- [x] Agent 任务持久化：多步任务落到 SQLite 任务表，支持中断恢复与重试（替代内存 BackgroundTasks）。
- [x] 在线元数据补全：DOI / arXiv ID / 标题可经 Crossref、arXiv、OpenAlex、Semantic Scholar 拉取元数据。
- [x] FTS5 全文检索：对 `title` / `authors` / `abstract` / `full_text` 建索引，并新增 `/search/fulltext`。
- [x] DOI 按用户去重：新库使用 `(user_id, doi)` 复合唯一约束，旧库自动补复合索引。
- [x] 密钥管理：首启生成随机 `SECRET_KEY` 并持久化；落库 API Key 使用 Fernet 加密。
- [x] 持久化任务队列：`agent_tasks` 表 + 后台 worker + `/tasks` 状态与重试接口。
- [x] 沙箱隔离：Agent 代码子进程默认过滤密钥/代理环境变量、隔离模式运行、限制工作目录与超时。
- [x] 标注/笔记导出：支持 Markdown / JSON / Zotero RDF。

### 4.3 P2：产品功能路线（仅保留最后三项）

- [x] 文档/图表导出：写作项目支持 Markdown / Word / 浏览器打印 HTML（可另存为 PDF）。
- [x] 多语言术语表与翻译记忆：个人术语表本地 JSON 持久化，翻译可一键入表。
- [x] 桌面集成：Electron 单实例、PDF/Bib/RIS 文件关联、系统通知、托盘常驻。
- [x] 局域网访问：默认监听 `0.0.0.0`，提供 `allow_lan.bat` 防火墙放行脚本与手机访问说明。

> 其余原 P2 项（Zotero 深度集成、CSL 引文、笔记本工作区、网页/RSS/视频导入、OCR、GROBID）
> 按需求已从路线图移除，不纳入后续实施。

### 4.4 Agent 功能补全（本轮重点）

Agent 是后续功能投入的重心，借鉴 OpenAI Swarm、OpenManus、AutoGPT、CrewAI、MetaGPT 的核心设计：

- [x] 多轮会话上下文：全局助手不再只凭当前一句话，而是携带最近对话历史。
- [x] 真实 MCP 客户端：stdio / HTTP / SSE 服务器可被发现、动态注册为 `mcp__<server>__<tool>` 并直接调用。
- [x] 工具目录：`/agent/tools` 返回内置工具与 MCP 工具，助手中心新增「工具 Tools」页。
- [x] 专用 Agent 路由：RAG / 数据 / 实验 / 写作四类轻量编排。
- [x] Skill 调度：337 个内置科研 Skill + 上传 / GitHub 导入。
- [x] 长期记忆：用户画像 / 知识沉淀 / 笔记 / 交互日志，跨对话共享。
- [x] 工作流执行器：串行、条件分支、人工确认、重试、错误策略。
- [x] 计划 + 执行循环：`workflow_execute` 工具把一句话任务自动拆成多步工作流并执行。
- [x] 反思循环：`workflow_execute` 与 Skill 执行结束后自动把反思摘要写入长期记忆。
- [x] 会话摘要记忆：长对话自动压缩为摘要写入 `conversations.md`，通过后台任务执行。
- [x] Agent 事件流：新增 `/chat/events`，对话页实时展示 thinking / tool_start / tool_result / answer。

---

## 五、建议实施顺序

1. P0 已全部完成：安全加固 + 启动自愈 + 备份完整 + 分页。
2. P1 已全部完成：持久化任务队列、在线元数据补全、FTS5 全文检索、DOI 按用户去重、
   密钥管理、Agent 沙箱隔离、标注/笔记导出，以及真实 MCP 客户端与多轮上下文。
3. Agent 反思循环、会话摘要记忆、事件流（含前端接入）、P2 三项与局域网访问均已落地。

---

## 六、验收建议

- 单元测试：`cd backend; .\.venv\Scripts\python -m pytest -q`。
- 安全回归：构造含 `../evil` 的插件 zip / Skill zip，确认不会写出目标目录。
- 自愈回归：把一条论文记录手动改为 `status=processing` 后重启服务，确认自动重新解析。
- 备份回归：写入技能/插件/MCP 配置后导出备份，恢复到一个空库，确认 Agent 数据一并恢复。
- MCP 回归：配置一个本地 stdio MCP 服务器，执行「发现」，确认工具出现在 `/agent/tools` 且对话可直接调用。

> （此处需要插图：P0/P1/P2 优先级路线图）  
> （此处需要插图：当前架构到目标架构的差异图）
