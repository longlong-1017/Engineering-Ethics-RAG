"""十题合成检索基准：金标页独立于扩展词典，仅作检索指标。"""
from dataclasses import replace
import pytest
from src.retriever import Retriever, reciprocal_rank_fusion
from src.query_expansion import expand_query
from src.dense_index import DenseIndex,page_id
from src.evidence import plan_evidence
from tests.helpers import make_corpus,make_page

QUESTIONS=[
'什么是工程伦理？','工程师的伦理责任有哪些？','环境工程中的安全主要包括哪些方面？',
'环境工程中的社会公正主要体现在哪些方面？','简述环境工程安全与社会公正之间的关系。',
'某化工企业排放废水虽然满足现行标准，但可能长期影响周边居民健康。工程师应该如何进行伦理判断？',
'某工程项目能够带来显著经济收益，但可能对当地生态环境造成不可逆损害，应如何进行伦理决策？',
'当工程师发现项目存在安全隐患，但管理层要求继续施工时，应如何处理？',
'工程活动为什么需要考虑公众利益？','一个课件中不存在的虚构工程伦理概念是什么？']
GOLD=[{1},{2},{3},{4},{3,4},{2,3,4,5},{2,4,5,6},{2,5},{7},set()]


def corpus():
    texts=['工程伦理是指工程实践中处理人与社会及自然关系的道德原则和行为准则。',
'工程师的伦理责任包括保护公众安全与健康，报告安全隐患，保持职业判断并承担社会责任。',
'环境工程中的安全包括公众健康、生产安全和生态安全；工程活动必须重视污染对周边居民的影响。',
'环境工程中的社会公正包括公平分配社会资源，避免弱势群体承担不合理的环境负担。',
'工程风险评估与预防包括识别长期风险，评估健康损害的不确定性，建立预警机制并采取预防措施。',
'工程活动中的环境伦理原则包括尊重自然和不损害原则，应综合考虑经济收益与不可逆生态损害。',
'工程活动中的公众利益需要优先考虑，因为公众承担工程风险，工程师必须保护公众安全与健康。']
    return make_corpus(*(make_page(t,category='A',filename=f'合成课件{i}.pdf',page_number=i) for i,t in enumerate(texts,1)))


def metrics(mode):
    r=Retriever(corpus(),retrieval_mode=mode)
    result=[]
    for question,gold in zip(QUESTIONS,GOLD):
        hits=r.search(question,top_k=10).hits
        ids=[h.page.page_number for h in hits]
        if gold:
            ranks=[ids.index(i)+1 for i in gold if i in ids]
            result.append((len(gold&set(ids[:5]))/len(gold),len(gold&set(ids[:10]))/len(gold),1/min(ranks) if ranks else 0))
    return tuple(sum(v[i] for v in result)/len(result) for i in range(3))


def test_ten_questions_and_case_background_not_fictional_fact():
    r=Retriever(corpus());response=r.search(QUESTIONS[5],top_k=10)
    assert response.diagnostics['subqueries'][0]==QUESTIONS[5]
    assert {2,3,4}&{h.page.page_number for h in response.hits}
    plan=plan_evidence(QUESTIONS[5],response.hits)
    assert len(plan.quotes)>=2
    assert all(text==h.page.text.strip() or text for h,text in plan.quotes)
    fictional=r.search(QUESTIONS[-1]);assert not fictional.enough_evidence
    assert not plan_evidence(QUESTIONS[-1],fictional.hits).quotes


def test_expansion_bounded_unique_and_original_preserved():
    queries=expand_query(QUESTIONS[5]);assert len(queries)<=6 and len(set(queries))==len(queries)
    assert queries[0]==QUESTIONS[5]


def test_rrf_scale_independent_and_stable_id_dedup():
    scores=reciprocal_rank_fusion([['a','b','a'],['b','c']])
    assert scores['b']>scores['a'] and len(scores)==3


class Encoder:
    def __init__(self):self.encoded=[]
    def encode(self,texts):
        self.encoded.extend(texts)
        return [[1.,float('环境' in t)+.1] for t in texts]


def test_dense_incremental_cache_and_strict_pool(tmp_path):
    c=corpus();enc=Encoder();cache=tmp_path/'vectors.sqlite3'
    d=DenseIndex(c.pages,enc,'mock-v1',cache);assert len(enc.encoded)==7
    DenseIndex(c.pages,enc,'mock-v1',cache);assert len(enc.encoded)==7
    changed=[replace(c.pages[0],text=c.pages[0].text+'补充说明。'),*c.pages[1:]]
    DenseIndex(changed,enc,'mock-v1',cache);assert len(enc.encoded)==8
    assert all(k==page_id(c.pages[0]) for k,s in d.search('环境',{page_id(c.pages[0])}))


def test_broken_dense_degrades_to_bm25():
    class Broken:
        def search(self,*args):raise RuntimeError('synthetic')
    response=Retriever(corpus(),dense_index=Broken()).search(QUESTIONS[5])
    assert response.hits and response.diagnostics['fallback']


def test_benchmark_comparison():
    old,new=metrics('legacy'),metrics('hybrid')
    assert new[1]>=old[1]
    print('synthetic Recall@5 Recall@10 MRR',old,new)


def test_mock_dense_rrf_is_integrated_and_never_leaks_unreviewed_page(tmp_path):
    c=corpus()
    hidden=make_page('环境工程中的安全包括公众健康及生态安全，需要控制污染排放。',category=None,filename='未审核合成.pdf',page_number=80)
    c=make_corpus(*c.pages,hidden)
    dense=DenseIndex(c.expanded_pages,Encoder(),'mock',tmp_path/'vectors.sqlite3')
    response=Retriever(c,dense_index=dense).search(QUESTIONS[5],mode='strict',top_k=10)
    assert response.diagnostics['dense_hits']>0
    assert all(h.page.filename!='未审核合成.pdf' for h in response.hits)
    assert len({h.evidence_id for h in response.hits})==len(response.hits)


def test_mock_case_uses_courseware_context_before_general_fallback():
    from src.qa import AnswerEngine
    from src.config import Settings
    from tests.test_qa import FakeClient
    from tests.helpers import structured_answer
    fake=FakeClient(content=structured_answer('应关注工程风险。',[('应关注工程风险。',['S1'])]))
    answer=AnswerEngine(Retriever(corpus()),settings=Settings(deepseek_api_key='synthetic-only'),client=fake).answer(
        QUESTIONS[5],qa_mode='hybrid',provider='deepseek',allow_api=True)
    assert fake.calls==1 and answer.evidence_context
    assert not answer.general_knowledge
    assert '课件证据' in fake.last_messages[1]['content']
