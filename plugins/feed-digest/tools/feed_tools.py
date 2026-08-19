"""feed-digest 插件：RSS/Atom 情报抓取工具。

自包含模块（不 import 应用内部代码），遵循插件工具契约：
TOOLS = [{name, description, parameters, handler(ctx, args)}]
"""
import xml.etree.ElementTree as ET

import httpx

# 常用科研情报源（可用 args.urls 覆盖）
DEFAULT_FEEDS = [
    "https://rss.arxiv.org/rss/cs.AI",
    "https://rss.arxiv.org/rss/cs.CL",
]


def _parse_feed(text: str, limit: int) -> list[dict]:
    """容错解析 RSS 2.0 / Atom，返回 [{title, link, published}]。"""
    entries: list[dict] = []
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError:
        return entries

    # RSS 2.0: <channel><item>…
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        if title:
            entries.append({"title": title, "link": link, "published": pub})
        if len(entries) >= limit:
            return entries

    # Atom: <feed><entry>…
    ns = "{http://www.w3.org/2005/Atom}"
    for entry in root.iter(f"{ns}entry"):
        title = (entry.findtext(f"{ns}title") or "").strip()
        link_el = entry.find(f"{ns}link")
        link = (link_el.get("href") or "") if link_el is not None else ""
        pub = (entry.findtext(f"{ns}updated") or "").strip()
        if title:
            entries.append({"title": title, "link": link, "published": pub})
        if len(entries) >= limit:
            break
    return entries


def _rss_fetch(ctx, args: dict) -> dict:
    """抓取 RSS/Atom 订阅源，返回最新条目（供 Agent 汇总成情报摘要）。"""
    urls = args.get("urls") or DEFAULT_FEEDS
    if isinstance(urls, str):
        urls = [urls]
    limit = int(args.get("limit", 10))
    per_feed = max(1, limit // max(1, len(urls)))

    feeds: list[dict] = []
    total = 0
    for url in urls:
        try:
            # 优先复用运行时代理环境（沙箱/内网可正常出网）
            resp = httpx.get(url, timeout=15.0, follow_redirects=True,
                             headers={"User-Agent": "ResearchMate-FeedDigest/1.0"})
            resp.raise_for_status()
            items = _parse_feed(resp.text, per_feed)
        except Exception as e:  # noqa: BLE001
            feeds.append({"url": url, "ok": False, "error": str(e)})
            continue
        feeds.append({"url": url, "ok": True, "count": len(items), "items": items})
        total += len(items)

    return {
        "ok": any(f.get("ok") for f in feeds),
        "feeds": feeds,
        "total": total,
        "tip": "已抓取订阅源条目，可结合 feed-digest 技能生成情报摘要",
    }


TOOLS = [
    {
        "name": "rss_fetch",
        "description": "抓取 RSS/Atom 订阅源（默认 arXiv cs.AI/cs.CL），返回最新条目标题与链接，用于科研情报采集与摘要。",
        "parameters": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "订阅源地址列表；省略时使用默认 arXiv 源",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回条目总数上限，默认 10",
                },
            },
            "required": [],
        },
        "handler": _rss_fetch,
    },
]
