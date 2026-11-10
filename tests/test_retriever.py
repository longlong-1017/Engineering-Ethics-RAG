from __future__ import annotations

import pytest

from src.retriever import MODE_EXPANDED, MODE_STRICT, Retriever
from tests.helpers import make_corpus, make_page


def _corpus():
    return make_corpus(
        make_page(
            "工程风险的技术因素包括零部件老化、控制系统失灵和非线性作用。",
            category="A",
            page_number=1,
            filename="严格课件.pdf",
        ),
        make_page(
            "工程风险的技术因素还包括人为因素、环境因素和管理因素。",
            category=None,
            page_number=2,
            filename="未审核课件.pdf",
        ),
        make_page(
            "工程风险的技术因素在图片中，文字未提取。",
            category="C",
            page_number=3,
            filename="图片课件.pdf",
        ),
    )


def test_strict_search_only_returns_strict_pages():
    response = Retriever(_corpus()).search("工程风险的技术因素", mode=MODE_STRICT)
    assert response.hits
    assert all(hit.page.strict_eligible for hit in response.hits)
    assert all(hit.evidence_status == "strict" for hit in response.hits)


def test_expanded_search_marks_unreviewed_and_hold_pages():
    response = Retriever(_corpus()).search("工程风险的技术因素", mode=MODE_EXPANDED)
    statuses = {hit.page.page_number: hit.evidence_status for hit in response.hits}
    assert statuses[1] == "strict"
    assert statuses[2] == "unreviewed"
    assert statuses[3] == "reviewed_hold"
    assert response.has_unreviewed
    assert response.has_hold
    assert "未审核" in response.evidence_warning


def test_strict_search_empty_when_only_unreviewed_matches():
    corpus = make_corpus(
        make_page("工程风险的技术因素包括零部件老化。", category="A", page_number=1),
        make_page("量子计算在工程伦理中的讨论。", category=None, page_number=2),
    )
    retriever = Retriever(corpus)
    assert retriever.search("量子计算", mode=MODE_STRICT).hits == ()
    expanded = retriever.search("量子计算", mode=MODE_EXPANDED)
    assert expanded.hits
    assert expanded.hits[0].evidence_status == "unreviewed"


def test_unrelated_query_returns_no_hits():
    response = Retriever(_corpus()).search("今天天气怎么样", mode=MODE_EXPANDED)
    assert response.hits == ()
    assert not response.enough_evidence


def test_duplicate_text_is_merged_and_strict_source_preferred():
    text = "工程风险的技术因素包括零部件老化。"
    corpus = make_corpus(
        make_page(text, category=None, page_number=1, filename="未审核.pdf", doc_id="a"),
        make_page(text, category="A", page_number=1, filename="严格.pdf", doc_id="b"),
    )
    response = Retriever(corpus).search("工程风险的技术因素", mode=MODE_EXPANDED)
    assert len(response.hits) == 1
    assert response.hits[0].page.strict_eligible
    assert response.hits[0].duplicate_count == 1


def test_definition_question_prefers_direct_definition():
    corpus = make_corpus(
        make_page(
            "工程伦理规范是指工程师面对伦理问题时应遵循的行为准则。",
            category="A",
            page_number=1,
        ),
        make_page(
            "工程伦理是一种职业伦理，关注工程师的责任。",
            category=None,
            page_number=2,
        ),
    )
    retriever = Retriever(corpus)
    strict = retriever.search("什么是工程伦理", mode=MODE_STRICT)
    assert all(hit.page.page_number == 1 for hit in strict.hits)
    expanded = retriever.search("什么是工程伦理", mode=MODE_EXPANDED)
    assert expanded.hits[0].page.page_number == 2
    assert expanded.hits[0].phrase_match is True


def test_invalid_mode_raises():
    with pytest.raises(ValueError):
        Retriever(_corpus()).search("工程风险", mode="unknown")


def test_phrase_match_boosts_exact_phrase():
    corpus = make_corpus(
        make_page("利益冲突是工程职业伦理的重要问题。", category="A", page_number=1),
        make_page("工程与伦理的一般介绍。", category="A", page_number=2),
    )
    response = Retriever(corpus).search("利益冲突", mode=MODE_STRICT)
    assert response.hits[0].page.page_number == 1
    assert response.hits[0].phrase_match
