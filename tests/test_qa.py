from __future__ import annotations

from src.config import Settings
from src.deepseek_client import ChatResult, DeepSeekError
from src.qa import (
    PROVIDER_AUTO,
    PROVIDER_DEEPSEEK,
    PROVIDER_LOCAL,
    STATUS_INSUFFICIENT,
    STATUS_OK,
    AnswerEngine,
)
from src.retriever import MODE_EXPANDED, MODE_STRICT, Retriever
from tests.helpers import make_corpus, make_page, structured_answer


class FakeClient:
    def __init__(self, *, content: str | None = None, error: Exception | None = None):
        if content is None:
            content = structured_answer(
                "工程风险包括技术因素。",
                [("工程风险包括技术因素。", ["S1"])],
            )
        self.configured = True
        self.content = content
        self.error = error
        self.calls = 0
        self.last_messages = None

    def chat(self, messages, **kwargs):
        self.calls += 1
        self.last_messages = messages
        if self.error is not None:
            raise self.error
        return ChatResult(content=self.content, model="deepseek-chat", usage={"total_tokens": 10})


def _risk_corpus():
    return make_corpus(
        make_page(
            "2.2.1 工程风险的来源\n"
            "1、工程风险的技术因素\n"
            "1）工程中零部件老化，导致系统功能失调，从而引发事故风险。\n"
            "2）控制系统失灵，存在引发事故的隐患。\n"
            "3）非线性作用会引发安全隐患。",
            category="A",
            page_number=8,
            filename="风险课件.pdf",
        ),
        make_page(
            "工程风险的技术因素还包括人为因素和管理因素。",
            category=None,
            page_number=14,
            filename="未审核风险课件.pdf",
        ),
    )


def _engine(corpus, *, settings=None, client=None):
    return AnswerEngine(
        Retriever(corpus),
        settings=settings or Settings(deepseek_api_key=None),
        client=client,
    )


def test_local_answer_has_citation_and_source_page():
    answer = _engine(_risk_corpus()).answer(
        "工程风险的技术因素有哪些？",
        mode=MODE_STRICT,
        provider=PROVIDER_LOCAL,
    )
    assert answer.status == STATUS_OK
    assert answer.provider == PROVIDER_LOCAL
    assert "[S1]" in answer.answer
    assert answer.citations
    assert answer.citations[0].page.filename == "风险课件.pdf"
    assert answer.citations[0].page.page_number == 8
    assert "零部件老化" in answer.answer


def test_local_enumeration_answer_keeps_all_items():
    corpus = make_corpus(
        make_page(
            "具体到工程实践情境，包含以下五种“回避”利益冲突的方式：\n"
            "①拒绝，比如拒收卖主的礼物；\n"
            "②放弃，比如出售股份；\n"
            "③离职，比如辞去职务；\n"
            "④不参与其中；\n"
            "⑤披露利益冲突。\n"
            "回避利益冲突的方法就是放弃产生冲突的利益。",
            category="A",
            page_number=68,
        )
    )
    answer = _engine(corpus).answer(
        "工程师如何回避利益冲突？",
        mode=MODE_STRICT,
        provider=PROVIDER_LOCAL,
    )
    assert answer.status == STATUS_OK
    for marker in "①②③④⑤":
        assert marker in answer.answer


def test_insufficient_when_no_evidence():
    answer = _engine(_risk_corpus()).answer(
        "量子计算如何实现？",
        mode=MODE_STRICT,
        provider=PROVIDER_LOCAL,
    )
    assert answer.status == STATUS_INSUFFICIENT
    assert "资料不足" in answer.answer
    assert answer.citations == ()


def test_definition_without_direct_definition_is_insufficient():
    corpus = make_corpus(
        make_page(
            "工程伦理规范是指工程师面对伦理问题时应遵循的行为准则。",
            category="A",
            page_number=1,
        )
    )
    answer = _engine(corpus).answer(
        "什么是工程伦理？",
        mode=MODE_STRICT,
        provider=PROVIDER_LOCAL,
    )
    assert answer.status == STATUS_INSUFFICIENT
    assert "直接定义" in answer.answer


def test_expanded_direct_definition_is_answered_with_warning():
    corpus = make_corpus(
        make_page(
            "工程伦理规范是指工程师面对伦理问题时应遵循的行为准则。",
            category="A",
            page_number=1,
        ),
        make_page(
            "工程伦理是一种职业伦理，关注工程师对公众的责任。",
            category=None,
            page_number=26,
            filename="未审核课件.pdf",
        ),
    )
    answer = _engine(corpus).answer(
        "什么是工程伦理？",
        mode=MODE_EXPANDED,
        provider=PROVIDER_LOCAL,
    )
    assert answer.status == STATUS_OK
    assert answer.citations
    assert answer.citations[0].page.page_number == 26
    assert answer.warnings
    assert "未审核" in answer.warnings[0]


def test_expanded_answer_marks_unreviewed_evidence():
    corpus = make_corpus(
        make_page("工程风险的一般介绍。", category="A", page_number=1),
        make_page("工程风险的技术因素包括人为因素。", category=None, page_number=2),
    )
    answer = _engine(corpus).answer(
        "工程风险的技术因素",
        mode=MODE_EXPANDED,
        provider=PROVIDER_LOCAL,
    )
    assert answer.status == STATUS_OK
    assert answer.citations
    assert answer.citations[0].evidence_status == "unreviewed"
    assert "未审核" in answer.warnings[0]


def test_api_not_called_without_explicit_permission():
    fake = FakeClient()
    engine = _engine(
        _risk_corpus(),
        settings=Settings(deepseek_api_key="sk-test"),
        client=fake,
    )
    answer = engine.answer(
        "工程风险的技术因素有哪些？",
        mode=MODE_STRICT,
        provider=PROVIDER_AUTO,
        allow_api=False,
    )
    assert fake.calls == 0
    assert answer.provider == PROVIDER_LOCAL
    assert any("未授权" in warning for warning in answer.warnings)


def test_api_called_with_explicit_permission():
    fake = FakeClient(content=structured_answer(
        "控制系统失灵会带来事故隐患。",
        [("控制系统失灵，存在引发事故的隐患。", ["S1"])],
    ))
    engine = _engine(
        _risk_corpus(),
        settings=Settings(deepseek_api_key="sk-test"),
        client=fake,
    )
    answer = engine.answer(
        "工程风险的技术因素有哪些？",
        mode=MODE_STRICT,
        provider=PROVIDER_AUTO,
        allow_api=True,
    )
    assert fake.calls == 1
    assert answer.provider == PROVIDER_DEEPSEEK
    assert answer.status == STATUS_OK
    assert "[S1]" in answer.answer
    assert answer.model == "deepseek-chat"


def test_api_failure_falls_back_to_local_extract():
    fake = FakeClient(error=DeepSeekError("timeout"))
    engine = _engine(
        _risk_corpus(),
        settings=Settings(deepseek_api_key="sk-test"),
        client=fake,
    )
    answer = engine.answer(
        "工程风险的技术因素有哪些？",
        mode=MODE_STRICT,
        provider=PROVIDER_DEEPSEEK,
        allow_api=True,
    )
    assert answer.provider == PROVIDER_LOCAL
    assert any("回退" in warning for warning in answer.warnings)
    assert "零部件老化" in answer.answer


def test_api_invalid_citation_is_warned():
    fake = FakeClient(content=structured_answer(
        "工程风险包括技术因素。",
        [("工程风险包括技术因素。", ["S9"])],
    ))
    engine = _engine(
        _risk_corpus(),
        settings=Settings(deepseek_api_key="sk-test"),
        client=fake,
    )
    answer = engine.answer(
        "工程风险的技术因素有哪些？",
        mode=MODE_STRICT,
        provider=PROVIDER_DEEPSEEK,
        allow_api=True,
    )
    assert any("不存在的证据编号" in warning for warning in answer.warnings)
    assert answer.provider == PROVIDER_DEEPSEEK
    assert answer.verification_status == "unverified"
    assert answer.citations == ()
    assert answer.verification_status == "unverified"
    assert answer.verification_errors
    assert "[S9]" not in answer.answer


def test_api_says_insufficient_sets_status():
    fake = FakeClient(content="资料不足：课件没有给出该问题的直接依据。")
    engine = _engine(
        _risk_corpus(),
        settings=Settings(deepseek_api_key="sk-test"),
        client=fake,
    )
    answer = engine.answer(
        "工程风险的技术因素有哪些？",
        mode=MODE_STRICT,
        provider=PROVIDER_DEEPSEEK,
        allow_api=True,
    )
    assert answer.status == STATUS_INSUFFICIENT


def test_local_provider_never_calls_api():
    fake = FakeClient()
    engine = _engine(
        _risk_corpus(),
        settings=Settings(deepseek_api_key="sk-test"),
        client=fake,
    )
    answer = engine.answer(
        "工程风险的技术因素有哪些？",
        mode=MODE_STRICT,
        provider=PROVIDER_LOCAL,
        allow_api=True,
    )
    assert fake.calls == 0
    assert answer.provider == PROVIDER_LOCAL
