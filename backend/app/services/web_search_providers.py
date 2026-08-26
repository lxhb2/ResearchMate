"""联网搜索提供方：AnySearch 匿名 REST + 可选 SearXNG 自建实例。

AnySearch Skill/MCP 仓库采用 Apache-2.0，这里只调用其公开 HTTP API，
不复制第三方代码；查询会发送到 api.anysearch.com，官方声明为匿名可用、
零保留执行。若需要完全本地化，可配置 SEARXNG_URL 指向自建 SearXNG。
"""

from __future__ import annotations

import html
import ipaddress
import os
import re
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.config import settings

_TAG_RE = re.compile(r"<[^>]+>")
_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}
_DOMAIN_AUTHORITY = {
    "arxiv.org": 6,
    "nature.com": 6,
    "science.org": 6,
    "ieee.org": 5,
    "acm.org": 5,
    "springer.com": 5,
    "sciencedirect.com": 5,
    "apa.org": 5,
    "nih.gov": 5,
    "github.com": 4,
    "wikipedia.org": 3,
}


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


def normalize_url(url: str) -> tuple[str, str]:
    """返回用于去重的规范地址和保留展示用的干净地址。"""
    raw = (url or "").strip()
    try:
        parsed = urlsplit(raw)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return raw, raw
        host = parsed.netloc.lower().removesuffix(".")
        if host.startswith("www."):
            host = host[4:]
        query_pairs = [
            (key, value)
            for key, value in (
                part.split("=", 1) if "=" in part else (part, "")
                for part in parsed.query.split("&")
            )
            if key.lower() not in _TRACKING_PARAMS
        ]
        clean_query = "&".join(f"{k}={v}" for k, v in query_pairs)
        path = parsed.path.rstrip("/")
        canonical = urlunsplit((parsed.scheme.lower(), host, path, clean_query, ""))
        display = urlunsplit((parsed.scheme, host, parsed.path, clean_query, ""))
        return canonical, display or raw
    except ValueError:
        return raw, raw


def result_identity(item: dict[str, Any]) -> str:
    canonical, _ = normalize_url(str(item.get("url") or ""))
    if canonical.startswith(("http://", "https://")):
        return canonical
    title = re.sub(r"\W+", "", str(item.get("title") or "").lower())
    return f"title:{title}"


def _content_terms(text: str) -> set[str]:
    """ASCII 词元 + 中文相邻二元组，避免中文按单字匹配产生噪声。"""
    value = (text or "").lower()
    words = set(re.findall(r"[a-z][a-z0-9_-]{1,}", value))
    chinese_runs = re.findall(r"[\u4e00-\u9fff]{2,}", value)
    bigrams = {run[i:i + 2] for run in chinese_runs for i in range(len(run) - 1)}
    return words | bigrams


def rank_results(items: list[dict[str, Any]], query: str, limit: int) -> list[dict[str, Any]]:
    """多源合并、去重和轻量重排；不依赖任何私有排序服务。"""
    query_terms = _content_terms(query)
    grouped: dict[str, dict[str, Any]] = {}
    for raw in items:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        url = str(raw.get("url") or "").strip()
        if not title or not url.startswith(("http://", "https://")):
            continue
        identity = result_identity({"title": title, "url": url})
        row = {
            "title": title,
            "url": url,
            "snippet": _clean_text(raw.get("snippet") or "")[:500],
            "date": str(raw.get("date") or "").strip(),
            "source": str(raw.get("source") or "web"),
            "academic": bool(raw.get("academic")),
            "providers": [str(raw.get("source") or "web")],
        }
        old = grouped.get(identity)
        if old:
            old["providers"] = sorted(set(old.get("providers") or []) | set(row["providers"]))
            old["source"] = old["providers"][0]
            old["academic"] = bool(old.get("academic") or row["academic"])
            if len(row["snippet"]) > len(old["snippet"]):
                old["snippet"] = row["snippet"]
            if not old.get("date") and row["date"]:
                old["date"] = row["date"]
        else:
            grouped[identity] = row

    ranked: list[dict[str, Any]] = []
    year = datetime.now(timezone.utc).year
    for item in grouped.values():
        text_terms = _content_terms(f'{item["title"]} {item["snippet"]}')
        overlap = len(query_terms & text_terms)
        host = (urlsplit(item["url"]).hostname or "").lower()
        authority = next(
            (score for domain, score in _DOMAIN_AUTHORITY.items() if host == domain or host.endswith("." + domain)),
            0,
        )
        freshness = 1.0 if str(year) in item["title"] + item["snippet"] else 0.0
        score = min(8.0, overlap * 1.15)
        score += authority
        score += len(set(item.get("providers") or [])) * 1.5
        score += 1.0 if item.pop("academic", False) else 0.0
        score += freshness
        item["score"] = round(score, 3)
        ranked.append(item)
    ranked.sort(key=lambda row: (-row["score"], row["title"].lower()))
    return ranked[: max(1, min(int(limit or 5), 20))]


def _is_public_http_url(url: str) -> bool:
    try:
        parsed = urlsplit((url or "").strip())
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("http", "https") or not host or host == "localhost" or host.endswith(".local"):
            return False
        try:
            addr = ipaddress.ip_address(host)
            return addr.is_global
        except ValueError:
            pass
        infos = socket.getaddrinfo(host, None)
        return all(ipaddress.ip_address(info[4][0]).is_global for info in infos)
    except (ValueError, OSError):
        return False


def extract_html_text(html_text: str, max_chars: int = 2400) -> str:
    soup = BeautifulSoup(html_text or "", "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside", "form"]):
        tag.decompose()
    node = soup.find("main") or soup.find("article")
    if not node or len(node.get_text(" ", strip=True)) < 300:
        node = soup.body or soup
    return _clean_text(node.get_text(" ", strip=True))[:max_chars]


def fetch_page_evidence(url: str, timeout: float = 12.0) -> dict[str, Any]:
    """读取公开网页正文作为 Agent 引用证据；拒绝内网地址。"""
    if not _is_public_http_url(url):
        raise RuntimeError("仅支持公开 HTTP(S) 页面")
    headers = {
        "User-Agent": f"ResearchMate/{settings.APP_VERSION}",
        "Accept": "text/html,application/xhtml+xml;q=0.8,*/*;q=0.5",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        current_url = url
        for _ in range(3):
            if not _is_public_http_url(current_url):
                raise RuntimeError("重定向目标不是公网地址")
            resp = client.get(current_url, headers=headers)
            if resp.is_redirect:
                location = resp.headers.get("location", "")
                current_url = str(httpx.URL(resp.url).join(location))
                continue
            resp.raise_for_status()
            break
        content_type = resp.headers.get("content-type", "").lower()
        if resp.text and ("html" in content_type or "xml" in content_type or not content_type):
            text = extract_html_text(resp.text)
        else:
            text = ""
    if len(text) < 80:
        raise RuntimeError("未能提取到有效正文")
    return {"url": url, "text": text}


def arxiv_search(query: str, limit: int = 5, timeout: float = 8.0) -> dict[str, Any]:
    """arXiv 官方 API，适合预印本和理工科论文检索。"""
    params = {
        "search_query": f'all:"{query}"',
        "start": 0,
        "max_results": max(1, min(int(limit or 5), 10)),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get("https://export.arxiv.org/api/query", params=params)
        resp.raise_for_status()
    from xml.etree import ElementTree as ET

    ns = "{http://www.w3.org/2005/Atom}"
    root = ET.fromstring(resp.content)
    items: list[dict[str, Any]] = []
    for entry in root.findall(f"{ns}entry"):
        title = _clean_text(entry.findtext(f"{ns}title") or "")
        url = (entry.findtext(f"{ns}id") or "").strip()
        if title and url.startswith(("http://", "https://")):
            items.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": _clean_text(entry.findtext(f"{ns}summary") or "")[:500],
                    "date": (entry.findtext(f"{ns}published") or "")[:10],
                    "source": "arxiv",
                    "academic": True,
                }
            )
    return {"count": len(items), "query": query, "engine": "arxiv", "items": items}


def crossref_search(query: str, limit: int = 5, timeout: float = 8.0) -> dict[str, Any]:
    """Crossref 官方元数据检索，覆盖期刊论文 DOI。"""
    params = {
        "query.bibliographic": query,
        "rows": max(1, min(int(limit or 5), 10)),
        "select": "title,URL,abstract,issued",
        "mailto": "researchmate@local.app",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get("https://api.crossref.org/works", params=params)
        resp.raise_for_status()
    rows = (resp.json().get("message") or {}).get("items") or []
    items: list[dict[str, Any]] = []
    for row in rows:
        title = _clean_text(" ".join(row.get("title") or []))
        url = str(row.get("URL") or "").strip()
        if title and url.startswith(("http://", "https://")):
            date_parts = ((row.get("issued") or {}).get("date-parts") or [[None]])[0]
            items.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": _clean_text(row.get("abstract") or "")[:500],
                    "date": str(date_parts[0] or ""),
                    "source": "crossref",
                    "academic": True,
                }
            )
    return {"count": len(items), "query": query, "engine": "crossref", "items": items}


def openalex_search(query: str, limit: int = 5, timeout: float = 8.0) -> dict[str, Any]:
    """OpenAlex 免费学术图谱，补充 Crossref 摘要覆盖率。"""
    params = {
        "search": query,
        "per-page": max(1, min(int(limit or 5), 10)),
        "mailto": "researchmate@local.app",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get("https://api.openalex.org/works", params=params)
        resp.raise_for_status()
    rows = resp.json().get("results") or []
    items: list[dict[str, Any]] = []
    for row in rows:
        title = _clean_text(row.get("display_name") or "")
        landing = row.get("primary_location") or {}
        url = str(landing.get("landing_page_url") or row.get("doi") or row.get("id") or "")
        if not url.startswith("http"):
            continue
        if title:
            abstract_index = row.get("abstract_inverted_index") or {}
            positions: dict[int, str] = {}
            for word, offsets in abstract_index.items():
                for offset in offsets:
                    positions[offset] = word
            snippet = " ".join(positions[i] for i in sorted(positions))
            items.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": _clean_text(snippet)[:500],
                    "date": str(row.get("publication_year") or ""),
                    "source": "openalex",
                    "academic": True,
                }
            )
    return {"count": len(items), "query": query, "engine": "openalex", "items": items}


def deep_web_search(
    query: str,
    limit: int = 8,
    config: dict[str, Any] | None = None,
    read_pages: int = 3,
) -> dict[str, Any]:
    """并行多源搜索：配置源、公共搜索、开放学术源，再合并去重与正文取证。

    设计目标是在本地应用中实现同类 Agent 的通用能力：多来源并行、证据聚合、
    可引用 URL 和单源失败隔离；不依赖任何私有搜索服务。
    """
    errors: list[str] = []

    def bing_rss() -> dict[str, Any]:
        from app.agent.tools import _fetch_bing_rss

        return {"items": _fetch_bing_rss(query, min(limit, 10), timeout=6.0)}

    def bing_html() -> dict[str, Any]:
        from app.agent.tools import _fetch_bing_html

        return {"items": _fetch_bing_html(query, min(limit, 10), timeout=6.0)}

    def duckduckgo() -> dict[str, Any]:
        from app.agent.tools import _fetch_duckduckgo_html

        return {"items": _fetch_duckduckgo_html(query, min(limit, 10), timeout=6.0)}

    providers: dict[str, Any] = {
        "bing_rss": bing_rss,
        "bing_html": bing_html,
        "duckduckgo": duckduckgo,
        "arxiv": lambda: arxiv_search(query, limit, timeout=6.0),
        "crossref": lambda: crossref_search(query, limit, timeout=6.0),
        "openalex": lambda: openalex_search(query, limit, timeout=6.0),
    }
    if searxng_configured(config):
        providers["searxng"] = lambda: searxng_search(query, min(limit, 10), timeout=7, config=config)
    if anysearch_enabled(config):
        providers["anysearch"] = lambda: anysearch_search(query, min(limit, 10), timeout=7, config=config)

    all_items: list[dict[str, Any]] = []
    succeeded: set[str] = set()
    executor = ThreadPoolExecutor(max_workers=min(8, len(providers)), thread_name_prefix="rm-search")
    futures = {executor.submit(fn): name for name, fn in providers.items()}
    try:
        for future in as_completed(futures, timeout=7):
            name = futures[future]
            try:
                rows = future.result().get("items") or []
                all_items.extend(rows)
                if rows:
                    succeeded.add(name)
                else:
                    errors.append(f"{name}: 无结果")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {exc}")
    except TimeoutError:
        errors.append("部分搜索提供方超时")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    ranked = rank_results(all_items, query, limit=max(int(limit or 8), 10))
    evidence: list[dict[str, Any]] = []
    page_executor = ThreadPoolExecutor(max_workers=min(read_pages or 1, 2), thread_name_prefix="rm-reader")
    page_futures = {page_executor.submit(fetch_page_evidence, row["url"], 5): row for row in ranked[:read_pages]}
    try:
        for future in as_completed(page_futures, timeout=6):
            row = page_futures[future]
            try:
                data = future.result()
                evidence.append({"title": row["title"], **data})
                row["snippet"] = row["snippet"] or data["text"][:240]
                row["readable"] = True
            except Exception as exc:  # noqa: BLE001
                row["readable"] = False
                row["read_error"] = str(exc)
    except TimeoutError:
        errors.append("网页正文读取超时")
    finally:
        page_executor.shutdown(wait=False, cancel_futures=True)
    evidence = evidence[:read_pages]

    shown = ranked[: max(1, min(int(limit or 8), 10))]
    return {
        "count": len(shown),
        "query": query,
        "engine": "researchmate-deep-search",
        "providers": sorted(succeeded),
        "items": shown,
        "evidence": evidence,
        "errors": errors[:12],
    }


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
