from __future__ import annotations

import pytest

from src.bm25 import BM25Index


def test_bm25_ranks_matching_document_first():
    index = BM25Index(
        [
            ["工程", "风险", "技术", "因素"],
            ["工程", "伦理", "规范"],
            ["环境", "伦理", "原则"],
        ]
    )
    scores = index.score(["风险", "技术"])
    assert scores[0] > scores[1]
    assert scores[0] > scores[2]
    assert scores[1] == 0.0


def test_bm25_idf_and_document_frequency():
    index = BM25Index([["工程", "风险"], ["工程", "伦理"], ["工程", "安全"]])
    assert index.doc_count == 3
    assert index.document_frequency["工程"] == 3
    assert index.document_frequency["风险"] == 1
    assert index.idf("风险") > index.idf("工程")


def test_bm25_unseen_term_has_high_idf_but_no_score():
    index = BM25Index([["工程", "伦理"]])
    scores = index.score(["量子计算"])
    assert scores == [0.0]
    assert index.idf("量子计算") > index.idf("工程")


def test_bm25_duplicate_query_terms_count_once():
    index = BM25Index([["工程", "风险"], ["工程", "伦理"]])
    assert index.score(["工程", "工程"]) == index.score(["工程"])


def test_bm25_parameters_validated():
    with pytest.raises(ValueError):
        BM25Index([["工程"]], k1=-1)
    with pytest.raises(ValueError):
        BM25Index([["工程"]], b=1.5)


def test_empty_index_is_safe():
    index = BM25Index([])
    assert index.doc_count == 0
    assert index.score(["工程"]) == []
