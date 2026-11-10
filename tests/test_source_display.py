"""真实来源映射与论点验证分离；仅使用合成课件和Mock。"""
import json
from types import SimpleNamespace
import pytest
from src.config import Settings
from src.qa import AnswerEngine
from src.retriever import Retriever, Hit
from src.structured_answer import parse_structured_answer, render_unverified_draft, validate_structured_answer
from src.citations import assess_claim_support, strip_internal_status
from tests.helpers import make_corpus, make_page
from tests.test_qa import FakeClient


def mapped():
    page=make_page('工程风险的技术因素包括零部件老化导致功能失调，控制系统失灵以及非线性作用，可能引发安全隐患。',category=None,filename='合成工程伦理.pdf',page_number=37)
    return {3:(SimpleNamespace(citation='《合成工程伦理.pdf》第 37 页',page=page),page.text)}


def payload(text,ref='S3'):
    return json.dumps(dict(summary='',points=[dict(content=text,citations=[ref])],conclusion='',insufficient=False),ensure_ascii=False)


def test_unverified_draft_maps_existing_source_even_if_fact_not_supported():
    evidence=mapped();parsed=parse_structured_answer(payload('事故造成999人死亡。'),list(evidence))
    validation=validate_structured_answer(parsed.answer,'工程风险有哪些？',evidence)
    assert not validation.ok and any('数字' in e for e in validation.errors)
    text=render_unverified_draft(parsed.answer,validation.errors,evidence)
    assert '[S3]' in text and '合成工程伦理.pdf' in text and '第 37 页' in text
    assert '不关联' not in text and '999' in text
    assert '数字未' not in text  # 风险由独立的verification_errors区域展示


def test_unknown_id_has_risk_and_never_gets_fabricated_source():
    evidence=mapped();parsed=parse_structured_answer(payload('工程风险需要重视。','S999'),list(evidence))
    assert not parsed.ok and any('S999' in e for e in parsed.errors)
    text=render_unverified_draft(parsed.answer,parsed.errors,evidence)
    assert '[S999]' not in text and '第 999 页' not in text
    assert '合成工程伦理.pdf' not in text


@pytest.mark.parametrize('annotation',['（该页未审核，需要复核）','该页未审核，需复核；','（未核验，不关联 PDF 页码）'])
def test_status_not_in_exam_answer_and_not_used_as_factual_objection(annotation):
    evidence=mapped();text='零部件老化导致功能失调，控制系统故障带来安全隐患。'+annotation
    parsed=parse_structured_answer(payload(text),list(evidence))
    assert parsed.ok
    clean=parsed.answer.points[0].content
    assert not any(w in clean for w in ('未审核','复核','未核验','PDF'))
    result=validate_structured_answer(parsed.answer,'工程风险的技术因素有哪些？',evidence)
    assert result.ok, result.errors


def test_normal_connectives_and_paraphrase_not_strict_unknown_veto():
    result=assess_claim_support('因此，设备老化造成失效，同时控制系统故障带来风险。',
        ['设备老化造成失效，控制系统失灵带来风险。'],strict_unknown=False)
    assert result.ok


def test_real_audit_course_content_is_not_removed_as_metadata():
    assert '审核制度' in strip_internal_status('工程审核制度要求保留审计记录。')


def test_full_mock_unreviewed_source_clean_body_and_real_context():
    page=make_page('工程风险的技术因素包括零部件老化导致功能失调，控制系统失灵和非线性作用。',filename='合成工程伦理.pdf',page_number=37)
    fake=FakeClient(content=payload('零部件老化导致功能失调。（该页未审核，需复核）','S1'))
    qa=AnswerEngine(Retriever(make_corpus(page)),settings=Settings(deepseek_api_key='synthetic-only'),client=fake)
    result=qa.answer('工程风险的技术因素有哪些？',mode='expanded',provider='deepseek',allow_api=True)
    assert fake.calls==1
    assert result.verification_status=='verified'
    assert '合成工程伦理.pdf' in result.answer and '第 37 页' in result.answer
    assert '未审核' not in result.answer and '复核' not in result.answer
    assert result.evidence_context[0]['page_number']==37
    assert '未审核' in result.evidence_context[0]['quality']
    assert 'content 中写明' not in fake.last_messages[0]['content']
