# ResearchMate 优化记录

> 记录日期：2026-08-21
> 范围：Zotero 导入修复、P0 安全与可靠性加固、P1 功能补全、Agent 核心集成、pdf2zh-next 整篇翻译与划词加速
> 验证：后端 43 个测试通过、前端 TypeScript 检查与生产构建通过

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

## 九、段落/词级翻译速度与悬浮体验

- 新增本地翻译缓存：重复短句/术语直接秒回，减少 LLM 调用。
- 可选 DeepL API 直连：配置 `DEEPL_API_KEY` 后，短文本优先走 DeepL，速度更快。
- 新增 `/translate/batch` 批量并发翻译，支持长段落/多选片段加速。
- 阅读器改为 DeepL 式悬浮翻译卡：选中文字点击「翻译」后，译文在选区附近实时流式展示，可复制/关闭。

## 十、pdf2zh-next 整篇翻译与划词加速（2026-08-21）

- 完整阅读并评估 PDFMathTranslate-next（pdf2zh-next 2.9.0）：基于 BabelDOC，支持保持版式的双语 PDF、上百页长文献、SiliconFlow Free 免费服务，速度明显优于直接串行调用 BabelDOC。
- 采用隔离环境接入：`backend/.venv-pdf2zh` 独立安装 pdf2zh-next，避免 Gradio/scipy/onnx 等依赖污染主程序；提供 `backend/scripts/install_pdf2zh.ps1` 一键安装。
- 新增 `backend/app/services/pdf2zh_service.py` 与 `backend/scripts/pdf2zh_bridge.py`：后端通过桥接进程调用，Windows 隐藏命令窗口，解析 pdf2zh 进度事件并持久化到任务结果。
- 任务队列改造：整篇翻译优先 pdf2zh-next，失败自动回退 BabelDOC；前端显示实时进度、阶段与所用引擎，避免 120s 超时。
- 划词翻译优化：短文本/段落（≤5000 字符）按「术语表 → 本地缓存 → DeepL → SiliconFlow Free → 快速 LLM」链路返回，长文本才走 LLM 流式；前端增加请求序号防串卡并提升长文本直连阈值。
- 配置项：`PDF2ZH_ENGINE`、`PDF2ZH_SILICONFLOW_API_KEY`、`PDF2ZH_SILICONFLOW_MODEL`、`TRANSLATION_FREE_SERVICE` 等，详见 `backend/.env.example`。
- 风险提示：pdf2zh-next 与 BabelDOC 同属 AGPL-3.0；SiliconFlow Free 有配额/限速，失败时会自动回退，如需稳定可配置 SiliconFlow / OpenAI / DeepL Key。

## 十一、联网搜索默认提供方与版本显示防残留（2026-08-21）

- 前端版本显示残留 `v0.3.0` 的根因：`AppLayout` 与设置页存在写死的旧版本号，设置页还用 `0.3.0` 作为 API 失败兜底。
- 修复：构建时由 `package.json` 注入 `__APP_VERSION__`，运行态按“后端 `/app/info` → Electron `getVersion()` → 构建版本”三级读取，彻底移除写死的版本号。
- MCP `clientInfo` 版本也改为读取 `settings.APP_VERSION`，不再出现 0.3.0 残留。
- 接入 AnySearch：项目 `anysearch-skill` / `anysearch-mcp-server` 为 Apache-2.0，提供匿名可用的 REST API；新增 `backend/app/services/web_search_providers.py`，`web_search` 工具默认优先调用 AnySearch，失败回退 Bing / DuckDuckGo。
- 开源替代：支持自建 SearXNG（AGPL-3.0，仅通过 HTTP JSON API 调用，不复制其代码），配置 `SEARXNG_URL` 后优先于 AnySearch，满足完全本地化需求。
- 隐私说明：AnySearch 匿名模式会把搜索关键词发送到 `https://api.anysearch.com`，官方声明为零保留；如不能接受，可关闭 `ANYSEARCH_ENABLED=false` 或配置 SearXNG。

## 十二、搜索 API 配置界面与 v0.3.2 发布（2026-08-21）

- 设置页新增「联网搜索 API 配置」卡片：可开关 AnySearch、填写 AnySearch API Key / Base URL、SearXNG 地址，并提供「测试搜索连接」按钮。
- 搜索配置持久化到用户设置（`anysearch_enabled` / `anysearch_api_key` / `anysearch_base_url` / `searxng_url`），`web_search` 工具实时读取，无需重启。
- 顶层 Agent 增加联网意图自动识别：输入“搜索/查一下/最新资料/学术名词”等会直接调用 `web_search`，不会被本地 RAG 路由抢占。
- 新增操作指南文案与 `docs/AnySearch_接入评估.md`，说明搜索链路、隐私边界与开源替代。
- 版本号统一升级为 `v0.3.2`，重新打包 Electron 安装包并上传 GitHub Release。

## 十三、整篇翻译引擎打包与回退修复（v0.3.3，2026-08-21）

- 修复打包后 `pdf2zh-next 未安装`：Electron 现在把 `backend/scripts/pdf2zh_bridge.py` 作为资源打进安装包，并在启动后端时注入 `PDF2ZH_BRIDGE`。
- 修复 BabelDOC 回退误报：`babeldoc_service.is_available()` 会先探测 CLI 是否能真正启动，不再把损坏的半成品 `babeldoc.exe` 当成可用引擎。
- 新增 `/api/v1/translate/pdf/engines` 诊断接口，可查看 pdf2zh/BabelDOC 的可用状态与实际路径，方便排查。

已被需求移除、不在当前路线图内的可选方向：Zotero 深度集成、CSL 引文、笔记本/专题工作区、网页 / RSS / 视频多源导入、OCR、GROBID。
