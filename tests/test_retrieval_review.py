"""第三阶段联调层的合成/Mock回归，不触碰生产数据或生成模型。"""
from copy import deepcopy
import pytest

from src.retrieval_review import (features,RelevanceCalibration,review_results,reference,
                                  resolve_references,evidence_coverage,quiz_record,conflict_hints,RetrievalReviewSession)

Q='什么是工程风险？'


def record(text,id='TB-x',kind='textbook',chapter=1,section='1.1',page=1):
    return dict(id=id,kind=kind,priority=3 if kind=='textbook' else 1,
                text=text,review_status='UNVERIFIED',strict_eligible=False,
                sources=[dict(filename='合成.pdf',document_sha256='synthetic',physical_page=page,
                              printed_page=None,printed_page_candidates=[1],printed_page_inferred=32,
                              printed_page_status='candidate_conflicts_with_offset')],
                chapter=chapter,section_id=section,topic_heading='',original_rank=1,raw_scores={},context_for=[])


class AllRelevant:
    def predict(self,values):return 2
    def score(self,values):return 1.
    def to_dict(self):return {'provenance':'synthetic_mock'}


def calibration():
    data=[(record('工程风险是指工程活动中不利后果发生的可能性，需要进行风险分析。'),2),
          (record('工程师在职业活动中还需要关注工程风险。'),1),
          (record('金融资产价值由市场供求决定。'),0)]
    return RelevanceCalibration.fit([dict(features=features(Q,r),label=label) for r,label in data],
                                     'synthetic_review_not_human_gold'),data


def test_calibration_boundaries_come_from_labeled_scores_and_three_levels():
    cal,data=calibration()
    assert [cal.predict(features(Q,r)) for r,label in data]==[2,1,0]
    assert cal.low<=cal.high and 'synthetic' in cal.provenance
    with pytest.raises(ValueError):RelevanceCalibration.fit([dict(features=(0,)*5,label=0)],'synthetic')


def test_relevance_precedes_source_priority_and_inputs_are_immutable():
    cal,data=calibration();good=deepcopy(data[0][0]);bad=record('金融资产价值由市场供求决定。',id='ppt:unrelated',kind='ppt_new')
    original=deepcopy([good,bad]);result=review_results(Q,[good,bad],cal)
    assert result['selected'][0]['record']['id']==good['id']
    assert any(x['id']==bad['id'] and x['reason']=='校准模型判为不相关' for x in result['filtered'])
    assert [good,bad]==original and result['references']['R1']['review_status']=='UNVERIFIED'


def test_names_only_are_related_but_not_sufficient_for_comparison():
    r=record('课程涉及生产安全、公共安全、社会公正等多个领域。')
    result=review_results('生产安全与公共安全有什么区别？',[r],AllRelevant())
    assert result['selected'] and result['coverage']['state']=='partial_reference'
    assert not result['coverage']['strict_verified']


def test_comparison_two_explanations_complete_without_review_upgrade():
    a=record('环境工程中的生产安全\n\n环境工程中的生产主要涉及饮用水及污水处理，要求生产过程安全。')
    b=record('公共安全是指涉及公众生命、健康和环境的安全问题。',id='TB-y')
    result=review_results('生产安全与公共安全有什么区别？',[a,b],AllRelevant())
    assert result['coverage']['state']=='complete_reference'
    assert not result['coverage']['strict_verified']
    assert all(x['review_status']=='UNVERIFIED' for x in result['references'].values())


def test_unknown_requested_accident_date_keeps_partial_coverage():
    r=record('工程风险的技术因素包括设备老化、控制系统失灵和非线性作用。')
    result=review_results('工程风险的技术因素有哪些？并给出2027年某事故的伤亡人数。',[r],AllRelevant())
    assert result['coverage']['state']=='partial_reference'


def test_specific_rule_identity_cannot_be_replaced_by_generic_ethics():
    r=record('工程伦理规范包括公众利益、工程师责任以及其他一般要求。')
    result=review_results('《合成行业安全规范》第九条是什么？',[r],AllRelevant())
    assert not result['selected'] and result['coverage']['state']=='insufficient'
    assert '标题未在证据中出现' in result['filtered'][0]['reason']


def test_source_identity_collisions_and_fake_reference_ids_rejected():
    a=record('工程风险需要预防。');b=record('完全不同的正文。')
    with pytest.raises(ValueError):review_results(Q,[a,b],AllRelevant())
    result=review_results(Q,[a],AllRelevant())
    assert resolve_references(['R1'],result['references'])[0]['sources'][0]['physical_page']==1
    with pytest.raises(ValueError):resolve_references(['R999'],result['references'])


@pytest.mark.parametrize('fault',['page','printed','review'])
def test_reference_cannot_invent_pages_or_upgrade_textbook(fault):
    r=record('教材文本。')
    if fault=='page':r['sources'][0]['physical_page']=0
    if fault=='printed':r['sources'][0]['printed_page']=32
    if fault=='review':r['review_status']='VERIFIED';r['strict_eligible']=True
    with pytest.raises(ValueError):reference(r,1)


def test_pending_section_print_candidates_and_status_preserved():
    r=record('工程风险是指不利后果的可能性。',section=None)
    ref=reference(r,1)
    assert ref['section_id'] is None and ref['sources'][0]['printed_page'] is None
    assert ref['sources'][0]['printed_page_candidates']==[1]
    assert '小节归属待确认' in ref['risks'] and '印刷页码冲突待审核' in ref['risks']


def test_citation_keeps_book_and_original_chapter_metadata():
    r=record('工程风险相关正文。');r.update(book='工程伦理',chapter_title='工程与伦理',section_title='工程风险')
    ref=reference(r,1)
    assert (ref['book'],ref['chapter'],ref['chapter_title'],ref['section_id'],ref['section_title'])==('工程伦理',1,'工程与伦理','1.1','工程风险')


def test_strict_filter_uses_only_existing_audited_ppt():
    book=record('工程风险相关教材。');ppt=record('工程风险相关课件。',id='ppt:a',kind='ppt_old')
    ppt['strict_eligible']=True;ppt['review_status']='严格合格A'
    result=review_results(Q,[book,ppt],AllRelevant(),strict=True)
    assert [x['record']['id'] for x in result['selected']]==['ppt:a']
    assert any(x['id']==book['id'] for x in result['filtered'])


def test_duplicate_filter_preserves_excluded_source_trace():
    a=record('完整相同的工程风险教材正文。');b=record(a['text'],id='TB-y',page=2)
    result=review_results(Q,[a,b],AllRelevant())
    assert len(result['selected'])==1
    excluded=next(x for x in result['filtered'] if '重复' in x['reason'])
    assert excluded['sources'] and excluded['duplicate_of']


@pytest.mark.parametrize('scope',['valid','chapter','section','page','unknown'])
def test_neighbor_context_is_traced_and_cannot_cross_boundaries(scope):
    seed=record('工程利益冲突方式包括①拒绝、②放弃、③离职。')
    other=record('④不参与；⑤披露。',id='TB-y',page=2)
    other['context_for']=[seed['id']]
    if scope=='chapter':other['chapter']=2
    if scope=='section':other['section_id']='1.2'
    if scope=='page':other['sources'][0]['physical_page']=99
    if scope=='unknown':other['section_id']=None
    class Gate(AllRelevant):
        def predict(self,v):return 2 if v[0]>0 else 0
    result=review_results('工程利益冲突方式',[seed,other],Gate(),top_k=1)
    assert bool(result['context'])==(scope=='valid')
    if scope=='valid':assert len(result['references'])==2 and result['references']['R2']['sources'][0]['physical_page']==2


def bank(answer='B'):
    return dict(id='1.1-01',question='工程风险伦理评估原则不包括',type='单选',
                options={'A':'以人为本','B':'经济至上','C':'预防为主','D':'制度约束'},
                correct_answer=answer,answer_status='confirmed_from_screenshot' if answer else 'not_visible_in_screenshot',
                verification_status='source_reported_confirmed' if answer else 'pending',
                history=[dict(user_answer='ABCD')],pdf_sources=[dict(pdf_filename='测试题库.pdf',pdf_sha256='hash',question_pages=[4],answer_page=6)])


def test_quiz_options_and_history_never_become_retrieval_facts():
    row=bank();r=quiz_record(row)
    assert r['text']==row['question'] and '经济至上' not in r['text'] and 'history' not in r['bank']
    result=evidence_coverage(row['question'],[r],row['options'])
    assert result['state']=='complete_reference' and not result['strict_verified']
    wrong=dict(row['options'],B='新干扰项')
    assert evidence_coverage(row['question'],[r],wrong)['state']=='partial_reference'


def test_pending_quiz_answer_cannot_be_inferred_from_history_or_course():
    row=bank(None);r=quiz_record(row);course=record('工程风险伦理评估原则包括以人为本、预防为主、整体主义和制度约束。')
    result=evidence_coverage(row['question'],[r,course],row['options'])
    assert result['state']=='partial_reference'
    assert not any(x['complete_reference'] for x in result['by_source'].values())


def test_numeric_difference_is_only_a_conflict_hint_and_never_auto_merged():
    a=record('合成事故死亡10人。',kind='ppt_new');b=record('合成事故死亡12人。',id='TB-y')
    hints=conflict_hints([a,b]);assert hints and '待人工核对' in hints[0]['reason']
    result=review_results('合成事故伤亡情况',[a,b],AllRelevant())
    assert result['conflict_hints'] and result['cross_source_combination_allowed'] is False


def test_generic_coordinator_requires_calibration_and_strict_skips_textbook_bank():
    class NoTextbookCalls:
        def search(self,*a,**kw):raise AssertionError('严格模式不应检索教材')
    session=RetrievalReviewSession({},NoTextbookCalls(),[],[bank()])
    with pytest.raises(ValueError):session.search('任意问题')
    session.calibration=AllRelevant()
    result=session.search('任意问题',strict=True)
    assert not result['selected'] and result['coverage']['state']=='insufficient'


def test_conflicting_status_for_same_evidence_id_is_not_silently_accepted():
    a=record('工程风险需要预防。');b=deepcopy(a);b['strict_eligible']=True
    with pytest.raises(ValueError):review_results(Q,[a,b],AllRelevant())


@pytest.mark.parametrize('verb',['回避','避免','避开'])
@pytest.mark.parametrize('body_verb',['回避','避免','避开'])
def test_action_aliases_share_features_without_promoting_background(verb,body_verb):
    question=verb+'利益冲突有哪些方式？'
    direct=record(body_verb+'利益冲突的方式\n\n1）公开说明利益关系。\n2）退出相关决策。')
    background=record('利益冲突可能来自经济利益、道德义务和不同价值观。')
    original=deepcopy([direct,background])
    assert features(question,direct)==features('回避利益冲突有哪些方式？',record(
        '回避利益冲突的方式\n\n1）公开说明利益关系。\n2）退出相关决策。'))
    assert features(question,direct)[4]==1
    assert features(question,background)[4]==0
    assert [direct,background]==original


def test_alias_normalization_preserves_paragraph_and_list_boundaries():
    from src.retrieval_review import normalize_concepts
    raw='避免利益冲突\n\n1）申报。\n2）退出。'
    assert normalize_concepts(raw)=='回避利益冲突\n\n1）申报。\n2）退出。'
    for verb in ('回避','避免','避开'):
        r=record(verb+'利益冲突的两种方式\n\n1）申报。\n2）退出。')
        result=evidence_coverage(verb+'利益冲突的两种方式有哪些？',[r])
        assert result['state']=='complete_reference'
        assert not result['strict_verified']
        assert r['review_status']=='UNVERIFIED'


def test_frozen_evaluation_never_refits_or_changes_calibration(tmp_path,monkeypatch):
    import json,runpy
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    module=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/review_retrieval_phase3.py'))
    def forbidden_fit(*args,**kwargs):raise AssertionError('冻结评测禁止重新拟合')
    monkeypatch.setattr(RelevanceCalibration,'fit',forbidden_fit)
    cal=RelevanceCalibration((1,2,0,0,1),0.3660714285714286,0.6875,'synthetic_not_human_gold').to_dict()
    r=record('回避利益冲突的方法包括主动申报和退出决策。')
    payload={'cases':[{'case':{'id':'S01','question':'避免利益冲突有哪些方式？','split':'test'},'candidates':[r]}]}
    labels={'pairs':[{'query_id':'S01','evidence_id':r['id'],'relevance':2}],
            'query_coverage':{},'provenance':'synthetic_not_human_gold'}
    paths=[tmp_path/name for name in ('harvest.json','labels.json','cal.json','out.json')]
    for path,data in zip(paths,[payload,labels,{'calibration':cal}]):path.write_text(json.dumps(data))
    module['evaluate'](paths[0],paths[1],paths[3],paths[2])
    result=json.loads(paths[3].read_text())
    assert result['calibration']==json.loads(json.dumps(cal))
    assert result['calibration_mode']=='frozen'
    assert result['formal_human_gold_metrics'] is None
    assert result['results'][0]['result']['references']['R1']['review_status']=='UNVERIFIED'
