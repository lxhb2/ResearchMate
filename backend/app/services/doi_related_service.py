"""Find papers related to a DOI through free academic metadata APIs."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx

from app.services.bibliometric_service import normalize_doi

_MAILTO = "researchmate@local.app"
_TIMEOUT = 6.0
_MAX_ITEMS = 72
def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _extract_doi(value: str) -> str:
    """Accept raw DOI, doi.org URL, or text containing one DOI."""
    text = str(value or "").strip()
    match = re.search(r"\b10\.\d{4,9}/\S+", text, re.I)
    return normalize_doi(match.group(0) if match else text)


def _norm_item(item: dict[str, Any], relation: str, source: str) -> dict[str, Any]:
    doi = normalize_doi(item.get("doi"))
    title = _clean_text(item.get("title"))
    return {
        "id": f"doi:{doi}" if doi else f"title:{title.lower()}",
        "title": title,
        "authors": [_clean_text(author) for author in (item.get("authors") or []) if _clean_text(author)],
        "year": item.get("year") or None,
        "doi": doi,
        "abstract": _clean_text(item.get("abstract")),
        "journal": _clean_text(item.get("journal")),
        "citation_count": int(item.get("citation_count") or 0),
        "url": _clean_text(item.get("url")) or (f"https://doi.org/{doi}" if doi else ""),
        "relation": relation,
        "source": source,
    }


def _openalex_abstract(inverted: dict[str, list[int]] | None) -> str:
    positions = [(index, word) for word, indexes in (inverted or {}).items() for index in indexes]
    return " ".join(word for _, word in sorted(positions))


def _openalex_item(row: dict[str, Any], relation: str) -> dict[str, Any]:
    primary = row.get("primary_location") or {}
    source = (primary.get("source") or {}) if isinstance(primary.get("source"), dict) else {}
    return _norm_item(
        {
            "title": _clean_text(row.get("title") or row.get("display_name")),
            "authors": [
                (authorship.get("author") or {}).get("display_name")
                for authorship in (row.get("authorships") or [])
            ],
            "year": row.get("publication_year"),
            "doi": normalize_doi(row.get("doi")),
            "abstract": _openalex_abstract(row.get("abstract_inverted_index")),
            "journal": source.get("display_name"),
            "citation_count": row.get("cited_by_count"),
            "url": primary.get("landing_page_url") or row.get("doi") or row.get("id"),
        },
        relation,
        "openalex",
    )


def _openalex_params(**params: Any) -> dict[str, Any]:
    return {"mailto": _MAILTO, **params}


def _fetch_openalex(doi: str, limit: int, timeout: float) -> dict[str, Any]:
    fields = "id,title,display_name,publication_year,authorships,doi,abstract_inverted_index,primary_location,cited_by_count,referenced_works,related_works"
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        anchor_resp = client.get(
            f"https://api.openalex.org/works/doi:{doi}",
            params=_openalex_params(select=fields),
        )
        anchor_resp.raise_for_status()
        anchor_row = anchor_resp.json()
        anchor_id = str(anchor_row.get("id") or "").rsplit("/", 1)[-1]
        rows_by_relation: dict[str, list[dict[str, Any]]] = {
            "reference": [],
            "citation": [],
            "similar": [],
        }

        def fetch_batch(ids: list[str]) -> list[dict[str, Any]]:
            if not ids:
                return []
            response = client.get(
                "https://api.openalex.org/works",
                params=_openalex_params(
                    filter=f"openalex_id:{'|'.join(ids)}",
                    select=fields,
                    **{"per-page": len(ids)},
                ),
            )
            response.raise_for_status()
            return list(response.json().get("results") or [])

        if anchor_id:
            ids_by_relation = {
                "reference": [str(value).rsplit("/", 1)[-1] for value in (anchor_row.get("referenced_works") or [])],
                "similar": [str(value).rsplit("/", 1)[-1] for value in (anchor_row.get("related_works") or [])],
            }
            for relation, ids in ids_by_relation.items():
                batches = [ids[index : index + 25] for index in range(0, min(len(ids), limit), 25)]
                for batch in batches:
                    rows_by_relation[relation].extend(fetch_batch(batch))

            response = client.get(
                "https://api.openalex.org/works",
                params=_openalex_params(
                    filter=f"cites:{anchor_id}",
                    select=fields,
                    **{"per-page": limit},
                    sort="cited_by_count:desc",
                ),
            )
            response.raise_for_status()
            rows_by_relation["citation"].extend(response.json().get("results") or [])

    anchor = _openalex_item(anchor_row, "anchor")
    related = [
        _openalex_item(row, relation)
        for relation, rows in rows_by_relation.items()
        for row in rows
    ]
    return {
        "anchor": anchor,
        "related": related,
        "count": len(related),
        "ok": True,
    }


def _semantic_authors(value: Any) -> list[str]:
    if isinstance(value, list):
        return [
            _clean_text(author.get("name") if isinstance(author, dict) else author)
            for author in value
        ]
    return []


def _semantic_item(row: dict[str, Any]) -> dict[str, Any]:
    external = row.get("externalIds") or {}
    doi = normalize_doi(external.get("DOI"))
    return _norm_item(
        {
            "title": _clean_text(row.get("title")),
            "authors": _semantic_authors(row.get("authors")),
            "year": row.get("year"),
            "doi": doi,
            "abstract": _clean_text(row.get("abstract")),
            "journal": _clean_text(row.get("venue")),
            "citation_count": row.get("citationCount"),
            "url": _clean_text(row.get("url")) or (f"https://doi.org/{doi}" if doi else ""),
        },
        "similar",
        "semantic_scholar",
    )


def _fetch_semantic_recommendations(doi: str, limit: int, timeout: float) -> list[dict[str, Any]]:
    fields = "title,authors,year,abstract,externalIds,venue,url,citationCount"
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(
            f"https://api.semanticscholar.org/recommendations/v1/papers/forpaper/DOI:{doi}",
            params={"fields": fields, "limit": min(20, limit)},
        )
        response.raise_for_status()
    return [_semantic_item(row) for row in (response.json().get("recommendedPapers") or [])]


def _merge_items(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in items:
        if not item.get("title"):
            continue
        item_id = str(item["id"])
        existing = merged.get(item_id)
        if existing:
            relations = list(dict.fromkeys([*existing.get("relations", []), item["relation"]]))
            sources = list(dict.fromkeys([*existing.get("sources", []), item["source"]]))
            existing.update(
                {
                    key: item[key]
                    for key in ("title", "authors", "year", "doi", "abstract", "journal", "citation_count", "url")
                    if item.get(key)
                }
            )
            existing["relations"] = relations
            existing["sources"] = sources
        else:
            item = dict(item)
            item["relations"] = [item.pop("relation")]
            item["sources"] = [item.pop("source")]
            merged[item_id] = item
    rank = {"similar": 0, "citation": 1, "reference": 2}
    return sorted(
        merged.values(),
        key=lambda item: (min(rank.get(relation, 3) for relation in item["relations"]), -int(item.get("citation_count") or 0), item["title"].lower()),
    )[:limit]


def find_related_papers(
    query: str,
    limit: int = 24,
    timeout: float = _TIMEOUT,
) -> dict[str, Any]:
    doi = _extract_doi(query)
    if not doi:
        raise ValueError("请输入有效的 DOI，例如 10.1038/s41586-020-2649-2")
    limit = max(5, min(int(limit or 24), _MAX_ITEMS))
    timeout = max(1.0, min(float(timeout or _TIMEOUT), 15.0))
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=2) as executor:
        openalex_future = executor.submit(_fetch_openalex, doi, limit, timeout)
        semantic_future = executor.submit(_fetch_semantic_recommendations, doi, limit, timeout)
        try:
            openalex = openalex_future.result()
        except Exception as exc:  # noqa: BLE001 - OpenAlex failure degrades to Semantic Scholar.
            openalex = {"anchor": None, "related": [], "count": 0, "ok": False}
            errors.append(f"openalex: {exc}")
        try:
            semantic = semantic_future.result()
        except Exception as exc:  # noqa: BLE001
            semantic = []
            errors.append(f"semantic_scholar: {exc}")
    related = [*openalex["related"], *semantic]
    anchor = openalex.get("anchor") or None
    if not anchor and not related:
        raise ValueError("未能通过 DOI 找到论文，请确认 DOI 是否正确")
    return {
        "ok": True,
        "doi": doi,
        "anchor": anchor,
        "papers": _merge_items(related, limit),
        "errors": errors,
        "sources": {
            "openalex": {"ok": bool(openalex["ok"]), "count": openalex["count"]},
            "semantic_scholar": {"ok": bool(semantic), "count": len(semantic)},
        },
    }
