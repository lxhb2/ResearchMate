"""在线文献元数据补全：Crossref / arXiv / OpenAlex / Semantic Scholar。"""
import re
import xml.etree.ElementTree as ET
from typing import Optional

import httpx

SOURCES = ["crossref", "openalex", "semantic_scholar", "arxiv"]
TIMEOUT = 10.0


def _norm(item: dict) -> dict:
    """统一候选结构，缺字段给空值。"""
    return {
        "title": (item.get("title") or "").strip(),
        "authors": list(item.get("authors") or []),
        "year": item.get("year"),
        "doi": (item.get("doi") or "").strip(),
        "abstract": (item.get("abstract") or "").strip(),
        "journal": (item.get("journal") or "").strip(),
        "url": (item.get("url") or "").strip(),
        "source": item.get("source") or "",
    }


def _authors_from_names(names: list[str]) -> list[str]:
    return [n for n in (names or []) if n]


# ---------------------------------------------------------------------------
# Crossref
# ---------------------------------------------------------------------------

def _looks_like_doi(q: str) -> bool:
    return bool(re.match(r"^10\.\d{4,9}/\S+$", (q or "").strip(), re.I))


def _fetch_crossref(query: str) -> list[dict]:
    base = "https://api.crossref.org/works"
    params = (
        {"rows": 3}
        if _looks_like_doi(query)
        else {"query.bibliographic": query, "rows": 3}
    )
    url = f"{base}/{query.strip()}" if _looks_like_doi(query) else base
    resp = httpx.get(url, params=params, timeout=TIMEOUT, headers={"User-Agent": "ResearchMate/0.2"})
    resp.raise_for_status()
    data = resp.json()
    items = data.get("message", []) if isinstance(data.get("message"), list) else [data.get("message", {})]
    out = []
    for m in items:
        if not isinstance(m, dict):
            continue
        authors = []
        for a in m.get("author") or []:
            given = (a.get("given") or "").strip()
            family = (a.get("family") or "").strip()
            name = f"{given} {family}".strip() if given and family else (family or given)
            if name:
                authors.append(name)
        year = None
        for part in (m.get("issued") or {}).get("date-parts") or []:
            if part and part[0]:
                year = int(part[0])
                break
        out.append(
            _norm(
                {
                    "title": (m.get("title") or [""])[0] if isinstance(m.get("title"), list) else (m.get("title") or ""),
                    "authors": authors,
                    "year": year,
                    "doi": (m.get("DOI") or "").strip(),
                    "abstract": re.sub(r"<[^>]+>", "", m.get("abstract") or "").strip(),
                    "journal": (m.get("container-title") or [""])[0] if isinstance(m.get("container-title"), list) else (m.get("container-title") or ""),
                    "url": (m.get("URL") or "").strip(),
                    "source": "crossref",
                }
            )
        )
    return out


# ---------------------------------------------------------------------------
# arXiv
# ---------------------------------------------------------------------------

def _fetch_arxiv(query: str) -> list[dict]:
    params = {"start": 0, "max_results": 3}
    arxiv_id = re.search(r"(\d{4}\.\d{4,5})(?:v\d+)?", query)
    if arxiv_id:
        params["id_list"] = arxiv_id.group(1)
    else:
        params["search_query"] = f"all:{query.strip()}"
    resp = httpx.get("https://export.arxiv.org/api/query", params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(resp.text)
    out = []
    for entry in root.findall("atom:entry", ns):
        title = " ".join((entry.findtext("atom:title", "", ns) or "").split())
        authors = [a.findtext("atom:name", "", ns).strip() for a in entry.findall("atom:author", ns) if a.findtext("atom:name", "", ns)]
        published = entry.findtext("atom:published", "", ns) or ""
        year = None
        ym = re.search(r"(\d{4})", published)
        if ym:
            year = int(ym.group(1))
        doi = ""
        for link in entry.findall("atom:link", ns):
            if link.get("title") == "doi":
                doi = (link.get("href") or "").replace("https://doi.org/", "")
                break
        out.append(
            _norm(
                {
                    "title": title,
                    "authors": authors,
                    "year": year,
                    "doi": doi,
                    "abstract": " ".join((entry.findtext("atom:summary", "", ns) or "").split()),
                    "journal": "arXiv",
                    "url": (entry.findtext("atom:id", "", ns) or "").strip(),
                    "source": "arxiv",
                }
            )
        )
    return out


# ---------------------------------------------------------------------------
# OpenAlex
# ---------------------------------------------------------------------------

def _fetch_openalex(query: str) -> list[dict]:
    resp = httpx.get(
        "https://api.openalex.org/works",
        params={"search": query, "per-page": 3, "mailto": "researchmate@example.com"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    out = []
    for w in (data.get("results") or [])[:3]:
        year = w.get("publication_year")
        out.append(
            _norm(
                {
                    "title": (w.get("title") or "").strip(),
                    "authors": [
                        (a.get("author") or {}).get("display_name", "")
                        for a in (w.get("authorships") or [])
                        if (a.get("author") or {}).get("display_name")
                    ],
                    "year": int(year) if year else None,
                    "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
                    "abstract": (w.get("abstract_inverted_index") and _openalex_abstract(w["abstract_inverted_index"])) or "",
                    "journal": ((w.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
                    "url": (w.get("id") or "").strip(),
                    "source": "openalex",
                }
            )
        )
    return out


def _openalex_abstract(inverted: dict) -> str:
    positions = []
    for word, indexes in (inverted or {}).items():
        for idx in indexes:
            positions.append((idx, word))
    positions.sort()
    return " ".join(w for _i, w in positions)


# ---------------------------------------------------------------------------
# Semantic Scholar
# ---------------------------------------------------------------------------

def _fetch_semantic_scholar(query: str) -> list[dict]:
    resp = httpx.get(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params={"query": query, "limit": 3, "fields": "title,authors,year,abstract,externalIds,venue,url"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    out = []
    for p in (data.get("data") or [])[:3]:
        ext = p.get("externalIds") or {}
        out.append(
            _norm(
                {
                    "title": (p.get("title") or "").strip(),
                    "authors": [a.get("name", "") for a in (p.get("authors") or []) if a.get("name")],
                    "year": p.get("year"),
                    "doi": (ext.get("DOI") or "").strip(),
                    "abstract": (p.get("abstract") or "").strip(),
                    "journal": (p.get("venue") or "").strip(),
                    "url": (p.get("url") or "").strip(),
                    "source": "semantic_scholar",
                }
            )
        )
    return out


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

_FETCHERS = {
    "crossref": _fetch_crossref,
    "arxiv": _fetch_arxiv,
    "openalex": _fetch_openalex,
    "semantic_scholar": _fetch_semantic_scholar,
}


def lookup(query: str, sources: Optional[list[str]] = None, limit: int = 6) -> dict:
    """按多个来源查询元数据，返回候选列表与各来源错误。"""
    query = (query or "").strip()
    if not query:
        return {"query": "", "items": [], "errors": ["查询内容为空"]}
    selected = [s for s in (sources or SOURCES) if s in _FETCHERS] or SOURCES
    items: list[dict] = []
    errors: list[str] = []
    for source in selected:
        try:
            items.extend(_FETCHERS[source](query))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{source}: {e}")
    # 去重（按 DOI 优先，其次标题）
    seen: set[str] = set()
    dedup: list[dict] = []
    for it in items:
        key = (it.get("doi") or "").lower() or (it.get("title") or "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        dedup.append(it)
    return {
        "query": query,
        "items": dedup[:limit],
        "errors": errors,
    }
