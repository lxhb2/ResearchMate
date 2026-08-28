import io
import math
import zipfile

from app.services.bibliometric_service import (
    _build_network,
    _force_layout,
    _keywords_from_record,
    _louvain_partition,
    build_vosviewer_bundle,
    normalize_doi,
)


RECORDS = [
    {
        "id": "A",
        "title": "Alpha graph network",
        "authors": ["Ann Lee", "Bob Chen"],
        "keywords": [],
        "abstract": "Graph network methods for graph analysis",
        "doi": "10.1000/a",
        "references": ["10.1000/r1", "10.1000/r2"],
        "cited_by_count": 12,
        "paper_id": "paper-a",
    },
    {
        "id": "B",
        "title": "Beta network learning",
        "authors": ["Bob Chen", "Cid Diaz"],
        "keywords": [],
        "abstract": "Network learning and graph representation",
        "doi": "10.1000/b",
        "references": ["10.1000/r2", "10.1000/r3"],
        "cited_by_count": 6,
        "paper_id": "paper-b",
    },
    {
        "id": "C",
        "title": "Gamma graph learning",
        "authors": ["Ann Lee", "Cid Diaz"],
        "keywords": [],
        "abstract": "Graph learning methods",
        "doi": "10.1000/c",
        "references": ["10.1000/r1", "10.1000/r3"],
        "cited_by_count": 2,
        "paper_id": "paper-c",
    },
]


def test_normalize_doi_accepts_common_forms():
    assert normalize_doi("https://doi.org/10.1000/A.") == "10.1000/a"
    assert normalize_doi("doi: 10.1000/a") == "10.1000/a"


def test_keywords_are_extracted_without_substring_noise():
    record = {
        "title": "Graph network methods for graph analysis",
        "abstract": "Network learning and graph representation",
    }
    keywords = _keywords_from_record(record)
    assert "Graph" in keywords
    assert "Network" in keywords
    assert not any(word in {"graph", "network"} for word in keywords)


def test_coauthorship_network_counts_shared_authors():
    result = _build_network(RECORDS, "co_authorship")
    weights = {
        tuple(sorted((edge["source"], edge["target"]))): edge["weight"]
        for edge in result["edges"]
    }
    assert result["directed"] is False
    assert weights[("Ann Lee", "Bob Chen")] == 1
    assert weights[("Bob Chen", "Cid Diaz")] == 1
    assert weights[("Ann Lee", "Cid Diaz")] == 1
    assert all(node["x"] and node["y"] for node in result["nodes"])


def test_keyword_cooccurrence_uses_extracted_terms():
    result = _build_network(RECORDS, "co_occurrence")
    labels = {node["label"].lower() for node in result["nodes"]}
    assert {"graph", "network", "learning"} <= labels
    assert len(result["edges"]) >= 2


def test_bibliographic_coupling_counts_shared_references():
    result = _build_network(RECORDS, "bibliographic_coupling")
    weights = {
        tuple(sorted((edge["source"], edge["target"]))): edge["weight"]
        for edge in result["edges"]
    }
    assert weights[("A", "B")] == 1
    assert weights[("A", "C")] == 1
    assert weights[("B", "C")] == 1


def test_citation_network_is_corpus_internal():
    result = _build_network(RECORDS, "citation")
    assert result["directed"] is True
    assert result["edges"] == []


def test_paper_similarity_merges_text_and_citation_relations():
    records = [
        {
            "id": "A",
            "title": "Graph network learning",
            "abstract": "Graph network learning methods for graph analysis",
            "keywords": ["graph"],
            "doi": "10.1000/a",
            "references": ["10.1000/b"],
            "cited_by_count": 10,
        },
        {
            "id": "B",
            "title": "Graph network learning",
            "abstract": "Graph network learning methods for graph analysis",
            "keywords": ["graph"],
            "doi": "10.1000/b",
            "references": [],
            "cited_by_count": 5,
        },
    ]
    result = _build_network(records, "paper_similarity")
    assert result["directed"] is False
    assert len(result["edges"]) == 1
    assert set(result["edges"][0]["kinds"]) == {"citation", "similar"}


def test_force_layout_resolves_dense_node_collisions():
    node_count = 60
    labels = [index % 3 for index in range(node_count)]
    nodes = [{"id": str(index)} for index in range(node_count)]
    edges = [
        {"source": str(index), "target": str((index + 1) % node_count), "weight": 2}
        for index in range(node_count)
    ]
    positions = _force_layout(labels, nodes, edges)

    for index, left in enumerate(positions):
        for right in positions[index + 1 :]:
            assert math.hypot(left[0] - right[0], left[1] - right[1]) >= 130.0


def test_cluster_resolution_controls_granularity():
    nodes = [{"id": node_id} for node_id in "ABCD"]
    edges = [
        {"source": "A", "target": "B", "weight": 1},
        {"source": "B", "target": "C", "weight": 2},
        {"source": "C", "target": "D", "weight": 1},
    ]

    coarse = _louvain_partition(nodes, edges, resolution=0.5)
    fine = _louvain_partition(nodes, edges, resolution=1.5)
    assert len(set(coarse)) == 1
    assert len(set(fine)) == 2


def test_vosviewer_bundle_contains_map_and_network_files():
    records = [
        {"id": node_id, "title": node_id, "authors": [], "keywords": [], "references": []}
        for node_id in "ABCDEF"
    ]
    by_id = {record["id"]: record for record in records}
    for left, right in [("A", "B"), ("B", "C"), ("C", "A"), ("C", "D")]:
        by_id[left]["authors"].append(right)
        by_id[right]["authors"].append(left)
    graph = _build_network(records, "co_authorship", resolution=1.0)

    with zipfile.ZipFile(io.BytesIO(build_vosviewer_bundle(graph))) as archive:
        assert archive.namelist() == ["vosviewer-map.txt", "vosviewer-network.txt"]
        map_text = archive.read("vosviewer-map.txt").decode("utf-8")
        network_text = archive.read("vosviewer-network.txt").decode("utf-8")

    assert map_text.splitlines()[0] == (
        "label\tid\tx\ty\tweight<Weight>\tscore<Citations>\t"
        "score<Publication year>\tscore<Cluster density>\tcluster_number"
    )
    assert network_text.splitlines()[0] == "source\ttarget\tstrength"
    assert len(map_text.splitlines()) == len(graph["nodes"]) + 1
    assert len(network_text.splitlines()) == len(graph["edges"]) + 1
