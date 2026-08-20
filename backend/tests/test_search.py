"""Pure helper functions used by semantic and keyword search."""
from app.services.search_service import _cosine, _keyword_score, _tokenize


def test_cosine_similarity_bounds() -> None:
    assert _cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert _cosine([1.0, 0.0], [1.0]) == 0.0
    assert _cosine([], []) == 0.0


def test_keyword_score_ranks_hits_first() -> None:
    tokens = _tokenize("copper flotation")
    hit = _keyword_score(tokens, "copper flotation is an important process")
    miss = _keyword_score(tokens, "mineral processing")
    assert hit > 0
    assert miss == 0
    assert hit > miss


def test_tokenize_splits_english_and_keeps_chinese() -> None:
    tokens = _tokenize("CPTU 浮选机理 Copper")
    assert "cptu" in tokens
    assert "copper" in tokens
    assert any("浮选" in t for t in tokens)
