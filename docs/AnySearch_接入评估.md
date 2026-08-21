# AnySearch 接入评估

> 更新：2026-08-21

## 结论

AnySearch 可以接入 ResearchMate，且已按“直接调用公开 REST API”的方式落地。
项目本体为 Apache-2.0，我们只调用其 HTTP 接口，不复制第三方源码，因此不涉及
对 Apache 源码的再分发义务；使用其在线服务仍需遵守 AnySearch 的服务条款与隐私政策。

## 项目信息

- `anysearch-ai/anysearch-skill`：统一实时搜索 Skill，约 5.8k stars，Apache-2.0
- `anysearch-ai/anysearch-mcp-server`：MCP 服务器说明仓库，Apache-2.0
- 能力：通用网页搜索、垂直领域搜索、并行批量搜索、URL 全文提取
- 匿名可用，无需 API Key；也可在 anysearch.com 注册免费 Key 提高限流

## 法律与隐私边界

- Apache-2.0 允许商用、修改、嵌入，只要保留版权声明与许可文本；本实现不复制其代码，
  仅按公开 API 文档调用。
- 匿名模式会把搜索关键词发送到 `https://api.anysearch.com`；官方声明为零保留执行、
  零知识凭据、无追踪无日志。
- 涉及密码、身份证、商业机密、患者数据等敏感内容时，不建议使用在线搜索，应关闭
  `ANYSEARCH_ENABLED=false` 或改用自建 SearXNG。

## 已实现方式

后端新增 `backend/app/services/web_search_providers.py`：

- 默认启用 AnySearch，`web_search` 工具优先调用 `/v1/search`；
- AnySearch 失败或关闭时自动回退 Bing RSS / Bing HTML / DuckDuckGo；
- 对话中输入“搜索/查一下/最新资料”等联网意图时，即使未手动打开联网开关也会自动走 `web_search`；
- 可选配置 `ANYSEARCH_API_KEY` 提高限流；
- 可选配置 `SEARXNG_URL=http://localhost:8888`，自建 SearXNG 时优先使用；
- 配置项均写入 `backend/.env.example`，可在 `.env` 中修改。

## 开源免费替代

如果希望完全本地化，推荐 **SearXNG**：

- 开源元搜索引擎，AGPL-3.0，可自托管；
- 提供 HTTP JSON API，ResearchMate 仅调用接口，不复制其代码；
- 配置 `SEARXNG_URL` 后自动成为默认搜索提供方；
- 也可关闭 AnySearch：`ANYSEARCH_ENABLED=false`。

## 可选 MCP 方式

如需保留“MCP 服务器”形态，可连接远程端点：

```json
{
  "name": "anysearch",
  "type": "http",
  "url": "https://api.anysearch.com/mcp",
  "headers": {
    "X-Anysearch-Client": "mcp/1.0.0"
  }
}
```

当前 ResearchMate 已直接接入 REST，MCP 方式可作为后续增强。
