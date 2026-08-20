# ResearchMate 优化记录

> 记录日期：2026-08-20
> 范围：Zotero 导入修复、P0 安全与可靠性加固、P1 功能补全、Agent 核心集成
> 验证：后端 32 个测试通过、前端 TypeScript 检查与生产构建通过

---

## 一、Zotero 导入修复

| 问题 | 处理 | 位置 |
| --- | --- | --- |
| 输入 `C:\Users\Administrator\Zotero` 无法解析 | Zotero 数据库被占用时自动重试，并复制 DB + WAL/SHM 到临时快照解析 | `backend/app/services/import_service.py` |
| 解析到的论文打不开、PDF 识别不到、打开报 404 | 识别 `linkMode=0` / `storage:` 附件、无父条目的独立 PDF，导入时复制入库并补附件 | `backend/app/routers/imports.py`、`backend/app/services/import_service.py` |
| 重新导入旧记录不补 PDF | 无 DOI 记录按来源 + 标题匹配，缺附件时自动回填并重新解析 | `backend/app/routers/imports.py` |

验证结果：真实 Zotero 目录解析 `82` 条文献、`77` 个 PDF，无报错。

---

## 二、P0：安全与可靠性

| 项目 | 状态 | 位置 |
| --- | --- | --- |
| 插件 zip 解压防 Zip Slip | 已完成 | `backend/app/agent/plugin_manager.py` |
| Skill 压缩包路径穿越防护 | 已完成 | `backend/app/agent/skill_store.py` |
| 启动自愈：重放 `processing` / `pending` 论文 | 已完成 | `backend/app/main.py` |
| 备份完整性：纳入 `storage/agent/` | 已完成 | `backend/app/routers/backup.py` |
| 文献列表 SQL 分页 | 已完成 | `backend/app/routers/papers.py` |

---

## 三、P1：功能补全

| 项目 | 状态 | 位置 |
| --- | --- | --- |
| 持久化任务队列：`agent_tasks` 表 + worker + 重试 + 进度页 | 已完成 | `backend/app/models/agent_task.py`、`backend/app/services/task_queue.py`、`backend/app/routers/tasks.py` |
| 在线元数据补全：Crossref / arXiv / OpenAlex / Semantic Scholar | 已完成 | `backend/app/services/metadata_service.py`、`backend/app/routers/imports.py` |
| FTS5 全文检索：标题/作者/摘要/全文索引 | 已完成 | `backend/app/services/fts_service.py`、`backend/app/routers/search.py` |
| DOI 按用户去重：`(user_id, doi)` 复合唯一约束 | 已完成 | `backend/app/models/paper.py`、`backend/app/main.py` |
| 密钥管理：随机 `SECRET_KEY` + API Key Fernet 加密 | 已完成 | `backend/app/config.py`、`backend/app/utils/secrets.py`、`backend/app/services/settings_service.py` |
| Agent 代码沙箱：隔离环境、过滤密钥、超时 | 已完成 | `backend/app/services/sandbox_service.py` |
| 标注/笔记导出：Markdown / JSON / Zotero RDF | 已完成 | `backend/app/services/annotation_export.py`、`backend/app/routers/annotations.py` |

---

## 四、Agent 核心集成

| 项目 | 状态 | 位置 |
| --- | --- | --- |
| 真实 MCP 客户端：stdio / HTTP / SSE 握手与工具调用 | 已完成 | `backend/app/agent/mcp_client.py` |
| MCP 动态工具注册：`mcp__<服务器>__<工具>` | 已完成 | `backend/app/agent/mcp_runtime.py` |
| 多轮会话上下文 | 已完成 | `backend/app/agent/top_agent.py`、`backend/app/routers/chat.py` |
| `workflow_execute`：一句话任务自动拆解并执行 | 已完成 | `backend/app/agent/tools.py` |
| 工具目录与助手中心「工具 Tools」页 | 已完成 | `backend/app/routers/agent.py`、`frontend/src/pages/AgentCenterPage.tsx` |
| 助手中心「任务 Tasks」进度页 | 已完成 | `frontend/src/pages/AgentCenterPage.tsx` |

---

## 五、验证结果

```bash
cd backend
.\.venv\Scripts\python -m pytest -q
# 31 passed

cd frontend
npx tsc --noEmit -p tsconfig.json --pretty false
# 通过
```

说明：完整 `npm run build` 因 `frontend/tsconfig.tsbuildinfo` 被占用（`EPERM`，疑似编辑器/TS Server 锁定）未完成，类型检查已通过。

---

## 六、当前完成状态

路线图 P0 / P1 / P2 与 Agent 强化项均已落地：

- **P0**：安全加固、启动自愈、备份完整性、分页。
- **P1**：持久化任务队列、在线元数据补全、FTS5 全文检索、DOI 按用户去重、密钥管理、Agent 沙箱、标注/笔记导出。
- **Agent**：真实 MCP 客户端、多轮上下文、`workflow_execute`、会话摘要记忆、反思沉淀、实时事件流（含前端接入）、工具与任务进度页。
- **P2**：文档/图表导出、术语表与翻译记忆、桌面集成（单实例、文件关联、系统通知、托盘常驻）。
- **局域网访问**：默认监听 `0.0.0.0`，启动脚本支持 `HOST` 覆盖，提供 `allow_lan.bat` 防火墙放行。

## 七、写作模块优化

- 写作向导新增「上一步 / 下一步」导航，步骤间流转更清晰。
- 选题、大纲、草稿每一步都可自由选择中文或英文生成。
- 摘要步骤改为同时生成中英文摘要与中英文关键词，适配国内论文投稿要求。
- 新增学术写作规范库 `backend/app/services/writing_guide.py`：
  - 英文侧融合 Glasman-Deal《Science Research Writing》的 IMRaD、叙事包裹、句子/段落功能、动词时态与读者导向原则；
  - 中文侧适配国内学术规范（摘要目的/方法/结果/结论四要素、GB/T 7714 参考文献、学术书面语）。
- 素材检索接入 RAG 6 维向量库：按章节标题自动映射到 background / method / results / conclusion / contributions 等维度。
- Word 导出会包含中英文摘要与关键词。

## 八、整篇 PDF 翻译加速（BabelDOC）

- 评估 BabelDOC：可胜任 PDF 整篇翻译，保持原版式并输出双语 PDF，适合替代逐段 LLM 翻译的慢速链路。
- 新增可选接入：`backend/app/services/babeldoc_service.py` 调用 BabelDOC CLI，阅读器新增「整篇翻译」按钮。
- 未安装时自动提示 `pip install -r requirements-babeldoc.txt`，不影响原有划词翻译流程。

已被需求移除、不在当前路线图内的可选方向：Zotero 深度集成、CSL 引文、笔记本/专题工作区、网页 / RSS / 视频多源导入、OCR、GROBID。
