from __future__ import annotations

from pathlib import Path

import pytest

from src.config import PROJECT_ROOT, Settings
from src.corpus import load_corpus
from src.qa import STATUS_INSUFFICIENT, STATUS_OK, AnswerEngine
from src.retriever import MODE_EXPANDED, MODE_STRICT, Retriever


DATA_DIR = PROJECT_ROOT / "data" / "processed_v3"
pytestmark = pytest.mark.skipif(
    not DATA_DIR.is_dir(),
    reason="需要本地 processed_v3 课件数据",
)


@pytest.fixture(scope="module")
def corpus():
    return load_corpus(DATA_DIR)


def test_real_corpus_counts(corpus):
    stats = corpus.stats()
    assert stats["documents"] == 10
    assert stats["total_pages"] == 607
    assert stats["text_pages"] == 590
    assert stats["strict_pages"] == 81
    assert stats["expanded_pages"] == 590
    assert stats["reviewed_pages"] == 145
    assert stats["unreviewed_pages"] == 462


def test_every_strict_page_is_explicitly_reviewed(corpus):
    for page in corpus.strict_pages:
        assert page.reviewed
        assert page.text.strip()
        assert page.review_category == "A" or (
            page.review_category == "B" and page.repair_applied
        )


def test_no_unreviewed_page_is_marked_strict(corpus):
    for page in corpus.pages:
        if page.review_category is None:
            assert not page.strict_eligible
            assert page.review_label.startswith("未审核")


def test_real_strict_retrieval_has_filename_and_page(corpus):
    response = Retriever(corpus).search(
        "工程风险的技术因素有哪些", mode=MODE_STRICT, top_k=3
    )
    assert response.hits
    top = response.hits[0]
    assert top.page.filename.endswith(".pdf")
    assert top.page.page_number == 8
    assert top.strict_eligible
    assert top.citation.endswith("第 8 页")


def test_known_gap_is_insufficient_in_strict_but_found_in_expanded(corpus):
    retriever = Retriever(corpus)
    strict = retriever.search("责任伦理与法律责任的区别", mode=MODE_STRICT)
    expanded = retriever.search("责任伦理与法律责任的区别", mode=MODE_EXPANDED)
    assert strict.hits == ()
    assert expanded.hits
    assert any(hit.evidence_status != "strict" for hit in expanded.hits)


def test_real_definition_question_is_honest_about_missing_definition(corpus):
    engine = AnswerEngine(Retriever(corpus), settings=Settings(deepseek_api_key=None))
    strict = engine.answer("什么是工程伦理？", mode=MODE_STRICT)
    assert strict.status == STATUS_INSUFFICIENT
    expanded = engine.answer("什么是工程伦理？", mode=MODE_EXPANDED)
    assert expanded.status == STATUS_OK
    assert expanded.warnings
    assert any(
        hit.evidence_status != "strict" for hit in expanded.citations
    )


def test_real_local_answer_keeps_pdf_page_citation(corpus):
    engine = AnswerEngine(Retriever(corpus), settings=Settings(deepseek_api_key=None))
    answer = engine.answer("工程风险的技术因素有哪些？", mode=MODE_STRICT)
    assert answer.status == STATUS_OK
    assert answer.citations
    assert "《" in answer.answer and "第" in answer.answer
    assert all(hit.page.filename.endswith(".pdf") for hit in answer.citations)
