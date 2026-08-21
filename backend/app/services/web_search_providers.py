"""联网搜索提供方：AnySearch 匿名 REST + 可选 SearXNG 自建实例。

AnySearch Skill/MCP 仓库采用 Apache-2.0，这里只调用其公开 HTTP API，
不复制第三方代码；查询会发送到 api.anysearch.com，官方声明为匿名可用、
零保留执行。若需要完全本地化，可配置 SEARXNG_URL 指向自建 SearXNG。
"""

from __future__ import annotations

import html
import os
import re
from typing import Any

import httpx

from app.config import settings

_TAG_RE = re.compile(r"<[^>]+>")


def anysearch_enabled(config: dict[str, Any] | None = None) -> bool:
    if config is not None:
        return bool(config.get("enabled", settings.ANYSEARCH_ENABLED))
    env = os.environ.get("ANYSEARCH_ENABLED", "").strip().lower()
    if env:
        return env not in ("0", "false", "no", "off")
    return bool(settings.ANYSEARCH_ENABLED)


def anysearch_api_key(config: dict[str, Any] | None = None) -> str:
    if config is not None:
        return str(config.get("api_key") or "")
    return (
        os.environ.get("ANYSEARCH_API_KEY", "").strip()
        or settings.ANYSEARCH_API_KEY.strip()
    )


def _clean_text(raw: str) -> str:
    text = _TAG_RE.sub(" ", raw or "")
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def _anysearch_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") or {}
    items: list[dict[str, Any]] = []
    for row in data.get("results") or []:
        title = (row.get("title") or "").strip()
        url = (row.get("url") or "").strip()
        if not title or not url.startswith(("http://", "https://")):
            continue
        items.append(
            {
                "title": title,
                "url": url,
                "snippet": _clean_text(row.get("snippet") or row.get("content") or "")[:500],
                "date": (row.get("date") or "").strip(),
                "source": "anysearch",
            }
        )
    return items


def anysearch_search(
    query: str,
    limit: int = 5,
    timeout: float = 30.0,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = str(
        (config or {}).get("base_url")
        or settings.ANYSEARCH_BASE_URL
        or "https://api.anysearch.com"
    ).rstrip("/")
    key = anysearch_api_key(config)
    headers = {
        "Content-Type": "application/json",
        "X-Anysearch-Client": f"researchmate/{settings.APP_VERSION}",
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"
    payload = {
        "query": query,
        "max_results": max(1, min(int(limit or 5), 10)),
    }
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.post(f"{base}/v1/search", json=payload, headers=headers)
        resp.raise_for_status()
        body = resp.json()
    if not isinstance(body, dict) or body.get("code", 0) != 0:
        raise RuntimeError(str(body.get("message") or "AnySearch 返回异常"))
    items = _anysearch_items(body)
    return {"count": len(items), "query": query, "engine": "anysearch", "items": items}


def anysearch_extract(url: str, timeout: float = 60.0, config: dict[str, Any] | None = None) -> str:
    base = str(
        (config or {}).get("base_url")
        or settings.ANYSEARCH_BASE_URL
        or "https://api.anysearch.com"
    ).rstrip("/")
    key = anysearch_api_key(config)
    headers = {
        "Content-Type": "application/json",
        "X-Anysearch-Client": f"researchmate/{settings.APP_VERSION}",
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.post(f"{base}/v1/extract", json={"url": url}, headers=headers)
        resp.raise_for_status()
        body = resp.json()
    if not isinstance(body, dict) or body.get("code", 0) != 0:
        raise RuntimeError(str(body.get("message") or "AnySearch 提取失败"))
    data = body.get("data") or {}
    title = (data.get("title") or "").strip()
    content = (data.get("content") or "").strip()
    parts = [f"# {title}", f"**Source**: {data.get('url', url)}", "---", content]
    return "\n\n".join(p for p in parts if p)


def searxng_configured(config: dict[str, Any] | None = None) -> bool:
    if config is not None:
        return bool((config.get("searxng_url") or "").strip())
    return bool((settings.SEARXNG_URL or "").strip())


def searxng_search(
    query: str,
    limit: int = 5,
    timeout: float = 30.0,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = str(
        (config or {}).get("searxng_url") or settings.SEARXNG_URL or ""
    ).strip().rstrip("/")
    if not base:
        raise RuntimeError("未配置 SearXNG URL")
    headers = {"Accept": "application/json", "User-Agent": f"ResearchMate/{settings.APP_VERSION}"}
    params = {
        "q": query,
        "format": "json",
        "language": "auto",
        "safesearch": "0",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(f"{base}/search", params=params, headers=headers)
        resp.raise_for_status()
        body = resp.json()
    items: list[dict[str, Any]] = []
    for row in (body.get("results") or [])[: max(1, min(int(limit or 5), 10))]:
        title = (row.get("title") or "").strip()
        url = (row.get("url") or "").strip()
        if not title or not url.startswith(("http://", "https://")):
            continue
        items.append(
            {
                "title": title,
                "url": url,
                "snippet": _clean_text(row.get("content") or row.get("snippet") or "")[:500],
                "date": (row.get("publishedDate") or row.get("date") or "").strip(),
                "source": "searxng",
            }
        )
    return {"count": len(items), "query": query, "engine": "searxng", "items": items}
