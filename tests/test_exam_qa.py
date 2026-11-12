"""第四阶段考试问答模式回归：混合/本地/无证据回退，不调用真实 API。"""
from __future__ import annotations

from src.config import Settings
from src.qa import (
    QA_MODE_HYBRID,
    QA_MODE_LOCAL,
    STATUS_OK,
    AnswerEngine,
)
from src.retriever import Retriever
from tests.helpers import make_corpus, make_page, structured_answer
from tests.test_qa import FakeClient


def _engine(pages, content):
    fake = FakeClient(content=content)
    engine = AnswerEngine(
        Retriever(make_corpus(*pages)),
        settings=Settings(deepseek_api_key="synthetic-exam-mode", api_enabled=True),
        client=fake,
    )
    return engine, fake


def test_local_mode_never_calls_deepseek_and_returns_courseware():
    page = make_page(
        "工程风险的技术因素\n1）零部件老化导致功能失调。\n2）控制系统失灵。",
        category="A", page_number=8,
    )
    engine, fake = _engine([page], structured_answer("不应被使用。", [("不应被使用。", ["S1"])]))
    result = engine.answer(
        "工程风险的技术因素有哪些？",
        qa_mode=QA_MODE_LOCAL,
        provider="auto",
        allow_api=True,
    )
    assert fake.calls == 0
    assert result.provider == "local"
    assert result.qa_mode == QA_MODE_LOCAL
    assert result.status == STATUS_OK
    assert result.citations
    assert "零部件老化" in result.answer


def test_hybrid_without_enough_courseware_passes_partial_material_to_general():
    page = make_page("工程风险的一般介绍。", category="A", page_number=1)
    fake_content = (
        "【简明答案】\n工程风险需要从通用伦理角度分析。\n\n"
        "【分点说明】\n1. 需要识别风险来源。\n\n"
        "【参考依据】\n- AI 通用知识补充，未经课件核实。"
    )
    engine, fake = _engine([page], fake_content)
    result = engine.answer(
        "工程风险的技术因素有哪些？",
        qa_mode=QA_MODE_HYBRID,
        provider="deepseek",
        allow_api=True,
    )
    assert fake.calls == 1
    user_prompt = fake.last_messages[1]["content"]
    assert "本地检索到以下部分相关片段" in user_prompt
    assert result.general_knowledge is True
    assert result.citations == ()
    assert any("部分相关材料" in warning for warning in result.warnings)


def test_no_local_material_still_allows_hybrid_general_answer():
    page = make_page("完全无关的课程介绍。", category="A", page_number=1)
    fake_content = (
        "【简明答案】\n通用回答。\n\n【分点说明】\n1. 通用说明。\n\n"
        "【参考依据】\n- AI 通用知识补充，未经课件核实。"
    )
    engine, fake = _engine([page], fake_content)
    result = engine.answer(
        "量子纠缠工程伦理跃迁定律是什么？",
        qa_mode=QA_MODE_HYBRID,
        provider="deepseek",
        allow_api=True,
    )
    assert fake.calls == 1
    assert result.general_knowledge is True
    assert result.citations == ()
    assert "本次不提供课件证据" in fake.last_messages[1]["content"]


def test_local_materials_adapter_exposes_ppt_and_textbook_without_rebuilding():
    from src.exam_materials import LocalMaterialsRetriever
    from src.versioned_corpus import load_versions, load_version_indexes, VersionedRetriever

    old, new = load_versions()
    base = VersionedRetriever(old, new, indexes=load_version_indexes(old, new))
    retriever = LocalMaterialsRetriever.load(base)
    response = retriever.search("工程风险的技术因素有哪些？", mode="expanded", top_k=6)
    versions = {hit.page.dataset_version for hit in response.hits}
    assert "old" in versions
    assert "textbook" in versions
    assert response.hits[0].page.dataset_version in {"old", "exam_2026"}
    assert any(hit.page.review_label for hit in response.hits)
