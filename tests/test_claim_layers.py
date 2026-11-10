"""分层证据校验专项；合成来源、假配置，不执行HTTP。"""
import json
from types import SimpleNamespace
import pytest
from src.citations import assess_claim_support,assess_claim_support_legacy
from src.structured_answer import parse_structured_answer,validate_structured_answer,render_structured_answer
from src.config import Settings
from src.qa import AnswerEngine
from src.retriever import Retriever
from tests.helpers import make_page,make_corpus
from tests.test_qa import FakeClient


def evidence():
    a=make_page('公众安全与健康应优先考虑，环境工程需要保护周边居民。',category='A',filename='安全课件.pdf',page_number=12)
    b=make_page('社会公正要求公平分配资源，不使弱势群体承担额外环境负担。',category=None,filename='公正课件.pdf',page_number=38)
    return {1:(SimpleNamespace(page=a,rank=1,citation=a.citation),a.text),
            3:(SimpleNamespace(page=b,rank=3,citation=b.citation),b.text)}


def validate(points,summary='',conclusion=''):
    raw=json.dumps(dict(summary=summary,points=points,conclusion=conclusion,insufficient=False),ensure_ascii=False)
    parsed=parse_structured_answer(raw,[1,3])
    return parsed,validate_structured_answer(parsed.answer,'如何进行伦理判断？',evidence())


def point(content,refs=('S1',),**kw):return dict(content=content,citations=list(refs),**kw)


@pytest.mark.parametrize('claim',[
    '不仅公众安全与健康应优先考虑，还要关注周边居民。',
    '总体而言，关注公众安全与健康，同时关注周边居民。',
])
def test_connectives_are_not_unsupported_facts(claim):
    old=assess_claim_support_legacy(claim,[evidence()[1][1]])
    new=assess_claim_support(claim,[evidence()[1][1]])
    assert new.ok,new.reasons


def test_synonym_paraphrase_keeps_core_obligation():
    result=assess_claim_support('设备老化导致系统失效。',['零部件老化导致系统失灵。'])
    assert result.ok,result.reasons


def test_summary_uses_supported_points_across_sources():
    parsed,result=validate([point('公众安全与健康应优先考虑。'),point('社会公正要求公平分配资源。',('S3',))],
                          summary='不仅公众安全与健康应优先考虑，还要关注社会公正。',
                          conclusion='公众安全与健康和社会公正需要同时关注。')
    assert result.ok,result.errors
    assert result.layers['reference_integrity']['ok'] and result.layers['claim_support']['ok']
    assert result.layers['source_review'][3]['strict_eligible'] is False
    rendered=render_structured_answer(parsed.answer,evidence())
    assert '第 12 页' in rendered and '第 38 页' in rendered


@pytest.mark.parametrize('claim',['化学工程需要优先考虑公众安全与健康。','危险源要求优先考虑公众安全与健康。','事故造成999人死亡。'])
def test_new_specific_fact_or_number_still_rejected(claim):
    _,result=validate([point(claim)])
    assert not result.ok


def test_unknown_id_and_fabricated_page_are_integrity_errors():
    parsed,_=validate([point('公众安全与健康应优先考虑。',('S99',))])
    assert not parsed.ok and any('S99' in e for e in parsed.errors)
    parsed,_=validate([point('依据安全课件.pdf第999页，应保护居民。')])
    assert not parsed.ok


def test_bad_source_metadata_cannot_be_verified():
    mapped=evidence();mapped[1][0].page=make_page(mapped[1][1],category='A',page_number=0)
    parsed,_=validate([point('公众安全与健康应优先考虑。')])
    result=validate_structured_answer(parsed.answer,'',mapped)
    assert not result.layers['reference_integrity']['ok']


def test_analysis_requires_supported_basis_and_separate_label():
    parsed,result=validate([point('公众安全与健康应优先考虑。'),
        point('建议组织长期监测，并听取居民意见。',kind='analysis',basis='公众安全与健康应优先考虑。')])
    assert result.ok,result.errors
    assert '【基于课件的案例分析】' in render_structured_answer(parsed.answer,evidence())
    _,bad=validate([point('已经造成999人死亡。',kind='analysis',basis='公众安全与健康应优先考虑。')])
    assert not bad.ok
    _,bad=validate([point('建议组织监测。',kind='analysis',basis='危险源已经得到消除。')])
    assert not bad.ok


def test_failed_fact_cannot_be_laundered_by_summary():
    _,result=validate([point('事故造成999人死亡。')],summary='事故造成999人死亡。')
    assert not result.ok and any('summary' in e for e in result.errors)


def test_mock_engine_preserves_layers_and_source_review():
    from dataclasses import replace
    a=replace(evidence()[1][0].page,text=evidence()[1][1]+'工程实践需要重视公众合法权益并落实保护措施。')
    fake=FakeClient(content=json.dumps(dict(summary='',points=[point('公众安全与健康应优先考虑。')],conclusion='',insufficient=False),ensure_ascii=False))
    qa=AnswerEngine(Retriever(make_corpus(a)),settings=Settings(deepseek_api_key='synthetic-only'),client=fake)
    result=qa.answer('公众安全与健康',provider='deepseek',allow_api=True)
    assert fake.calls==1 and result.verification_layers
    assert result.verification_status=='verified'
    assert result.citations[0].page.page_number==12


@pytest.mark.parametrize('claim,text',[
 ('不仅关注设备老化，还要关注系统故障与二者之间。','零部件老化和系统失灵带来安全风险。'),
 ('公众安全与健康不同于社会公正，二者之间需要同时关注。','公众安全与健康应优先考虑。社会公正要求公平分配资源。'),
 ('不仅设备老化导致系统失效，还要关注系统故障。','零部件老化导致系统失灵。'),
])
def test_reported_language_false_positive_improves_without_threshold_change(claim,text):
    assert not assess_claim_support_legacy(claim,[text]).ok
    assert assess_claim_support(claim,[text]).ok


def test_legacy_validation_policy_remains_callable():
    parsed,_=validate([point('公众安全与健康应优先考虑。')])
    old=validate_structured_answer(parsed.answer,'',evidence(),policy='legacy')
    assert old.ok
