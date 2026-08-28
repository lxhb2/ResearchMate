"""VOSviewer-style bibliometric graphs built from the local library or open APIs."""
from __future__ import annotations

import io
import math
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.models.paper import Paper
from app.services.graph_service import CLUSTER_COLORS, _tokens

NETWORK_TYPES = {
    "co_authorship": "合著网络",
    "co_occurrence": "关键词共现网络",
    "citation": "引文网络",
    "bibliographic_coupling": "文献耦合网络",
    "paper_similarity": "论文关联网络",
}
EXTERNAL_SOURCES = ["openalex", "crossref", "europe_pmc"]
DEFAULT_LIMIT = 50
MAX_LIMIT = 100
MAX_EDGES = 1200
_DOI_RE = re.compile(r"10\.\d{4,9}/\S+", re.I)
_MAILTO = "researchmate@local.app"
_MIN_RESOLUTION = 0.25
_MAX_RESOLUTION = 2.0


def normalize_doi(value: Any) -> str:
    raw = str(value or "").strip().lower()
    raw = re.sub(r"^https?://(dx\.)?doi\.org/", "", raw)
    raw = re.sub(r"^doi:\s*", "", raw)
    return raw.strip().rstrip(".,;")


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _keywords_from_record(record: dict[str, Any], max_keywords: int = 10) -> list[str]:
    explicit = [
        _clean_text(value)
        for value in (record.get("keywords") or [])
        if len(_clean_text(value)) >= 2
    ]
    if explicit:
        unique: list[str] = []
        seen: set[str] = set()
        for word in explicit:
            key = word.lower()
            if key not in seen:
                unique.append(word)
                seen.add(key)
        return unique[:max_keywords]

    text = f'{record.get("title") or ""} {record.get("abstract") or ""}'
    counts: dict[str, int] = {}
    for token in _tokens(text):
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts, key=lambda token: (-counts[token], -len(token), token))
    picked: list[str] = []
    for word in ranked:
        if any(word in old or old in word for old in picked):
            continue
        picked.append(word.title() if word.isascii() else word)
        if len(picked) >= max_keywords:
            break
    return picked


def _paper_record(paper: Paper) -> dict[str, Any]:
    return {
        "id": str(paper.id),
        "title": _clean_text(paper.title) or "未命名",
        "authors": [value for value in (paper.authors or []) if _clean_text(value)],
        "year": paper.year,
        "doi": normalize_doi(paper.doi),
        "abstract": _clean_text(paper.abstract),
        "keywords": [value for value in (paper.tags or []) if _clean_text(value)],
        "cited_by_count": 0,
        "references": [],
        "source": "library",
        "url": f"/reader/{paper.id}",
        "paper_id": str(paper.id),
    }


def _openalex_abstract(inverted: dict[str, list[int]] | None) -> str:
    positions: list[tuple[int, str]] = []
    for word, indexes in (inverted or {}).items():
        for index in indexes:
            positions.append((index, word))
    return " ".join(word for _, word in sorted(positions))


def _openalex_record(row: dict[str, Any]) -> dict[str, Any]:
    authors = [
        _clean_text(((authorship.get("author") or {}).get("display_name")))
        for authorship in (row.get("authorships") or [])
    ]
    keywords = [
        _clean_text(item.get("display_name"))
        for item in (row.get("keywords") or row.get("concepts") or [])
        if item.get("display_name")
    ]
    work_id = str(row.get("id") or "").rsplit("/", 1)[-1]
    doi = normalize_doi(row.get("doi"))
    primary = row.get("primary_location") or {}
    record_id = work_id or (f"doi:{doi}" if doi else str(row.get("id") or ""))
    return {
        "id": record_id,
        "title": _clean_text(row.get("title") or row.get("display_name")) or "未命名",
        "authors": [name for name in authors if name],
        "year": row.get("publication_year"),
        "doi": doi,
        "abstract": _clean_text(_openalex_abstract(row.get("abstract_inverted_index"))),
        "keywords": keywords,
        "cited_by_count": int(row.get("cited_by_count") or 0),
        "references": [
            str(value).rsplit("/", 1)[-1]
            for value in (row.get("referenced_works") or [])
        ],
        "source": "openalex",
        "url": _clean_text(primary.get("landing_page_url") or row.get("doi") or row.get("id")),
        "paper_id": work_id or doi,
    }


def openalex_records(query: str, limit: int = DEFAULT_LIMIT, timeout: float = 5.0) -> list[dict[str, Any]]:
    params = {
        "search": query,
        "per-page": max(1, min(int(limit or DEFAULT_LIMIT), 50)),
        "mailto": _MAILTO,
    }
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get("https://api.openalex.org/works", params=params)
        response.raise_for_status()
    return [_openalex_record(row) for row in (response.json().get("results") or [])]


def crossref_records(query: str, limit: int = DEFAULT_LIMIT, timeout: float = 5.0) -> list[dict[str, Any]]:
    params = {
        "query.bibliographic": query,
        "rows": max(1, min(int(limit or DEFAULT_LIMIT), 50)),
        "select": "title,author,issued,DOI,abstract,is-referenced-by-count,reference,URL,container-title,subject",
        "mailto": _MAILTO,
    }
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get("https://api.crossref.org/works", params=params)
        response.raise_for_status()
    rows = ((response.json().get("message") or {}).get("items") or [])
    records: list[dict[str, Any]] = []
    for row in rows:
        authors: list[str] = []
        for person in row.get("author") or []:
            given = _clean_text(person.get("given"))
            family = _clean_text(person.get("family"))
            authors.append(f"{given} {family}".strip() or family or given)
        date_parts = ((row.get("issued") or {}).get("date-parts") or [[None]])[0]
        doi = normalize_doi(row.get("DOI"))
        records.append(
            {
                "id": f"doi:{doi}",
                "title": _clean_text(" ".join(row.get("title") or [])) or "未命名",
                "authors": [name for name in authors if name],
                "year": date_parts[0] if date_parts and date_parts[0] else None,
                "doi": doi,
                "abstract": re.sub(r"<[^>]+>", " ", _clean_text(row.get("abstract"))),
                "keywords": [_clean_text(value) for value in (row.get("subject") or [])],
                "cited_by_count": int(row.get("is-referenced-by-count") or 0),
                "references": [
                    normalized
                    for item in (row.get("reference") or [])
                    if (normalized := normalize_doi(item.get("DOI")))
                ],
                "source": "crossref",
                "url": _clean_text(row.get("URL") or doi),
                "paper_id": doi,
            }
        )
    return records


def europepmc_records(query: str, limit: int = DEFAULT_LIMIT, timeout: float = 5.0) -> list[dict[str, Any]]:
    params = {
        "query": query,
        "format": "json",
        "pageSize": max(1, min(int(limit or DEFAULT_LIMIT), 50)),
        "resultType": "core",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search", params=params)
        response.raise_for_status()
    rows = ((response.json().get("resultList") or {}).get("result") or [])
    records: list[dict[str, Any]] = []
    for row in rows:
        authors = [
            _clean_text(item.get("fullName") or item.get("collectiveName") or item.get("lastName"))
            for item in ((row.get("authorList") or {}).get("author") or [])
        ]
        keywords = [_clean_text(value) for value in ((row.get("keywordList") or {}).get("keyword") or [])]
        pmid = _clean_text(row.get("pmid") or row.get("id"))
        doi = normalize_doi(row.get("doi"))
        record_id = f"pmid:{pmid}" if pmid else (f"doi:{doi}" if doi else _clean_text(row.get("id")))
        records.append(
            {
                "id": record_id,
                "title": _clean_text(row.get("title")) or "未命名",
                "authors": [name for name in authors if name],
                "year": int(row.get("pubYear") or 0) or None,
                "doi": doi,
                "abstract": _clean_text(row.get("abstractText")),
                "keywords": keywords,
                "cited_by_count": int(row.get("citedByCount") or 0),
                "references": [],
                "source": "europe_pmc",
                "url": f"https://doi.org/{doi}" if doi else f"https://europepmc.org/article/MED/{pmid}",
                "paper_id": pmid or doi,
            }
        )
    return records


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for record in records:
        doi = normalize_doi(record.get("doi"))
        title_key = re.sub(r"\W+", "", (record.get("title") or "").lower())
        key = f"doi:{doi}" if doi else f"title:{title_key}"
        if key in seen:
            continue
        seen.add(key)
        output.append(record)
    return output


def _enrich_library_with_openalex(records: list[dict[str, Any]], timeout: float = 5.0) -> dict[str, dict[str, Any]]:
    dois = [record["doi"] for record in records if record.get("doi")]
    if not dois:
        return {}
    batches = [dois[index : index + 25] for index in range(0, len(dois), 25)]

    def fetch(batch: list[str]) -> dict[str, dict[str, Any]]:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(
                "https://api.openalex.org/works",
                params={"filter": "doi:" + "|".join(batch), "per-page": len(batch), "mailto": _MAILTO},
            )
            response.raise_for_status()
        output: dict[str, dict[str, Any]] = {}
        for row in response.json().get("results") or []:
            doi = normalize_doi(row.get("doi"))
            if doi:
                output[doi] = {
                    "cited_by_count": int(row.get("cited_by_count") or 0),
                    "references": [
                        str(value).rsplit("/", 1)[-1]
                        for value in (row.get("referenced_works") or [])
                    ],
                    "openalex_id": str(row.get("id") or "").rsplit("/", 1)[-1],
                }
        return output

    enriched: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(3, len(batches))) as executor:
        futures = {executor.submit(fetch, batch): batch for batch in batches}
        for future in as_completed(futures):
            try:
                enriched.update(future.result())
            except Exception:  # noqa: BLE001 - single failed batch degrades to no reference edges
                continue
    return enriched


def _add_pair(weights: dict[tuple[str, str], int], left: str, right: str) -> None:
    key = (left, right) if left < right else (right, left)
    weights[key] = weights.get(key, 0) + 1


def _paper_vector(record: dict[str, Any]) -> dict[str, float]:
    title = " ".join([_clean_text(record.get("title"))] * 3)
    keywords = " ".join(_clean_text(value) for value in (record.get("keywords") or []))
    abstract = _clean_text(record.get("abstract"))
    counts = Counter(_tokens(f"{title} {keywords} {keywords} {abstract}"))
    return {token: float(count) for token, count in counts.items() if len(token) >= 2}


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    if len(right) < len(left):
        left, right = right, left
    dot = sum(value * right.get(token, 0.0) for token, value in left.items())
    if dot <= 0.0:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return dot / (left_norm * right_norm)


def _cooccurrence_network(
    records: list[dict[str, Any]], field: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    node_counts: dict[str, int] = {}
    edge_weights: dict[tuple[str, str], int] = {}
    node_papers: dict[str, set[str]] = {}

    for record in records:
        if field == "keywords":
            values = _keywords_from_record(record)
        else:
            values = [_clean_text(value) for value in (record.get(field) or []) if _clean_text(value)]
        values = list(dict.fromkeys(values))[:30]
        paper_id = str(record.get("paper_id") or record.get("id") or record.get("title"))
        for value in values:
            node_counts[value] = node_counts.get(value, 0) + 1
            node_papers.setdefault(value, set()).add(paper_id)
        for index, left in enumerate(values):
            for right in values[index + 1 :]:
                _add_pair(edge_weights, left, right)

    degree: dict[str, int] = {node: 0 for node in node_counts}
    for (left, right), weight in edge_weights.items():
        degree[left] += weight
        degree[right] += weight
    selected = {
        node
        for node, count in node_counts.items()
        if count >= 2 or degree.get(node, 0) >= 2
    }
    nodes = [
        {
            "id": node,
            "label": node,
            "value": node_counts[node],
            "extra": {"papers": len(node_papers.get(node, set())), "degree": degree.get(node, 0)},
        }
        for node in selected
    ]
    edges = [
        {"source": left, "target": right, "weight": weight}
        for (left, right), weight in edge_weights.items()
        if left in selected and right in selected
    ]
    edges.sort(key=lambda edge: -edge["weight"])
    return nodes, edges[:MAX_EDGES]


def _paper_network(
    records: list[dict[str, Any]], network_type: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_doi = {record["doi"]: index for index, record in enumerate(records) if record.get("doi")}
    by_work_id = {str(record["id"]): index for index, record in enumerate(records)}
    nodes = [
        {
            "id": str(record.get("id") or record.get("paper_id") or index),
            "label": record.get("title") or "未命名",
            "value": max(1, int(record.get("cited_by_count") or 0)),
            "extra": {
                "authors": record.get("authors") or [],
                "year": record.get("year"),
                "citation_count": int(record.get("cited_by_count") or 0),
                "doi": record.get("doi") or None,
                "paper_id": record.get("paper_id"),
                "reference_count": len(record.get("references") or []),
            },
        }
        for index, record in enumerate(records)
    ]

    edge_weights: dict[tuple[str, str], int] = {}
    citation_weights: dict[tuple[str, str], int] = {}
    if network_type in ("citation", "paper_similarity"):
        for record in records:
            source_id = str(record.get("id") or record.get("paper_id"))
            for reference in record.get("references") or []:
                normalized = normalize_doi(reference) if str(reference).startswith("10.") else str(reference)
                target_id = None
                if normalized in by_doi:
                    target_id = str(records[by_doi[normalized]]["id"])
                elif normalized in by_work_id:
                    target_id = normalized
                if target_id and target_id != source_id:
                    key = (source_id, target_id) if source_id < target_id else (target_id, source_id)
                    citation_weights[key] = citation_weights.get(key, 0) + 1
    if network_type == "citation":
        edge_weights = citation_weights
    elif network_type == "bibliographic_coupling":
        reference_sets = [
            {
                normalize_doi(reference) if str(reference).startswith("10.") else str(reference)
                for reference in (record.get("references") or [])
            }
            for record in records
        ]
        for index, references in enumerate(reference_sets):
            if not references:
                continue
            for other in range(index + 1, len(reference_sets)):
                shared = references & reference_sets[other]
                if shared:
                    key = (str(records[index]["id"]), str(records[other]["id"]))
                    edge_weights[key] = len(shared)

    if network_type == "paper_similarity":
        vectors = [_paper_vector(record) for record in records]
        document_frequency = Counter()
        for vector in vectors:
            document_frequency.update(vector.keys())
        total = max(1, len(vectors))
        idf = {
            token: math.log((total + 1) / (frequency + 1)) + 1.0
            for token, frequency in document_frequency.items()
        }
        weights = [
            {token: frequency * idf.get(token, 1.0) for token, frequency in vector.items()}
            for vector in vectors
        ]
        similarities: list[tuple[float, int, int]] = []
        for index, left in enumerate(weights):
            for other in range(index + 1, len(weights)):
                score = _cosine(left, weights[other])
                if score >= 0.08:
                    similarities.append((score, index, other))
        similarities.sort(key=lambda item: (-item[0], item[1], item[2]))
        neighbor_count: dict[int, int] = {}
        for score, index, other in similarities:
            if neighbor_count.get(index, 0) >= 4 and neighbor_count.get(other, 0) >= 4:
                continue
            neighbor_count[index] = neighbor_count.get(index, 0) + 1
            neighbor_count[other] = neighbor_count.get(other, 0) + 1
            left, right = (str(records[index]["id"]), str(records[other]["id"]))
            key = (left, right) if left < right else (right, left)
            citation_strength = citation_weights.get(key, 0) * 40
            weight = min(100, round(score * 100) + 20)
            if citation_strength:
                weight = max(weight, citation_strength)
            edge_weights[key] = max(1, weight)

    node_ids = {str(node["id"]) for node in nodes}
    edge_objects: list[dict[str, Any]] = []
    for (left, right), weight in edge_weights.items():
        if left not in node_ids or right not in node_ids:
            continue
        kinds = ["similar"]
        if network_type == "paper_similarity" and (left, right) in citation_weights:
            kinds = ["citation", "similar"]
        edge_objects.append(
            {"source": left, "target": right, "weight": weight, "kinds": kinds}
        )
    edge_objects.sort(key=lambda edge: -edge["weight"])
    return nodes, edge_objects[:MAX_EDGES]


def _louvain_partition(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]], resolution: float = 1.0
) -> list[int]:
    ids = [str(node["id"]) for node in nodes]
    if not ids:
        return []

    labels = {node_id: index for index, node_id in enumerate(ids)}
    adjacency: dict[str, dict[str, int]] = {node_id: {} for node_id in ids}
    for edge in edges:
        left, right = str(edge["source"]), str(edge["target"])
        weight = max(1, int(edge.get("weight") or 1))
        if left in adjacency and right in adjacency:
            adjacency[left][right] = adjacency[left].get(right, 0) + weight
            adjacency[right][left] = adjacency[right].get(left, 0) + weight

    degree = {node_id: sum(adjacency[node_id].values()) for node_id in ids}
    total_degree = sum(degree.values()) or 1
    community_degree = {labels[node_id]: degree[node_id] for node_id in ids}

    def score(node_id: str, community: str, internal: int = 0) -> float:
        # Standard Louvain gain: prefer strong internal links, while resolution
        # penalizes joining large communities. A larger value gives finer clusters.
        return internal - resolution * degree[node_id] * community_degree.get(community, 0) / total_degree

    for _ in range(16):
        changed = False
        for node_id in ids:
            old_label = labels[node_id]
            community_degree[old_label] -= degree[node_id]

            internals: dict[str, int] = {}
            for neighbor, weight in adjacency[node_id].items():
                neighbor_label = labels[neighbor]
                internals[neighbor_label] = internals.get(neighbor_label, 0) + weight

            candidates = {old_label}
            candidates.update(internals)
            old_score = score(node_id, old_label, internals.get(old_label, 0))
            best_label = old_label
            best_score = old_score
            for candidate in candidates:
                candidate_score = score(node_id, candidate, internals.get(candidate, 0))
                # Stable tie-break keeps the original label and avoids order churn.
                if candidate_score > best_score + 1e-12 or (
                    abs(candidate_score - best_score) <= 1e-12 and candidate < best_label
                ):
                    best_label = candidate
                    best_score = candidate_score

            labels[node_id] = best_label
            community_degree[best_label] = community_degree.get(best_label, 0) + degree[node_id]
            if best_label != old_label:
                changed = True
        if not changed:
            break

    old_labels = sorted(set(labels.values()))
    remap = {old_label: new_label for new_label, old_label in enumerate(old_labels)}
    return [remap[labels[node_id]] for node_id in ids]


def _cluster_layout(labels: list[int], node_count: int) -> list[tuple[float, float]]:
    groups: dict[int, list[int]] = {}
    for index, label in enumerate(labels):
        groups.setdefault(label, []).append(index)
    cluster_count = max(1, len(groups))
    positions: list[tuple[float, float]] = [(900.0, 650.0)] * node_count
    golden = 2.39996
    for cluster_label, members in groups.items():
        angle = 2 * math.pi * cluster_label / cluster_count
        radius = min(560, 240 + cluster_count * 62)
        center_x = 900 + radius * math.cos(angle)
        center_y = 650 + radius * math.sin(angle) * 0.72
        for index, node_index in enumerate(members):
            inner = 52 + 260 * math.sqrt(index / max(1, len(members)))
            node_angle = index * golden + cluster_label
            positions[node_index] = (
                center_x + inner * math.cos(node_angle),
                center_y + inner * math.sin(node_angle),
            )
    return positions


def _force_layout(
    labels: list[int], nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[tuple[float, float]]:
    """Cluster-aware spring layout with deterministic hard collision resolution."""
    count = len(nodes)
    if count == 0:
        return []
    if count == 1:
        return [(900.0, 650.0)]

    positions = _cluster_layout(labels, count)
    groups: dict[int, list[int]] = {}
    for index, label in enumerate(labels):
        groups.setdefault(label, []).append(index)

    # A slightly denser target than the final collision distance keeps clusters
    # recognizable while still leaving room for labels and hover states.
    min_distance = 132.0
    ideal_distance = min(178.0, max(112.0, math.sqrt(1450.0 * 920.0 / count) * 0.88))
    node_index = {str(node["id"]): index for index, node in enumerate(nodes)}
    adjacency: dict[int, dict[int, float]] = {index: {} for index in range(count)}
    for edge in edges:
        left = node_index.get(str(edge["source"]))
        right = node_index.get(str(edge["target"]))
        if left is None or right is None:
            continue
        if left == right:
            continue
        strength = min(3.0, 0.6 + math.sqrt(max(1.0, float(edge.get("weight") or 1))) * 0.35)
        adjacency[left][right] = adjacency[left].get(right, 0.0) + strength
        adjacency[right][left] = adjacency[right].get(left, 0.0) + strength

    def _apply_collisions(iterations: int = 4) -> None:
        for _ in range(iterations):
            moved = False
            for left in range(count):
                for right in range(left + 1, count):
                    dx = positions[right][0] - positions[left][0]
                    dy = positions[right][1] - positions[left][1]
                    distance = math.hypot(dx, dy)
                    if distance >= min_distance:
                        continue
                    if distance < 1e-6:
                        angle = (left * 2.39996 + right * 1.17) % (2 * math.pi)
                        dx, dy = math.cos(angle), math.sin(angle)
                        distance = 1.0
                    push = (min_distance - distance) / distance * 0.55
                    left_x = positions[left][0] - dx * push
                    left_y = positions[left][1] - dy * push
                    right_x = positions[right][0] + dx * push
                    right_y = positions[right][1] + dy * push
                    positions[left] = (left_x, left_y)
                    positions[right] = (right_x, right_y)
                    moved = True
            if not moved:
                break

    for iteration in range(160):
        temperature = max(7.0, 46.0 * (1.0 - iteration / 160))
        displacement = [(0.0, 0.0)] * count

        # Pairwise repulsion: strong enough to spread dense clusters, but capped
        # so a huge cluster does not explode before edge springs pull it back.
        for left in range(count):
            for right in range(left + 1, count):
                dx = positions[right][0] - positions[left][0]
                dy = positions[right][1] - positions[left][1]
                distance = max(1.0, math.hypot(dx, dy))
                force = min(1800.0, ideal_distance * ideal_distance / distance)
                unit_x, unit_y = dx / distance, dy / distance
                left_x, left_y = displacement[left]
                right_x, right_y = displacement[right]
                displacement[left] = (left_x - unit_x * force, left_y - unit_y * force)
                displacement[right] = (right_x + unit_x * force, right_y + unit_y * force)

        for left, neighbors in adjacency.items():
            for right, strength in neighbors.items():
                dx = positions[right][0] - positions[left][0]
                dy = positions[right][1] - positions[left][1]
                distance = max(1.0, math.hypot(dx, dy))
                force = (distance - ideal_distance * (1.15 if strength > 1.2 else 1.0)) * strength * 0.055
                unit_x, unit_y = dx / distance, dy / distance
                left_x, left_y = displacement[left]
                right_x, right_y = displacement[right]
                displacement[left] = (left_x + unit_x * force, left_y + unit_y * force)
                displacement[right] = (right_x - unit_x * force, right_y - unit_y * force)

        # Light gravity prevents disconnected nodes from drifting to infinity.
        for index, (x, y) in enumerate(positions):
            displacement[index] = ((900.0 - x) * 0.012 + displacement[index][0], (650.0 - y) * 0.012 + displacement[index][1])

        cluster_centers: dict[int, tuple[float, float]] = {}
        for members in groups.values():
            center_x = sum(positions[index][0] for index in members) / len(members)
            center_y = sum(positions[index][1] for index in members) / len(members)
            for index in members:
                cluster_centers[index] = (center_x, center_y)
        for index, center in cluster_centers.items():
            x, y = positions[index]
            displacement[index] = (displacement[index][0] + (center[0] - x) * 0.035, displacement[index][1] + (center[1] - y) * 0.035)

        max_force = max(max(abs(x), abs(y)) for x, y in displacement) or 1.0
        scale = min(1.0, temperature / max_force)
        for index, (dx, dy) in enumerate(displacement):
            positions[index] = (positions[index][0] + dx * scale, positions[index][1] + dy * scale)
        _apply_collisions(3)

    _apply_collisions(12)
    return positions


def _cluster_info(nodes: list[dict[str, Any]], labels: list[int]) -> list[dict[str, Any]]:
    groups: dict[int, list[dict[str, Any]]] = {}
    for node, label in zip(nodes, labels):
        groups.setdefault(label, []).append(node)
    ordered = sorted(groups, key=lambda label: (-sum(node["value"] for node in groups[label]), label))
    info: list[dict[str, Any]] = []
    for new_label, old_label in enumerate(ordered):
        members = groups[old_label]
        raw_label = " · ".join(node["label"] for node in members[:2])
        info.append(
            {
                "id": new_label,
                "label": (raw_label if len(raw_label) <= 36 else raw_label[:33] + "...") or f"聚类 {new_label + 1}",
                "color": CLUSTER_COLORS[new_label % len(CLUSTER_COLORS)],
                "count": len(members),
            }
        )
    remap = {old_label: new_label for new_label, old_label in enumerate(ordered)}
    for node in nodes:
        node["cluster"] = remap[node["cluster"]]
    return info


def _build_network(
    records: list[dict[str, Any]], network_type: str, resolution: float = 1.0
) -> dict[str, Any]:
    if network_type in ("co_authorship", "co_occurrence"):
        field = "authors" if network_type == "co_authorship" else "keywords"
        nodes, edges = _cooccurrence_network(records, field)
        directed = False
    else:
        nodes, edges = _paper_network(records, network_type)
        directed = network_type == "citation"

    labels = _louvain_partition(nodes, edges, resolution=resolution)
    for node, label in zip(nodes, labels):
        node["cluster"] = label
    clusters = _cluster_info(nodes, labels)
    positions = _force_layout(labels, nodes, edges)
    for node, (x, y) in zip(nodes, positions):
        node["x"] = round(x, 1)
        node["y"] = round(y, 1)
    return {"nodes": nodes, "edges": edges, "clusters": clusters, "directed": directed}


def build_vosviewer_bundle(graph: dict[str, Any]) -> bytes:
    """Build a ZIP containing VOSviewer map and network tab-separated files."""
    max_density = 1.0
    density: dict[str, int] = {}
    for edge in graph.get("edges") or []:
        weight = max(1, int(edge.get("weight") or 1))
        density[str(edge["source"])] = density.get(str(edge["source"]), 0) + weight
        density[str(edge["target"])] = density.get(str(edge["target"]), 0) + weight
    max_density = max(max_density, max(density.values(), default=1))

    map_columns = [
        "label",
        "id",
        "x",
        "y",
        "weight<Weight>",
        "score<Citations>",
        "score<Publication year>",
        "score<Cluster density>",
        "cluster_number",
    ]
    map_lines = ["\t".join(map_columns)]
    for node in graph.get("nodes") or []:
        extra = node.get("extra") or {}
        citation = int(extra.get("citation_count") or 0)
        year = int(extra.get("year") or 0)
        node_density = int(density.get(str(node["id"]), 0)) / max_density
        values = [
            str(node.get("label") or node.get("id")).replace("\t", " ").replace("\r", " ").replace("\n", " "),
            str(node.get("id") or node.get("label") or ""),
            f'{float(node.get("x") or 0):.6f}',
            f'{float(node.get("y") or 0):.6f}',
            str(max(1, int(node.get("value") or 1))),
            str(citation),
            str(year),
            f"{node_density:.6f}",
            str(int(node.get("cluster") or 0) + 1),
        ]
        map_lines.append("\t".join(values))

    network_lines = ["source\ttarget\tstrength"]
    for edge in graph.get("edges") or []:
        network_lines.append(
            "\t".join(
                [
                    str(edge["source"]).replace("\t", " "),
                    str(edge["target"]).replace("\t", " "),
                    str(max(1, int(edge.get("weight") or 1))),
                ]
            )
        )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("vosviewer-map.txt", "\n".join(map_lines) + "\n", compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("vosviewer-network.txt", "\n".join(network_lines) + "\n", compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


def build_bibliometric_graph(
    db: Session,
    user_id,
    network_type: str = "co_authorship",
    source: str = "library",
    query: str = "",
    external_source: str = "openalex",
    limit: int = DEFAULT_LIMIT,
    cluster_resolution: float = 1.0,
) -> dict[str, Any]:
    network_type = (network_type or "").strip()
    if network_type not in NETWORK_TYPES:
        raise ValueError("不支持的图谱类型")
    source = (source or "library").strip()
    if source not in ("library", "external"):
        raise ValueError("不支持的数据来源")
    external_source = (external_source or "openalex").strip()
    if source == "external" and external_source not in EXTERNAL_SOURCES:
        raise ValueError("不支持的外部学术源")
    query = _clean_text(query)
    if source == "external" and not query:
        raise ValueError("外部数据源需要输入检索主题")
    limit = max(10, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    try:
        resolution = float(cluster_resolution)
    except (TypeError, ValueError):
        raise ValueError("聚类分辨率必须是数字")
    if not _MIN_RESOLUTION <= resolution <= _MAX_RESOLUTION:
        raise ValueError(f"聚类分辨率需在 {_MIN_RESOLUTION} 到 {_MAX_RESOLUTION} 之间")

    if source == "library":
        papers = (
            db.query(Paper)
            .filter(Paper.user_id == user_id)
            .order_by(Paper.created_at.desc())
            .limit(limit)
            .all()
        )
        records = [_paper_record(paper) for paper in papers]
        enrichment_source = None
        if network_type in ("citation", "bibliographic_coupling") and records:
            enrichment = _enrich_library_with_openalex(records)
            enrichment_source = "openalex"
            for record in records:
                extra = enrichment.get(record.get("doi") or "")
                if extra:
                    record["cited_by_count"] = extra["cited_by_count"]
                    record["references"] = extra["references"]
                    record["id"] = extra.get("openalex_id") or record["id"]
    else:
        fetchers = {
            "openalex": openalex_records,
            "crossref": crossref_records,
            "europe_pmc": europepmc_records,
        }
        records = _dedupe_records(fetchers[external_source](query, limit=limit))
        enrichment_source = None

    network = _build_network(records, network_type, resolution=resolution)
    return {
        "ok": True,
        "network_type": network_type,
        "network_label": NETWORK_TYPES[network_type],
        "source": source,
        "external_source": external_source if source == "external" else None,
        "enrichment_source": enrichment_source,
        "paper_count": len(records),
        "node_count": len(network["nodes"]),
        "edge_count": len(network["edges"]),
        "cluster_resolution": resolution,
        **network,
    }
