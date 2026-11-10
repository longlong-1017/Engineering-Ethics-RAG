"""三态验收：VERIFIED / UNVERIFIED / FAILED。"""
from __future__ import annotations

from src.config import Settings
from src.deepseek_client import DeepSeekError
from src.qa import (
    QA_MODE_GENERAL,
    QA_MODE_HYBRID,
    STATUS_INSUFFICIENT,
    STATUS_OK,
    AnswerEngine,
    VERIFICATION_FAILED,
    VERIFICATION_UNVERIFIED,
    VERIFICATION_VERIFIED,
)
from src.retriever import Retriever
from tests.helpers import make_corpus, make_page, structured_answer
from tests.test_qa import FakeClient


def _page():
    return make_page(
        "环境工程中的安全与社会公正\n"
        "1、环境工程中的安全\n环境工程安全包括生产安全、公共安全和环境生态安全。\n"
        "2、环境工程中的社会公正\n环境公正应做到公平分配社会资源，分配不公会造成社会断裂。",
        category="A", page_number=28, filename="环境.pdf",
    )


def _engine(content, *, error=None):
    fake = FakeClient(content=content, error=error)
    engine = AnswerEngine(
        Retriever(make_corpus(_page())),
        settings=Settings(deepseek_api_key="synthetic-state-key", api_enabled=True),
        client=fake,
    )
    return engine, fake


def _ask(engine, allow=True, qa_mode=QA_MODE_HYBRID):
    return engine.answer(
        "环境工程中的安全与社会公正有什么关系？",
        qa_mode=qa_mode,
        provider="deepseek",
        allow_api=allow,
    )


def test_verified_state_has_real_citations_and_sections():
    content = structured_answer(
        "环境工程中的安全与社会公正是相互关联的。",
        [("环境工程安全包括生产安全、公共安全和环境生态安全。", ["S1"]),
         ("环境公正应做到公平分配社会资源。", ["S1"])],
    )
    engine, fake = _engine(content)
    result = _ask(engine)
    assert fake.calls == 1
    assert result.status == STATUS_OK
    assert result.verification_status == VERIFICATION_VERIFIED
    assert result.provider == "deepseek"
    assert result.citations
    assert "【简明答案】" in result.answer
    assert "【参考依据】" in result.answer
    assert result.verification_errors == ()


def test_fact_failure_keeps_unverified_draft_without_verified_citations():
    content = structured_answer(
        "环境工程中的安全与社会公正是相互关联的。",
        [("环境工程安全包括生产安全。", ["S1"]),
         ("事故造成999人死亡。", ["S1"])],
    )
    engine, fake = _engine(content)
    result = _ask(engine)
    assert fake.calls == 1
    assert result.status == STATUS_OK
    assert result.provider == "deepseek"
    assert result.verification_status == VERIFICATION_UNVERIFIED
    assert result.citations == ()
    assert result.verification_status == "unverified"
    assert result.verification_errors
    assert "【未通过严格校验的原因】" not in result.answer
    assert "999" in result.answer  # 保留 AI 原文，但明确未核验
    assert any("999" in error for error in result.verification_errors)
    assert result.search.hits


def test_invalid_reference_is_unverified_not_verified():
    content = structured_answer("", [("环境工程安全包括生产安全。", ["S99"])])
    engine, fake = _engine(content)
    result = _ask(engine)
    assert fake.calls == 1
    assert result.verification_status == VERIFICATION_UNVERIFIED
    assert result.provider == "deepseek"
    assert result.citations == ()
    assert any("S99" in error for error in result.verification_errors)


def test_unparseable_response_is_failed_and_uses_local_excerpt():
    engine, fake = _engine("这不是 JSON，但带有 [S1]")
    result = _ask(engine)
    assert fake.calls == 1
    assert result.verification_status == VERIFICATION_FAILED
    assert result.provider == "local"
    assert result.api_outcome == "unparseable"
    assert "资料不足" not in result.answer or "根据" in result.answer
    assert "JSON" in result.api_reason


def test_api_error_is_failed_and_uses_local_excerpt():
    engine, fake = _engine(None, error=DeepSeekError("timeout", code="timeout", attempted=True))
    result = _ask(engine)
    assert fake.calls == 1
    assert result.verification_status == VERIFICATION_FAILED
    assert result.provider == "local"
    assert result.api_outcome == "timeout"
    assert "本次曾尝试 API" in result.answer


def test_general_knowledge_is_marked_unverified():
    engine, fake = _engine(
        "【简明答案】\n通用知识回答。\n\n【分点说明】\n1. 说明。\n\n【参考依据】\n- AI 通用知识补充，未经课件核实。"
    )
    result = _ask(engine, qa_mode=QA_MODE_GENERAL)
    assert fake.calls == 1
    assert result.verification_status == VERIFICATION_UNVERIFIED
    assert result.general_knowledge is True
    assert result.citations == ()
    assert "AI 通用知识补充" in result.answer
