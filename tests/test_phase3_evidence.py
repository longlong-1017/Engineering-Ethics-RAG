"""独立合成语料：不使用验收题、真实课件名、页码或金标答案。"""
import re

import pytest

from src.config import Settings
from src.evidence import analyze_question, body_paragraphs, plan_evidence
from src.qa import AnswerEngine, PROVIDER_LOCAL, STATUS_OK, STATUS_INSUFFICIENT
from src.retriever import Retriever
from src.text_utils import compact_text, is_definition_question, split_sentences
from tests.helpers import make_corpus, make_page, structured_answer
from tests.test_qa import FakeClient


def answer(question, *pages, mode='strict', client=None, allow_api=False):
    return AnswerEngine(Retriever(make_corpus(*pages)),settings=Settings(deepseek_api_key=None),client=client).answer(
        question,mode=mode,provider='auto' if allow_api else PROVIDER_LOCAL,allow_api=allow_api)


@pytest.mark.parametrize('question',[
    '海湾桥事故的伤亡和经济损失是多少？',
    '远航号事故的时间、地点和后果是什么？',
    '北岭港爆炸事故的伤亡和经济损失是多少？',
])
def test_unrelated_accident_with_same_numeric_facets_cannot_answer(question):
    page=make_page('南沙港爆炸事故。2021年造成12人死亡、35人受伤，直接经济损失为2.75亿元。',category='A')
    result=answer(question,page)
    assert result.status==STATUS_INSUFFICIENT
    assert not result.citations


@pytest.mark.parametrize('question',[
    '合同的三种终止方式是什么？','桥梁倒塌的结果是什么？',
    '项目的经济损失是多少？','监理人员回避利益冲突的两种方式是什么？',
])
def test_what_suffix_is_not_always_definition(question):
    assert not is_definition_question(question)


@pytest.mark.parametrize('question',['什么是职业操守？','职业操守是什么？','职业操守指什么？'])
def test_actual_definition_recognition(question):
    assert is_definition_question(question)


def test_subtype_definition_does_not_define_parent():
    result=answer('什么是职业操守？',make_page('职业操守规范是指从业者处理工作事项时必须遵守的行为标准。',category='A'))
    assert result.status==STATUS_INSUFFICIENT


def test_outline_cannot_answer_list():
    result=answer('施工风险的技术因素包括哪些？',make_page('课程目录\n1、施工风险的技术因素\n2、责任划分\n3、职业规范',category='A'))
    assert result.status==STATUS_INSUFFICIENT


def test_short_complete_definition_is_usable():
    result=answer('什么是保密义务？',make_page('保密义务是指不得泄露受托秘密。',category='A'))
    assert result.status==STATUS_OK


@pytest.mark.parametrize('value',['2.75亿元','0.06亿元','12.125万元'])
def test_decimal_results_after_numbered_intro_remain_complete(value):
    text=f'南沙港事故\n1）事故经过。\n2022年发生爆炸，造成12人死亡、35人受伤，直接经济损失为{value}。'
    result=answer('南沙港事故的伤亡和经济损失是多少？',make_page(text,category='A',page_number=37))
    assert result.status==STATUS_OK
    assert value in result.answer and '35人受伤' in result.answer
    assert result.citations[0].page.page_number==37


def test_eight_item_list_and_long_last_item_not_truncated():
    items=['①关闭阀门','②撤离人员','③通报负责人','④检查电源','⑤隔离现场','⑥记录时间','⑦通知救援','⑧复核风险']
    text='应急处理包括以下八种方式：\n'+'；\n'.join(items)+'。'+('末项需要持续观察设备温度并记录复核过程。'*35)
    result=answer('应急处理包括哪八种方式？',make_page(text,category='A'))
    assert result.status==STATUS_OK
    assert all(item in result.answer for item in items)
    assert text[-40:] in result.answer


def test_cross_page_list_preserves_scope_and_sources():
    p1=make_page('防灾治理\n防灾治理有两个思路：一是通过设施预防，强化堤坝和监测设备的可靠性。',category='A',page_number=41,filename='合成材料.pdf')
    p2=make_page('防灾治理\n二是从组织层面准备，开展人员培训、疏散演练以及多部门协作。',category=None,page_number=42,filename='合成材料.pdf')
    strict=answer('防灾治理的两种理解思路是什么？',p1,p2)
    expanded=answer('防灾治理的两种理解思路是什么？',p1,p2,mode='expanded')
    assert all(h.page.page_number==41 for h in strict.citations)
    assert '多部门协作' in expanded.answer
    assert {h.page.page_number for h in expanded.citations}=={41,42}


def test_numeric_related_title_does_not_answer_result():
    result=answer('南沙港公众座谈会的结果如何？',make_page('南沙港公众座谈会于2020年召开，地点为市民中心，会上安排了项目介绍及专家讲解。',category='A'))
    assert result.status==STATUS_INSUFFICIENT


def test_definition_rejects_unrelated_same_heading_continuation():
    a=make_page('职业规范\n保密义务是指不得泄露受托秘密。',category='A',page_number=1)
    b=make_page('职业规范\n其次，安全培训需要每个月开展一次，避免操作事故和设备失灵。',category='A',page_number=2)
    result=answer('保密义务是什么？',a,b)
    assert len(result.citations)==1


def test_each_local_quote_is_locatable_in_its_cited_page():
    p=make_page('安全协议\n安全协议包括双方约定的应急责任和信息共享规则；必须定期复核执行情况。',category='A',filename='随机来源.pdf',page_number=93)
    result=answer('安全协议包括哪些？',p)
    assert result.status==STATUS_OK
    for hit,quote in plan_evidence(result.question,result.search.hits).quotes:
        assert compact_text(quote) in compact_text(hit.page.text)
        assert f'[S{hit.rank}]' in result.answer


@pytest.mark.parametrize('content',[
    structured_answer('数据保管包括公开所有客户记录。', [('数据保管包括公开所有客户记录。', ['S1'])]),
    structured_answer('数据保管包括加密客户记录。', [('数据保管包括加密客户记录。', ['S9'])]),
    structured_answer('数据保管包括加密客户记录。', [('数据保管包括加密客户记录。', ['S1']), ('还可以出售客户记录。', ['S1'])]),
    structured_answer('数据保管包括加密客户记录。', [('数据保管包括加密客户记录。', [])]),
])
def test_api_unverifiable_claims_are_kept_as_unverified_draft(content):
    fake=FakeClient(content=content)
    result=answer('数据保管包括哪些？',make_page('数据保管包括加密客户记录。必须限制访问权限，并定期审计访问日志，防止信息泄露。',category='A'),client=fake,allow_api=True)
    assert fake.calls==1
    assert result.provider=='deepseek'
    assert result.verification_status=='unverified'
    assert result.citations==()
    assert result.verification_status == "unverified"
    assert result.verification_errors
    assert "【未通过严格校验的原因】" not in result.answer


def test_api_decimal_hallucination_is_not_stripped_as_list_number():
    source=make_page('南沙港事故造成12人死亡、35人受伤，直接经济损失为2.75亿元。',category='A')
    fake=FakeClient(content=structured_answer('9.75亿元。', [('9.75亿元。', ['S1'])]))
    result=answer('南沙港事故的伤亡和经济损失是多少？',source,client=fake,allow_api=True)
    assert result.provider=='deepseek'
    assert result.verification_status=='unverified'
    assert '9.75亿元' in result.answer  # AI 草稿保留，但明确未核验
    assert result.citations==()


def test_complete_plain_list_does_not_quote_background_page():
    primary=make_page('排险流程\n检查设备状态\n隔离危险区域\n通知现场人员\n记录处置结果',category='A',page_number=7)
    background=make_page('排险流程\n排险流程包括人员培训背景，培训涉及不同机构的组织安排，需要长期协调与持续投入。',category='A',page_number=8)
    result=answer('排险流程包括哪些？',primary,background)
    assert result.status==STATUS_OK
    assert '检查设备状态' in result.answer
    # 主检索可能选择背景为首；规划应保留完整清单，不丢行。
    assert '记录处置结果' in result.answer


def test_named_principle_list_excludes_other_principle_background():
    primary=make_page('材料设计原则\n材料设计原则主要由诚实原则、节约原则和审慎原则三部分构成，设计人员必须在全生命周期贯彻。',category='A',page_number=7)
    background=make_page('材料设计原则\n评价标准包括外部绩效原则和奖励原则，这些原则决定组织的绩效考核方式，需要另行讨论。',category='A',page_number=8)
    result=answer('材料设计原则包括哪些？',primary,background)
    assert result.status==STATUS_OK
    assert '外部绩效' not in result.answer
