"""引用校验与 Mock API 的归纳/多页/数字/案例回归。不联网。"""
from types import SimpleNamespace

from src.citations import validate_citations
from src.config import Settings
from src.qa import AnswerEngine
from src.retriever import Retriever
from tests.helpers import make_corpus, make_page
from tests.test_qa import FakeClient
from tests.helpers import structured_answer


def _hit(rank=1):
    return SimpleNamespace(rank=rank)


def _engine(pages, content):
    fake = FakeClient(content=content)
    engine = AnswerEngine(
        Retriever(make_corpus(*pages)),
        settings=Settings(deepseek_api_key='synthetic-citation-key', api_enabled=True),
        client=fake,
    )
    return engine, fake


def test_valid_paraphrase_is_accepted_not_required_verbatim():
    evidence = (
        "工程风险的技术因素包括：1）零部件老化导致系统功能失调，引发事故风险；"
        "2）控制系统失灵，存在引发事故的隐患；3）非线性作用会引发安全隐患。"
    )
    answer = (
        "工程风险的技术因素主要有三类：零部件老化会造成功能失调，"
        "控制系统失灵会带来隐患，非线性作用也会引发安全风险。 [S1]"
    )
    result = validate_citations(
        "工程风险的技术因素有哪些？", answer, [(_hit(1), evidence)]
    )
    assert result.ok
    assert result.citations == (1,)


def test_heavy_but_accurate_paraphrase_is_accepted():
    evidence = (
        "工程风险的技术因素包括：1）零部件老化导致系统功能失调，引发事故风险；"
        "2）控制系统失灵，存在引发事故的隐患；3）非线性作用会引发安全隐患。"
    )
    answer = (
        "工程风险的技术来源主要包括三类：第一是设备老化造成的功能失效，"
        "第二是控制系统故障带来的隐患，第三是非线性效应。 [S1]"
    )
    result = validate_citations(
        "工程风险的技术因素有哪些？", answer, [(_hit(1), evidence)]
    )
    assert result.ok


def test_unsupported_source_and_uncited_claim_are_rejected():
    evidence = "数据保管包括加密客户记录。必须限制访问权限，并定期审计访问日志。"
    unsupported = validate_citations(
        "数据保管包括哪些？",
        "允许公开所有客户信息。 [S1]",
        [(_hit(1), evidence)],
    )
    assert not unsupported.ok
    assert any("关键词" in error or "重合" in error for error in unsupported.errors)

    uncited = validate_citations(
        "数据保管包括哪些？",
        "数据保管包括加密客户记录。 [S1] 还可以出售客户记录。",
        [(_hit(1), evidence)],
    )
    assert not uncited.ok
    assert any("缺少 [S#]" in error for error in uncited.errors)


def test_missing_and_nonexistent_citations_are_rejected():
    evidence = "数据保管包括加密客户记录。"
    missing = validate_citations("数据保管包括哪些？", "数据保管包括加密客户记录。", [(_hit(1), evidence)])
    assert not missing.ok and any("未包含任何" in error for error in missing.errors)

    nonexistent = validate_citations(
        "数据保管包括哪些？", "数据保管包括加密客户记录。 [S9]", [(_hit(1), evidence)]
    )
    assert not nonexistent.ok
    assert any("不存在的证据编号" in error and "S9" in error for error in nonexistent.errors)


def test_multi_page_citation_requires_each_page_to_contribute():
    p1 = "工程风险的技术因素包括零部件老化和控制系统失灵。"
    p2 = "工程风险的人为因素包括施工质量和操作人员风险意识。"
    evidence = [(_hit(1), p1), (_hit(2), p2)]

    valid = validate_citations(
        "工程风险包括哪些因素？",
        "工程风险包括技术因素和人为因素。 [S1][S2]",
        evidence,
    )
    assert valid.ok and valid.citations == (1, 2)

    extraneous = validate_citations(
        "工程风险包括哪些因素？",
        "工程风险的技术因素包括零部件老化。 [S1][S2]",
        evidence,
    )
    assert not extraneous.ok
    assert any("S2" in error and "无实质重合" in error for error in extraneous.errors)


def test_number_must_match_cited_evidence_exactly():
    source = "南沙港事故造成12人死亡、35人受伤，直接经济损失为2.75亿元。"
    ok = validate_citations(
        "南沙港事故的伤亡和经济损失是多少？",
        "事故造成12人死亡、35人受伤，直接经济损失约2.75亿元。 [S1]",
        [(_hit(1), source)],
    )
    assert ok.ok

    bad = validate_citations(
        "南沙港事故的伤亡和经济损失是多少？",
        "事故造成60人死亡、100人受伤，直接经济损失9.75亿元。 [S1]",
        [(_hit(1), source)],
    )
    assert not bad.ok
    assert any("数字未在所引证据出现" in error for error in bad.errors)


def test_fullwidth_citation_is_normalized_to_stable_format():
    result = validate_citations(
        "数据保管包括哪些？",
        "数据保管包括加密客户记录。【S1】",
        [(_hit(1), "数据保管包括加密客户记录。")],
    )
    assert result.ok
    assert "[S1]" in result.normalized_content
    assert "【" not in result.normalized_content


def test_mock_api_accepts_numeric_paraphrase():
    page = make_page(
        "南沙港事故\n2021年造成12人死亡、35人受伤，直接经济损失为2.75亿元。",
        category='A', page_number=37,
    )
    engine, fake = _engine(
        [page],
        structured_answer(
            "",
            [("事故造成12人死亡、35人受伤，直接经济损失约2.75亿元。", ["S1"])],
        ),
    )
    result = engine.answer(
        "南沙港事故的伤亡和经济损失是多少？", provider='deepseek', allow_api=True
    )
    assert fake.calls == 1
    assert result.provider == 'deepseek' and result.status == 'ok'
    assert '2.75亿元' in result.answer
    assert result.citations[0].page.page_number == 37


def test_mock_api_accepts_short_answer_paraphrase():
    page = make_page(
        "2.保持多方信任以应对利益冲突\n"
        "具体到工程实践情境，包含以下五种“回避”利益冲突的方式：\n"
        "①拒绝；②放弃；③离职；④不参与；⑤披露。",
        category='A', page_number=68,
    )
    engine, fake = _engine(
        [page],
        structured_answer(
            "",
            [("回避利益冲突的方式包括拒绝、放弃、离职、不参与和披露。", ["S1"])],
        ),
    )
    result = engine.answer(
        "工程师回避利益冲突的五种方式是什么？", provider='deepseek', allow_api=True
    )
    assert fake.calls == 1
    assert result.provider == 'deepseek'
    for item in "拒绝 放弃 离职 不参与 披露".split():
        assert item in result.answer


def test_mock_api_accepts_case_analysis_paraphrase():
    page = make_page(
        "挑战者号事故\n1986年1月28日，在佛罗里达肯尼迪航天中心，"
        "挑战者号航天飞机爆炸解体，7名宇航员殉职。",
        category='A', page_number=7,
    )
    engine, _ = _engine(
        [page],
        structured_answer(
            "",
            [("1986年1月28日，挑战者号在佛罗里达肯尼迪航天中心爆炸解体，7名宇航员殉职。", ["S1"])],
        ),
    )
    result = engine.answer(
        "挑战者号事故的时间、地点和后果是什么？", provider='deepseek', allow_api=True
    )
    assert result.provider == 'deepseek'
    assert "1986年1月28日" in result.answer and "7名宇航员" in result.answer
    assert result.citations[0].page.page_number == 7


def test_mock_api_accepts_multi_page_citation():
    pages = [
        make_page(
            "南沙港事故\n时间：2021年5月1日\n地点：南沙港三号泊位",
            category='A', page_number=1, filename='合成事故.pdf',
        ),
        make_page(
            "南沙港事故\n后果：造成12人死亡、35人受伤，直接经济损失2.75亿元。",
            category='A', page_number=2, filename='合成事故.pdf',
        ),
    ]
    engine, _ = _engine(
        pages,
        structured_answer(
            "",
            [("2021年5月1日，事故发生在南沙港三号泊位，造成12人死亡、35人受伤，直接经济损失2.75亿元。", ["S1", "S2"])],
        ),
    )
    result = engine.answer(
        "南沙港事故的时间、地点和后果是什么？", provider='deepseek', allow_api=True
    )
    assert result.provider == 'deepseek'
    assert {hit.page.page_number for hit in result.citations} == {1, 2}


def test_invalid_mock_citation_falls_back_with_specific_reason():
    page = make_page(
        "工程风险的技术因素包括零部件老化、控制系统失灵和非线性作用。",
        category='A', page_number=8,
    )
    engine, fake = _engine(
        [page],
        structured_answer(
            "",
            [
                ("工程风险包括技术因素。", ["S1"]),
                ("还可以忽略所有风险。", ["S1"]),
            ],
        ),
    )
    result = engine.answer(
        "工程风险的技术因素有哪些？", provider='deepseek', allow_api=True
    )
    assert fake.calls == 1
    assert result.provider == 'deepseek'
    assert result.verification_status == 'unverified'
    assert result.api_outcome == 'unverified'
    assert ('未支持' in result.api_reason or '结构化' in result.api_reason)
    assert '忽略所有风险' in result.answer
    assert result.verification_status == "unverified"
    assert result.verification_errors
    assert result.citations == ()


def test_nonexistent_mock_citation_falls_back_with_specific_reason():
    page = make_page(
        "数据保管包括加密客户记录。必须限制访问权限，并定期审计访问日志。",
        category='A', page_number=1,
    )
    engine, _ = _engine([page], structured_answer(
        "",
        [("数据保管包括加密客户记录。", ["S9"])],
    ))
    result = engine.answer(
        "数据保管包括哪些？", provider='deepseek', allow_api=True
    )
    assert result.provider == 'deepseek'
    assert result.verification_status == 'unverified'
    assert result.api_outcome == 'unverified'
    assert '不存在的证据编号' in result.api_reason
    assert '[S9]' not in result.answer
    assert result.verification_status == "unverified"
    assert result.verification_errors
    assert result.citations == ()


def test_prompt_declares_allowed_ids_and_paraphrase_permission():
    page = make_page(
        "工程风险的技术因素包括零部件老化、控制系统失灵和非线性作用。",
        category='A', page_number=8,
    )
    engine, fake = _engine(
        [page],
        structured_answer(
            "工程风险的技术因素包括零部件老化、控制系统失灵和非线性作用。",
            [("工程风险的技术因素包括零部件老化、控制系统失灵和非线性作用。", ["S1"])],
        ),
    )
    result = engine.answer(
        "工程风险的技术因素有哪些？", provider='deepseek', allow_api=True
    )
    assert result.provider == 'deepseek'
    user_prompt = fake.last_messages[1]['content']
    system_prompt = fake.last_messages[0]['content']
    assert '允许使用的证据编号仅限' in user_prompt
    assert '[S1]' in user_prompt
    assert '允许准确归纳' in user_prompt
    assert '不得添加证据中没有的事实' in system_prompt
    assert '只输出一个 JSON 对象' in system_prompt
    assert 'citations' in system_prompt


def test_guide_line_and_numbered_list_are_supported():
    page = make_page(
        "2.2.1 工程风险的来源\n"
        "1、工程风险的技术因素\n"
        "1）工程中零部件老化，导致系统功能失调，从而引发事故风险。\n"
        "2）控制系统失灵；现代工程高度复杂，存在引发事故的隐患。\n"
        "3）非线性作用会引发安全隐患。",
        category='A', page_number=8,
    )
    content = structured_answer(
        "工程风险的技术因素包括零部件老化、控制系统失灵和非线性作用。",
        [
            ("零部件老化会导致系统功能失调，从而引发事故风险。", ["S1"]),
            ("控制系统失灵会带来事故隐患。", ["S1"]),
            ("非线性作用会引发安全隐患。", ["S1"]),
        ],
    )
    engine, fake = _engine([page], content)
    result = engine.answer(
        "工程风险的技术因素有哪些？", provider='deepseek', allow_api=True
    )
    assert fake.calls == 1
    assert result.provider == 'deepseek' and result.status == 'ok'
    assert result.api_outcome == 'accepted'
    assert result.citations and result.citations[0].page.page_number == 8
    assert '缺少 [S#]' not in result.api_reason


def test_circled_and_fullwidth_list_prefixes_are_not_numbers():
    evidence = "回避方式包括拒绝、放弃、披露。"
    for prefix in ("①", "１."):
        result = validate_citations(
            "回避方式有哪些？",
            f"回避方式包括：\n{prefix}拒绝 [S1]",
            [(_hit(1), evidence)],
        )
        assert result.ok, (prefix, result.errors)


def test_unsupported_summary_relation_is_rejected():
    evidence = (
        "环境工程中的安全与社会公正\n"
        "环境工程安全包括生产安全、公共安全和环境生态安全。\n"
        "环境公正应做到公平分配社会资源。"
    )
    result = validate_citations(
        "环境工程中的安全与社会公正有什么关系？",
        "环境工程中的安全与社会公正是相互冲突的。\n"
        "1. 安全包括生产安全。 [S1]\n"
        "2. 社会公正要求公平分配资源。 [S1]",
        [(_hit(1), evidence)],
    )
    assert not result.ok
    assert any("冲突" in error or "未支持" in error for error in result.errors)


def test_conclusion_label_summary_is_pending_not_rejected():
    evidence = (
        "环境工程中的安全与社会公正\n"
        "环境工程安全包括生产安全、公共安全和环境生态安全。\n"
        "环境公正应做到公平分配社会资源，分配不公会造成社会断裂。"
    )
    result = validate_citations(
        "环境工程中的安全与社会公正有什么关系？",
        "结论：现有证据只分别界定了安全和社会公正，尚不能说明二者关系。\n"
        "1. 安全包括生产安全、公共安全和环境生态安全。 [S1]\n"
        "2. 社会公正应公平分配资源，分配不公会造成社会断裂。 [S1]",
        [(_hit(1), evidence)],
    )
    assert result.ok
    assert result.warnings
    assert any("待核实" in warning for warning in result.warnings)
    assert "结论：现有证据" in result.normalized_content


def test_pending_summary_with_fake_number_is_rejected():
    result = validate_citations(
        "环境工程中的安全与社会公正有什么关系？",
        "结论：事故造成999人死亡。\n"
        "1. 安全包括生产安全。 [S1]\n"
        "2. 社会公正应公平分配资源。 [S1]",
        [(_hit(1), "环境工程安全包括生产安全。环境公正应公平分配资源。")],
    )
    assert not result.ok
    assert any("数字未在所引证据出现" in error or "缺少 [S#]" in error for error in result.errors)


def test_pending_summary_with_unknown_entity_is_rejected():
    result = validate_citations(
        "环境工程中的安全与社会公正有什么关系？",
        "结论：三峡大坝工程证明安全与公正无关。\n"
        "1. 安全包括生产安全。 [S1]\n"
        "2. 社会公正应公平分配资源。 [S1]",
        [(_hit(1), "环境工程安全包括生产安全。环境公正应公平分配资源。")],
    )
    assert not result.ok
    assert any("未支持" in error or "缺少 [S#]" in error for error in result.errors)


def test_guide_line_without_colon_is_allowed():
    result = validate_citations(
        "工程风险的技术因素有哪些？",
        "工程风险的技术因素包括\n1. 零部件老化。[S1]",
        [(_hit(1), "工程风险的技术因素包括零部件老化。")],
    )
    assert result.ok


def test_numbered_guide_line_is_allowed():
    result = validate_citations(
        "工程风险的技术因素有哪些？",
        "1. 工程风险的技术因素包括：\n- 零部件老化。[S1]",
        [(_hit(1), "工程风险的技术因素包括零部件老化。")],
    )
    assert result.ok


def test_uncited_list_item_is_rejected():
    result = validate_citations(
        "工程风险的技术因素有哪些？",
        "工程风险的技术因素包括：\n1. 零部件老化。[S1]\n2. 控制系统失灵。",
        [(_hit(1), "工程风险的技术因素包括零部件老化；控制系统失灵。")],
    )
    assert not result.ok
    assert any('缺少 [S#]' in error for error in result.errors)


def test_leading_numbered_fact_without_citation_is_rejected():
    result = validate_citations(
        "工程风险的技术因素有哪些？",
        "事故造成12人死亡：\n1. 零部件老化。[S1]",
        [(_hit(1), "工程风险的技术因素包括零部件老化。")],
    )
    assert not result.ok
    assert any('缺少 [S#]' in error for error in result.errors)


def test_leading_causal_claim_without_citation_is_rejected():
    result = validate_citations(
        "工程风险的技术因素有哪些？",
        "工程风险会导致严重后果：\n1. 零部件老化。[S1]",
        [(_hit(1), "工程风险的技术因素包括零部件老化。")],
    )
    assert not result.ok
    assert any('缺少 [S#]' in error for error in result.errors)


def test_colon_ending_factual_claim_is_not_a_heading():
    result = validate_citations(
        "工程风险的技术因素有哪些？",
        "工程风险包括技术因素：\n1. 零部件老化。[S1]",
        [(_hit(1), "工程风险的技术因素包括零部件老化。")],
    )
    assert not result.ok
    assert any('缺少 [S#]' in error for error in result.errors)


def test_mock_api_ignores_trailing_citation_pointer():
    page = make_page(
        "2.2.1 工程风险的来源\n"
        "1、工程风险的技术因素\n"
        "1）工程中零部件老化，导致系统功能失调，从而引发事故风险。\n"
        "2）控制系统失灵；现代工程高度复杂，存在引发事故的隐患。\n"
        "3）非线性作用会引发安全隐患。",
        category='A', page_number=8,
    )
    content = structured_answer(
        "工程风险的技术因素包括零部件老化、控制系统失灵和非线性作用。",
        [
            ("零部件老化会导致系统功能失调，从而引发事故风险。", ["S1"]),
            ("控制系统失灵会带来事故隐患。", ["S1"]),
            ("非线性作用会引发安全隐患。", ["S1"]),
        ],
    )
    engine, _ = _engine([page], content)
    result = engine.answer(
        "工程风险的技术因素有哪些？", provider='deepseek', allow_api=True
    )
    assert result.provider == 'deepseek'
    assert result.api_outcome == 'accepted'
    assert result.citations and result.citations[0].page.page_number == 8


def test_non_factual_citation_pointer_lines_are_ignored():
    evidence = "工程风险的技术因素包括零部件老化、控制系统失灵和非线性作用。"
    base = (
        "工程风险的技术因素包括：\n"
        "1. 零部件老化。[S1]\n"
        "2. 控制系统失灵。[S1]\n"
        "3. 非线性作用。[S1]"
    )
    for pointer in ("依据：[S1]", "依据课件：[S1]", "根据资料 [S1]", "综上所述 [S1]"):
        result = validate_citations(
            "工程风险的技术因素有哪些？", base + "\n" + pointer,
            [(_hit(1), evidence)],
        )
        assert result.ok, (pointer, result.errors)


def test_connective_prefix_is_removed_before_fact_validation():
    evidence = "事故造成12人死亡、35人受伤，直接经济损失2.75亿元。"
    ok = validate_citations(
        "南沙港事故的伤亡和经济损失是多少？",
        "根据资料，事故造成12人死亡、35人受伤，直接经济损失2.75亿元。 [S1]",
        [(_hit(1), evidence)],
    )
    assert ok.ok

    bad = validate_citations(
        "南沙港事故的伤亡和经济损失是多少？",
        "根据资料，事故造成99人死亡、35人受伤，直接经济损失2.75亿元。 [S1]",
        [(_hit(1), evidence)],
    )
    assert not bad.ok
    assert any("数字未在所引证据出现" in error for error in bad.errors)


def test_citation_pointer_only_is_not_a_valid_answer():
    result = validate_citations(
        "工程风险的技术因素有哪些？",
        "依据：[S1]",
        [(_hit(1), "工程风险的技术因素包括零部件老化。")],
    )
    assert not result.ok
    assert any("未包含任何" in error for error in result.errors)


def test_bare_yiju_is_not_globally_ignored_when_it_carries_fact():
    result = validate_citations(
        "工程风险的技术因素有哪些？",
        "依据合同，所有风险都由承包商承担。 [S1]",
        [(_hit(1), "工程风险的技术因素包括零部件老化。")],
    )
    assert not result.ok
    assert any("未支持" in error or "覆盖" in error for error in result.errors)
