from __future__ import annotations

import pytest

from src.text_utils import (
    compact_text,
    has_direct_definition,
    is_definition_question,
    is_outline_page,
    join_wrapped_lines,
    normalize_text,
    query_phrases,
    query_terms,
    split_sentences,
    tokenize,
)


def test_normalize_and_compact():
    assert normalize_text("ＡＢＣ　工程\t伦理") == "abc 工程 伦理"
    assert compact_text("工程 伦理，2020！") == "工程伦理2020"


def test_chinese_query_tokenization_and_stopwords():
    terms = query_terms("什么是工程风险的技术因素？")
    assert "工程" in terms
    assert "风险" in terms
    assert "技术" in terms
    assert "因素" in terms
    assert "什么" not in terms
    assert "是" not in terms


def test_query_phrases_extract_core_concepts():
    assert query_phrases("什么是工程伦理？") == ("工程伦理",)
    phrases = query_phrases("责任伦理与法律责任的区别")
    assert "责任伦理" in phrases
    assert "法律责任" in phrases


def test_join_wrapped_lines_merges_pdf_line_breaks():
    text = (
        "2.2.1 工程风险的来源\n\n"
        "1、工程风险的技术因素\n\n"
        "  1）工程中零部件老化，导致系统功能失调，从而\n"
        "引发事故风险。\n"
    )
    paragraphs = join_wrapped_lines(text)
    assert "1）工程中零部件老化，导致系统功能失调，从而引发事故风险。" in paragraphs
    sentences = split_sentences(text)
    assert "1）工程中零部件老化，导致系统功能失调，从而引发事故风险。" in sentences


def test_join_wrapped_lines_keeps_numbered_items_separate():
    text = "具体方式：\n①拒绝，比如拒收礼物；\n②放弃，比如出售股份；\n⑤披露。"
    paragraphs = join_wrapped_lines(text)
    assert "①拒绝，比如拒收礼物；" in paragraphs
    assert "②放弃，比如出售股份；" in paragraphs


def test_outline_page_detection():
    outline = (
        "二、工程中的风险、责任与安全 1、经典案例 2、工程风险的来源及防范 "
        "3、工程风险的伦理评估 4、工程风险中的伦理责任 5、案例分析"
    )
    assert is_outline_page(outline)
    assert not is_outline_page(
        "工程风险的技术因素包括零部件老化、控制系统失灵和非线性作用。"
        "因此需要在设计阶段进行风险评估。"
    )


def test_definition_question_detection_and_direct_definition():
    assert is_definition_question("什么是工程伦理？")
    assert is_definition_question("工程风险的定义")
    assert not is_definition_question("工程风险的技术因素有哪些")

    assert has_direct_definition("什么是工程伦理？", "工程伦理是一种职业伦理。")
    assert not has_direct_definition("什么是工程伦理？", "工程伦理规范是指工程师应遵循的行为准则。")
    assert not has_direct_definition("什么是工程伦理？", "制药工程伦理是一门交叉学科。")


def test_empty_input_is_safe():
    assert tokenize("") == ()
    assert query_phrases("") == ()
    assert split_sentences("") == []


def test_bm25_style_tokens_include_latin_and_numbers():
    terms = tokenize("AI 工程师 2024 年")
    assert "ai" in terms
    assert "工程师" in terms
    assert "2024" in terms
