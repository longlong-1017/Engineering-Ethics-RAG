from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.corpus import (
    CorpusError,
    format_stats,
    load_corpus,
)
from tests.helpers import record, write_document


def test_load_corpus_classifies_strict_expanded_and_unreviewed(tmp_path: Path):
    records = [
        record(1, "工程风险的技术因素包括零部件老化。", category="A"),
        record(2, "工程风险的伦理责任需要工程师承担。", category="B", repaired=True),
        record(3, "工程风险的结构仍需核准。", category="B", repaired=False),
        record(4, "工程风险图片中的文字未提取。", category="C"),
        record(5, "未审核页面的工程风险正文。"),
        record(6, "   ", category="A"),
    ]
    write_document(tmp_path, "课件.pdf", records)
    corpus = load_corpus(tmp_path)

    assert corpus.total_pages == 6
    assert len(corpus.text_pages) == 5
    assert len(corpus.strict_pages) == 2
    assert len(corpus.expanded_pages) == 5
    assert len(corpus.reviewed_pages) == 5
    assert len(corpus.unreviewed_pages) == 1
    assert [page.page_number for page in corpus.strict_pages] == [1, 2]

    categories = {page.page_number: page.evidence_status for page in corpus.pages}
    assert categories[1] == "strict"
    assert categories[2] == "strict"
    assert categories[3] == "reviewed_hold"
    assert categories[4] == "reviewed_hold"
    assert categories[5] == "unreviewed"
    assert categories[6] == "no_text"


def test_review_labels_are_explicit(tmp_path: Path):
    write_document(
        tmp_path,
        "课件.pdf",
        [
            record(1, "A 类正文。", category="A"),
            record(2, "B 类已修复。", category="B", repaired=True),
            record(3, "B 类未修复。", category="B", repaired=False),
            record(4, "C 类图片缺字。", category="C"),
            record(5, "E 类可见性存疑。", category="E"),
            record(6, "未审核正文。"),
        ],
    )
    pages = {page.page_number: page for page in load_corpus(tmp_path).pages}
    assert "严格合格" in pages[1].strict_label
    assert "严格合格" in pages[2].strict_label
    assert "未修复" in pages[3].review_label
    assert "图片文字未提取" in pages[4].review_label
    assert "无法确认" in pages[5].review_label
    assert pages[6].review_label.startswith("未审核")
    assert pages[1].citation == "《课件.pdf》第 1 页"


def test_stats_and_format_stats(tmp_path: Path):
    write_document(
        tmp_path,
        "课件.pdf",
        [
            record(1, "A 类。", category="A"),
            record(2, "未审核。"),
        ],
    )
    stats = load_corpus(tmp_path).stats()
    assert stats["documents"] == 1
    assert stats["total_pages"] == 2
    assert stats["text_pages"] == 2
    assert stats["strict_pages"] == 1
    assert stats["expanded_pages"] == 2
    text = format_stats(stats)
    assert "严格检索页面：1" in text
    assert "未审核" in text


def test_missing_directory_raises(tmp_path: Path):
    with pytest.raises(CorpusError):
        load_corpus(tmp_path / "missing")


def test_empty_directory_raises(tmp_path: Path):
    with pytest.raises(CorpusError):
        load_corpus(tmp_path)


def test_malformed_json_raises(tmp_path: Path):
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(CorpusError, match="无法读取 JSON"):
        load_corpus(tmp_path)


def test_missing_pages_raises(tmp_path: Path):
    (tmp_path / "bad.json").write_text(
        json.dumps({"filename": "x.pdf", "document_id": "x"}),
        encoding="utf-8",
    )
    with pytest.raises(CorpusError, match="pages"):
        load_corpus(tmp_path)


def test_duplicate_page_number_raises(tmp_path: Path):
    write_document(
        tmp_path,
        "课件.pdf",
        [record(1, "第一页。"), record(1, "重复页码。")],
    )
    with pytest.raises(CorpusError, match="重复页码"):
        load_corpus(tmp_path)


def test_invalid_page_number_raises(tmp_path: Path):
    payload = {
        "filename": "课件.pdf",
        "document_id": "doc-1",
        "pages": [{"text": "正文", "status": "text"}],
    }
    (tmp_path / "bad.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CorpusError, match="page_number"):
        load_corpus(tmp_path)
