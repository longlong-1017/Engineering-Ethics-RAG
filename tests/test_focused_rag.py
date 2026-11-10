"""聚焦改造：真实检索/规划，合成课件和Mock模型，不加载配置或真实资料。"""
import json
import pytest
from src.config import Settings
from src.qa import AnswerEngine
from src.retriever import Retriever
from src.structured_answer import parse_structured_answer
from tests.helpers import make_corpus, make_page
from tests.test_qa import FakeClient


def run_answer(points, supplements=(), summary='工程风险需要从技术与责任两个层面分析。'):
    pages=[make_page('工程风险\n工程风险的技术因素包括零部件老化、控制系统失灵和非线性作用，可能引发安全事故。',category='A',filename='合成课件PPT导出.pdf',page_number=12),
           make_page('工程风险\n工程风险的责任包括加强安全意识教育，操作人员必须遵守安全第一的行动准则。',category='A',filename='合成课件PPT导出.pdf',page_number=13)]
    payload=dict(summary=summary,points=points,conclusion='应结合技术防范和责任要求控制工程风险。',insufficient=False,supplements=list(supplements))
    fake=FakeClient(content=json.dumps(payload,ensure_ascii=False))
    engine=AnswerEngine(Retriever(make_corpus(*pages)),settings=Settings(deepseek_api_key='synthetic-only'),client=fake)
    result=engine.answer('工程风险包括哪些？',provider='deepseek',allow_api=True)
    return result,fake


def test_synthesis_preserved_with_two_real_physical_pages_and_separate_supplement():
    result,fake=run_answer([
        dict(content='设备老化、控制系统故障以及非线性效应是技术风险的来源。',citations=['S1']),
        dict(content='操作人员应强化安全意识，把安全第一落实到操作中。',citations=['S2'])],
        ['复习时可用“技术防范—责任落实”作为组织答案的记忆框架。'])
    assert fake.calls==1 and result.provider=='deepseek'
    assert result.verification_status in ('verified','unverified')
    assert '设备老化' in result.answer and '记忆框架' in result.answer
    assert 'AI补充（未经课件核实' in result.answer
    assert {x['page_number'] for x in result.evidence_context}=={12,13}
    prompt=fake.last_messages[1]['content']
    for x in result.evidence_context:
        assert x['text'] in prompt and f"PDF 第 {x['page_number']} 页" in prompt
        assert x['filename'] in prompt and '['+x['id']+']' in prompt
    assert 'supplements' in fake.last_messages[0]['content']


@pytest.mark.parametrize('extra',['补充建议 [S1]','参考第999页','课件指出所有工程都没有风险'])
def test_supplement_cannot_borrow_courseware_authority(extra):
    result,_=run_answer([dict(content='零部件老化会带来安全风险。',citations=['S1'])],[extra])
    assert result.verification_status=='unverified'
    assert extra not in result.answer
    assert result.citations==()


def test_fabricated_reference_kept_unverified_without_real_source_claim():
    result,_=run_answer([dict(content='安全风险需要重视。',citations=['S999'])])
    assert result.verification_status=='unverified' and result.citations==()
    assert all(x['id']!='S999' for x in result.evidence_context)
