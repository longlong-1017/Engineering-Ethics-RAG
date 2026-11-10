"""智能混合/通用知识模式的 Mock 回归；不联网、不使用真实凭据。"""
from __future__ import annotations

from dataclasses import replace

from src.config import Settings
from src.deepseek_client import DeepSeekClient
from src.qa import (
    QA_MODE_GENERAL,
    QA_MODE_HYBRID,
    QA_MODE_RAG,
    STATUS_ERROR,
    STATUS_INSUFFICIENT,
    STATUS_OK,
    AnswerEngine,
)
from src.retriever import Retriever
from tests.helpers import make_corpus, make_page, structured_answer
from tests.test_deepseek_client import FakeSession
from tests.test_qa import FakeClient


GENERAL = (
    "【简明答案】\n"
    "功利主义看后果，义务论看规则。\n\n"
    "【分点说明】\n"
    "1. 功利主义强调最大多数人的最大幸福。\n"
    "2. 义务论强调遵守普遍道德规则。\n\n"
    "【参考依据】\n"
    "- AI 通用知识补充，未经课件核实。"
)


def _corpus():
    return make_corpus(
        make_page(
            "2.2.1 工程风险的来源\n"
            "1、工程风险的技术因素\n"
            "1）零部件老化，导致系统功能失调，从而引发事故风险。\n"
            "2）控制系统失灵，存在引发事故的隐患。\n"
            "3）非线性作用会引发安全隐患。",
            category="A", page_number=8, filename="严格风险.pdf",
        ),
        make_page(
            "2.2.2 工程风险的可接受性\n"
            "工程风险不可能为0，需要将风险控制在可接受范围内。\n"
            "1）分析风险可接受性；2）界定安全等级；3）制定预警机制和应急预案。",
            category=None, page_number=32, filename="未审核风险.pdf",
        ),
    )


def _env_corpus():
    return make_corpus(
        make_page(
            "环境工程中的安全与社会公正\n环境公正应做到公平分配社会资源；"
            "分配不公会造成社会断裂。",
            category="A", page_number=34, filename="环境.pdf",
        ),
        make_page(
            "环境工程中的安全与社会公正\n1、环境工程中的安全\n"
            "环境工程的安全主要包括生产安全、公共安全和环境生态安全。",
            category=None, page_number=28, filename="环境.pdf",
        ),
        make_page(
            "环境工程中的安全与社会公正\n2、环境工程中的社会公正\n"
            "环境工程中的社会公正涉及资源和利益的分配，可能产生工程得益者与受害者的矛盾。",
            category=None, page_number=33, filename="环境.pdf",
        ),
    )


def _engine(corpus, content=GENERAL, *, settings=None, client=None):
    client = client or FakeClient(content=content)
    return AnswerEngine(
        Retriever(corpus),
        settings=settings or Settings(deepseek_api_key="synthetic-mode-key", api_enabled=True),
        client=client,
    ), client


def test_rag_mode_never_uses_general_knowledge_or_api():
    engine, fake = _engine(_corpus())
    result = engine.answer(
        "功利主义与义务论在工程伦理中的区别是什么？",
        qa_mode=QA_MODE_RAG,
        provider="auto",
        allow_api=True,
    )
    assert result.status == STATUS_INSUFFICIENT
    assert result.qa_mode == QA_MODE_RAG
    assert result.general_knowledge is False
    assert fake.calls == 0
    assert result.citations == ()


def test_hybrid_prefers_strict_courseware():
    engine, fake = _engine(_corpus(), content=structured_answer(
        "工程风险的技术因素包括零部件老化、控制系统失灵和非线性作用。",
        [
            ("零部件老化会导致系统功能失调。", ["S1"]),
            ("控制系统失灵会带来事故隐患。", ["S1"]),
            ("非线性作用会引发安全隐患。", ["S1"]),
        ],
    ))
    result = engine.answer(
        "工程风险的技术因素有哪些？",
        qa_mode=QA_MODE_HYBRID,
        provider="deepseek",
        allow_api=True,
    )
    assert result.status == STATUS_OK
    assert result.qa_mode == QA_MODE_HYBRID
    assert result.evidence_source == "strict"
    assert result.general_knowledge is False
    assert result.citations and result.citations[0].page.page_number == 8
    assert fake.calls == 1


def test_hybrid_falls_back_to_expanded_before_general():
    engine, fake = _engine(_corpus(), content=structured_answer(
        "工程风险需要控制在可接受范围内，并制定预警和应急预案。",
        [
            ("分析风险可接受性。", ["S1"]),
            ("界定安全等级。", ["S1"]),
            ("制定预警机制和应急预案。", ["S1"]),
        ],
    ))
    result = engine.answer(
        "工程风险的可接受性如何控制？",
        qa_mode=QA_MODE_HYBRID,
        provider="deepseek",
        allow_api=True,
    )
    assert result.status == STATUS_OK
    assert result.evidence_source == "expanded"
    assert result.general_knowledge is False
    assert result.citations and result.citations[0].page.page_number == 32
    assert result.citations[0].evidence_status == "unreviewed"
    assert any("未审核" in warning for warning in result.warnings)
    assert fake.calls == 1


def test_hybrid_combines_strict_and_expanded_pages_for_relationship_question():
    content = structured_answer(
        "环境工程中的安全与社会公正是相互关联的：安全是首要责任，"
        "社会公正要求资源公平分配。",
        [
            ("环境工程安全包括生产安全、公共安全和环境生态安全。", ["S3"]),
            ("环境公正应做到公平分配社会资源，分配不公会造成社会断裂。", ["S1"]),
            ("环境工程中的社会公正涉及资源和利益的分配。", ["S2"]),
        ],
        conclusion="安全与公正是相互关联的，应同时考虑。",
    )
    engine, fake = _engine(_env_corpus(), content=content)
    result = engine.answer(
        "环境工程中的安全与社会公正有什么关系？",
        qa_mode=QA_MODE_HYBRID,
        provider="deepseek",
        allow_api=True,
    )
    assert result.status == STATUS_OK
    assert result.evidence_source == "expanded"
    assert result.general_knowledge is False
    assert result.citations
    assert {hit.page.page_number for hit in result.citations} == {28, 33, 34}
    assert any(hit.evidence_status == "unreviewed" for hit in result.citations)
    assert any("未审核" in warning for warning in result.warnings)
    assert fake.calls == 1


def test_hybrid_renders_structured_exam_answer_and_supported_summary():
    content = structured_answer(
        "环境工程中的安全与社会公正是相互关联的：安全是首要责任，社会公正要求资源公平分配。",
        [
            ("环境工程安全包括生产安全、公共安全和环境生态安全。", ["S3"]),
            ("环境工程中的社会公正涉及资源和利益的分配。", ["S2"]),
            ("环境公正应做到公平分配社会资源，分配不公会造成社会断裂。", ["S1"]),
        ],
        conclusion="安全与公正是相互关联的，应同时考虑。",
    )
    engine, fake = _engine(_env_corpus(), content=content)
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
    assert "【简明答案】" in result.answer
    assert "【分点论述】" in result.answer
    assert "【总结】" in result.answer
    assert "【参考依据】" in result.answer
    assert "[S3]" in result.answer and "[S1]" in result.answer and "[S2]" in result.answer
    assert "环境.pdf" in result.answer
    assert result.citations


def test_courseware_prompt_requires_citations_and_exam_structure():
    engine, fake = _engine(_corpus(), content=structured_answer(
        "工程风险的技术因素包括零部件老化、控制系统失灵和非线性作用。",
        [("工程风险的技术因素包括零部件老化、控制系统失灵和非线性作用。", ["S1"])],
    ))
    result = engine.answer(
        "工程风险的技术因素有哪些？",
        qa_mode=QA_MODE_HYBRID,
        provider="deepseek",
        allow_api=True,
    )
    assert result.status == STATUS_OK
    system_prompt = fake.last_messages[0]['content']
    assert "只输出一个 JSON 对象" in system_prompt
    assert "每个事实性论述和每个编号列表项" in system_prompt
    assert "citations" in system_prompt
    assert "不要长篇复制课件原文" in system_prompt


def test_hybrid_uses_general_knowledge_only_after_courseware_gap():
    engine, fake = _engine(_corpus(), content=GENERAL)
    result = engine.answer(
        "功利主义与义务论在工程伦理中的区别是什么？",
        qa_mode=QA_MODE_HYBRID,
        provider="deepseek",
        allow_api=True,
    )
    assert result.status == STATUS_OK
    assert result.qa_mode == QA_MODE_HYBRID
    assert result.evidence_source == "general"
    assert result.general_knowledge is True
    assert result.citations == ()
    assert "AI 通用知识补充" in result.answer
    assert "[S1]" not in result.answer
    assert fake.calls == 1


def test_general_mode_uses_no_courseware_and_sanitizes_fake_citations():
    engine, fake = _engine(
        _corpus(),
        content=(
            "【简明答案】\n功利主义看后果，义务论看规则。 [S1]\n\n"
            "【分点说明】\n1. 功利主义强调最大幸福。\n\n"
            "【参考依据】\n- 见《工程伦理.pdf》第 8 页。"
        ),
    )
    result = engine.answer(
        "功利主义与义务论在工程伦理中的区别是什么？",
        qa_mode=QA_MODE_GENERAL,
        provider="deepseek",
        allow_api=True,
    )
    assert result.status == STATUS_OK
    assert result.qa_mode == QA_MODE_GENERAL
    assert result.general_knowledge is True
    assert result.evidence_source == "general"
    assert result.citations == ()
    assert "[S1]" not in result.answer
    assert ".pdf" not in result.answer.lower()
    assert "第 8 页" not in result.answer
    assert "AI 通用知识补充，未经课件核实" in result.answer
    assert fake.calls == 1


def test_general_mode_formats_plain_model_text():
    engine, fake = _engine(
        _corpus(),
        content="功利主义关注后果，义务论关注规则。两者在工程决策中可能冲突。",
    )
    result = engine.answer(
        "功利主义与义务论在工程伦理中的区别是什么？",
        qa_mode=QA_MODE_GENERAL,
        provider="deepseek",
        allow_api=True,
    )
    assert result.status == STATUS_OK
    assert "【简明答案】" in result.answer
    assert "【分点说明】" in result.answer
    assert "【参考依据】" in result.answer


def test_hybrid_citation_rejection_does_not_silently_switch_to_general():
    engine, fake = _engine(
        _corpus(),
        content=structured_answer(
            "工程风险的技术因素包括公开所有客户记录。",
            [("工程风险的技术因素包括公开所有客户记录。", ["S1"])],
        ),
    )
    result = engine.answer(
        "工程风险的技术因素有哪些？",
        qa_mode=QA_MODE_HYBRID,
        provider="deepseek",
        allow_api=True,
    )
    assert fake.calls == 1
    assert result.qa_mode == QA_MODE_HYBRID
    assert result.general_knowledge is False
    assert result.provider == "deepseek"
    assert result.verification_status == "unverified"
    assert result.api_outcome == "unverified"
    assert result.model_calls == 1
    assert "公开所有客户记录" in result.answer
    assert result.verification_status == "unverified"
    assert result.verification_errors
    assert result.citations == ()
    assert "AI 通用知识补充" not in result.answer


def test_hybrid_gate_closed_returns_insufficient_not_general():
    engine, fake = _engine(_corpus())
    result = engine.answer(
        "功利主义与义务论在工程伦理中的区别是什么？",
        qa_mode=QA_MODE_HYBRID,
        provider="auto",
        allow_api=False,
    )
    assert result.status == STATUS_INSUFFICIENT
    assert result.general_knowledge is False
    assert result.provider == "none"
    assert fake.calls == 0
    assert any("无法使用 AI 通用知识" in warning for warning in result.warnings)


def test_general_mode_master_switch_false_never_sends(tmp_path):
    config = Settings(
        deepseek_api_key="synthetic-general-gate",
        api_enabled=False,
        api_state_path=tmp_path / "ledger.sqlite3",
    )
    session = FakeSession()
    client = DeepSeekClient(config, session=session)
    engine = AnswerEngine(Retriever(_corpus()), settings=config, client=client)
    result = engine.answer(
        "功利主义与义务论在工程伦理中的区别是什么？",
        qa_mode=QA_MODE_GENERAL,
        provider="deepseek",
        allow_api=True,
    )
    assert result.status == STATUS_ERROR
    assert result.api_attempted is False
    assert result.api_outcome != "accepted"
    assert not session.calls


def test_general_mode_missing_key_never_sends(tmp_path):
    config = Settings(
        deepseek_api_key=None,
        api_enabled=True,
        api_state_path=tmp_path / "ledger.sqlite3",
    )
    session = FakeSession()
    client = DeepSeekClient(config, session=session)
    engine = AnswerEngine(Retriever(_corpus()), settings=config, client=client)
    result = engine.answer(
        "功利主义与义务论在工程伦理中的区别是什么？",
        qa_mode=QA_MODE_GENERAL,
        provider="deepseek",
        allow_api=True,
    )
    assert result.status == STATUS_ERROR
    assert result.api_attempted is False
    assert result.api_outcome == "not_authorized"
    assert not session.calls


def test_general_mode_budget_zero_never_sends(tmp_path):
    config = Settings(
        deepseek_api_key="synthetic-general-budget",
        api_enabled=True,
        daily_budget_cny=0,
        api_state_path=tmp_path / "ledger.sqlite3",
    )
    session = FakeSession()
    client = DeepSeekClient(config, session=session)
    engine = AnswerEngine(Retriever(_corpus()), settings=config, client=client)
    result = engine.answer(
        "功利主义与义务论在工程伦理中的区别是什么？",
        qa_mode=QA_MODE_GENERAL,
        provider="deepseek",
        allow_api=True,
    )
    assert result.status == STATUS_ERROR
    assert result.api_attempted is False
    assert result.api_outcome == "budget_exhausted"
    assert not session.calls
