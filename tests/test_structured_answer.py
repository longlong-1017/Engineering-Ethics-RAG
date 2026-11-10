"""结构化 JSON 答案：解析、事实校验、统一渲染的回归。"""
from __future__ import annotations

from types import SimpleNamespace

from src.config import Settings
from src.corpus import load_corpus
from src.qa import QA_MODE_HYBRID, STATUS_INSUFFICIENT, STATUS_OK, AnswerEngine, _safe_model_output
from src.retriever import Retriever
from src.structured_answer import (
    parse_structured_answer,
    render_structured_answer,
    validate_structured_answer,
)
from tests.helpers import make_corpus, make_page, structured_answer
from tests.test_qa import FakeClient


def _engine(pages, content):
    fake = FakeClient(content=content)
    engine = AnswerEngine(
        Retriever(make_corpus(*pages)),
        settings=Settings(deepseek_api_key="synthetic-structured-key", api_enabled=True),
        client=fake,
    )
    return engine, fake


def _hits(pages):
    from src.evidence import plan_evidence

    question = "环境工程中的安全与社会公正有什么关系？"
    return question, plan_evidence(question, [])


def test_safe_raw_output_is_truncated_and_redacted():
    raw = "sk-synthetic-secret-value " + "x" * 5000
    safe = _safe_model_output(raw)
    assert "synthetic-secret-value" not in safe
    assert "[REDACTED]" in safe
    assert len(safe) <= 4000


def test_parse_accepts_code_fence_and_renders_sections():
    from src.corpus import load_corpus
    from src.retriever import Retriever
    from src.evidence import plan_evidence

    question = "环境工程中的安全与社会公正有什么关系？"
    search = Retriever(load_corpus()).search(question, mode="expanded", top_k=10)
    plan = plan_evidence(question, search.hits)
    evidence_map = {hit.rank: (hit, text) for hit, text in plan.quotes}
    allowed = tuple(evidence_map)
    raw = structured_answer(
        "环境工程中的安全与社会公正是相互关联的。",
        [
            ("环境工程安全包括生产安全、公共安全和环境生态安全。", ["S3"]),
            ("环境公正应做到公平分配社会资源。", ["S1"]),
        ],
        conclusion="安全与公正是相互关联的。",
    )
    wrapped = "```json\n" + raw + "\n```"
    parsed = parse_structured_answer(wrapped, allowed)
    assert parsed.ok and parsed.answer
    checked = validate_structured_answer(parsed.answer, question, evidence_map)
    assert checked.ok, checked.errors
    rendered = render_structured_answer(checked.answer, evidence_map)
    assert "【简明答案】" in rendered
    assert "【分点论述】" in rendered
    assert "【总结】" in rendered
    assert "【参考依据】" in rendered
    assert "[S3]" in rendered and "[S1]" in rendered
    assert ".pdf" in rendered


def test_parse_rejects_missing_fields_and_bad_citations():
    parsed = parse_structured_answer('{"summary":"x","points":[],"insufficient":false}', (1,))
    assert not parsed.ok
    assert any("conclusion" in error for error in parsed.errors)

    parsed = parse_structured_answer(
        structured_answer("x", [("事实", ["S9"])]), (1,)
    )
    assert not parsed.ok
    assert any("不存在的证据编号" in error for error in parsed.errors)


def test_parse_rejects_model_generated_pdf_or_page():
    raw = structured_answer("第一页的内容", [("事实。", ["S1"])])
    parsed = parse_structured_answer(raw, (1,))
    assert not parsed.ok
    assert any("PDF" in error or "页码" in error for error in parsed.errors)


def test_parse_removes_inline_citation_but_requires_citations_array():
    raw = structured_answer("总结", [("事实。 [S1]", ["S1"])])
    parsed = parse_structured_answer(raw, (1,))
    assert parsed.ok
    assert "[S1]" not in parsed.answer.points[0].content
    assert "内联" in parsed.warnings[0]


def test_structured_validator_rejects_wrong_number_and_unknown_entity():
    pages = [make_page(
        "环境工程中的安全与社会公正\n环境工程安全包括生产安全、公共安全和环境生态安全。",
        category="A", page_number=28,
    )]
    evidence = "环境工程中的安全与社会公正\n环境工程安全包括生产安全、公共安全和环境生态安全。"
    bad_number = parse_structured_answer(
        structured_answer("", [("事故造成999人死亡。", ["S1"])]), (1,)
    )
    assert bad_number.ok
    checked = validate_structured_answer(
        bad_number.answer, "环境工程中的安全与社会公正有什么关系？",
        {1: (type("H", (), {"strict_eligible": True})(), evidence)},
    )
    assert not checked.ok
    assert any("数字" in error for error in checked.errors)

    bad_entity = parse_structured_answer(
        structured_answer("", [("三峡大坝工程证明安全与公正无关。", ["S1"])]), (1,)
    )
    checked = validate_structured_answer(
        bad_entity.answer, "环境工程中的安全与社会公正有什么关系？",
        {1: (type("H", (), {"strict_eligible": True})(), evidence)},
    )
    assert not checked.ok


def test_structured_summary_with_new_number_is_rejected():
    parsed = parse_structured_answer(
        structured_answer(
            "事故造成999人死亡。",
            [("安全包括生产安全。", ["S1"])],
        ),
        (1,),
    )
    assert parsed.ok
    checked = validate_structured_answer(
        parsed.answer, "工程事故的后果是什么？",
        {1: (SimpleNamespace(), "安全包括生产安全。")},
    )
    assert not checked.ok
    assert any("数字" in error for error in checked.errors)


def test_structured_point_with_irrelevant_extra_citation_is_rejected():
    parsed = parse_structured_answer(
        structured_answer(
            "",
            [("安全包括生产安全。", ["S1", "S2"])],
        ),
        (1, 2),
    )
    assert parsed.ok
    checked = validate_structured_answer(
        parsed.answer, "工程安全包括什么？",
        {
            1: (SimpleNamespace(), "工程安全包括生产安全。"),
            2: (SimpleNamespace(), "社会公正要求公平分配资源。"),
        },
    )
    assert not checked.ok
    assert any("无实质重合" in error for error in checked.errors)


def test_insufficient_json_returns_no_rendered_citations():
    parsed = parse_structured_answer(
        structured_answer("缺少安全页证据。", insufficient=True), (1,)
    )
    assert parsed.ok and parsed.answer.insufficient
    rendered = render_structured_answer(parsed.answer, {})
    assert "资料不足" in rendered
    assert "[S1]" not in rendered


def test_target_question_with_multiple_points_uses_real_pages_and_unreviewed_warning():
    content = structured_answer(
        "环境工程中的安全与社会公正是相互关联的：安全是首要责任，社会公正要求资源公平分配。",
        [
            ("环境工程安全包括生产安全、公共安全和环境生态安全。", ["S3"]),
            ("环境工程中的社会公正涉及资源和利益的分配。", ["S2"]),
            ("环境公正应做到公平分配社会资源，分配不公会造成社会断裂。", ["S1"]),
        ],
        conclusion="安全与公正是相互关联的，应同时考虑。",
    )
    fake = FakeClient(content=content)
    engine = AnswerEngine(
        Retriever(load_corpus()),
        settings=Settings(deepseek_api_key="synthetic-structured-key", api_enabled=True),
        client=fake,
    )
    result = engine.answer(
        "环境工程中的安全与社会公正有什么关系？",
        qa_mode=QA_MODE_HYBRID,
        provider="deepseek",
        allow_api=True,
    )
    assert fake.calls == 1
    assert result.status == STATUS_OK
    assert result.provider == "deepseek"
    assert result.evidence_source == "expanded"
    assert {hit.page.page_number for hit in result.citations} >= {28, 33, 34}
    assert any(hit.evidence_status == "unreviewed" for hit in result.citations)
    assert "【简明答案】" in result.answer
    assert "【分点论述】" in result.answer
    assert "【总结】" in result.answer
    assert "【参考依据】" in result.answer
    assert "环境.pdf" not in result.answer  # 真实文件名由证据卡片提供，而非模型
    assert any("未审核" in warning for warning in result.warnings)


def test_free_text_json_parse_failure_falls_back_and_never_switches_to_general():
    page = make_page(
        "工程风险的技术因素\n"
        "1）零部件老化，导致系统功能失调。\n"
        "2）控制系统失灵。\n"
        "3）非线性作用。",
        category="A", page_number=8,
    )
    engine, fake = _engine([page], "结论：工程风险包括零部件老化。 [S1]")
    result = engine.answer(
        "工程风险的技术因素有哪些？",
        qa_mode=QA_MODE_HYBRID,
        provider="deepseek",
        allow_api=True,
    )
    assert fake.calls == 1
    assert result.provider == "local"
    assert result.api_outcome == "unparseable"
    assert "JSON 解析失败" in result.api_reason
    assert "AI 通用知识补充" not in result.answer
    assert result.verification_status == "failed"


def test_structured_insufficient_does_not_fabricate_an_answer():
    page = make_page(
        "环境工程中的安全与社会公正\n"
        "1、环境工程中的安全\n环境工程安全包括生产安全、公共安全。\n"
        "2、环境工程中的社会公正\n环境公正应公平分配社会资源。",
        category="A", page_number=28,
    )
    engine, fake = _engine(
        [page],
        structured_answer("现有证据不足，缺少安全页。", insufficient=True),
    )
    result = engine.answer(
        "环境工程中的安全与社会公正有什么关系？",
        qa_mode=QA_MODE_HYBRID,
        provider="deepseek",
        allow_api=True,
    )
    assert fake.calls == 1
    assert result.status == STATUS_INSUFFICIENT
    assert result.provider == "none"
    assert result.citations == ()
