"""双版本合成/Mock回归，不读取课件、配置或真实额度。"""
from dataclasses import replace
import hashlib
import pytest

from src.config import Settings
from src.dense_index import DenseIndex, page_id
from src.evidence import plan_evidence
from src.qa import AnswerEngine, QA_MODE_HYBRID, QA_MODE_NEW_FIRST
from src.versioned_corpus import (NEW_VERSION, VersionedRetriever, source_pdf,
                                  potential_conflicts, load_versions)
from tests.helpers import make_page, make_corpus, structured_answer
from tests.test_compact_display import ui
from tests.test_qa import FakeClient
from tests.test_retrieval_upgrade import Encoder
from tests.test_theory_comparison import Q, make_test_corpus

QUESTION = '工程风险的技术因素有哪些？'
TEXT = ('工程风险的技术因素\n1）工程中零部件老化，导致系统功能失调，从而引发事故风险。\n'
        '2）控制系统失灵，存在引发事故的隐患。\n3）非线性作用会引发安全隐患。')


def versions(new_text=TEXT):
    old = make_page(TEXT, category='A', filename='同名.pdf', page_number=17, doc_id='old-hash')
    new = replace(make_page(new_text, filename='同名.pdf', page_number=3, doc_id='new-hash'),
                  dataset_version=NEW_VERSION, versioned_source=True)
    return make_corpus(replace(old, versioned_source=True)), make_corpus(new)


def ask(retriever, content=None, **kw):
    client = FakeClient(content=content)
    engine = AnswerEngine(retriever, settings=Settings(deepseek_api_key='synthetic-only'), client=client)
    result = engine.answer(QUESTION, qa_mode=QA_MODE_NEW_FIRST,
                           provider='deepseek', allow_api=True, **kw)
    return result, client


def test_new_substantive_priority_and_single_version_model_evidence():
    r = VersionedRetriever(*versions())
    result = r.search(QUESTION, mode='new_first')
    assert result.hits[0].page.dataset_version == NEW_VERSION
    assert result.diagnostics['answer_version'] == NEW_VERSION
    assert any(h.page.dataset_version == 'old' for h in result.hits)
    assert {h.page.dataset_version for h, t in plan_evidence(QUESTION, result.evidence_hits).quotes} == {NEW_VERSION}
    assert len({h.rank for h in result.hits}) == len(result.hits)


def test_irrelevant_newer_page_does_not_displace_substantive_old():
    r = VersionedRetriever(*versions('课程目录\n工程风险\n工程风险的技术因素'))
    result = r.search(QUESTION, mode='new_first')
    assert result.diagnostics['answer_version'] == 'old'
    assert result.hits[0].page.dataset_version == 'old'
    assert result.enough_evidence


def test_strict_and_legacy_expanded_remain_old_only():
    r = VersionedRetriever(*versions())
    for mode in ('strict', 'expanded'):
        result = r.search(QUESTION, mode=mode)
        assert result.hits and all(h.page.dataset_version == 'old' for h in result.hits)
    assert all(h.strict_eligible for h in r.search(QUESTION).hits)


def test_comparison_cannot_synthesize_two_incomplete_versions():
    pages = make_test_corpus().pages
    old = make_corpus(pages[0], pages[2])
    new = make_corpus(replace(pages[1], dataset_version=NEW_VERSION))
    result = VersionedRetriever(old, new).search(Q, mode='new_first', top_k=10)
    assert result.diagnostics['answer_version'] == 'none'
    assert not result.enough_evidence and not result.evidence_hits


def test_no_evidence_never_calls_model():
    result, client = ask(VersionedRetriever(make_corpus(), make_corpus()))
    assert result.status == 'insufficient' and client.calls == 0
    assert not result.citations


def test_new_model_answer_pending_not_verified_and_prompt_sources_true():
    result, client = ask(VersionedRetriever(*versions()))
    assert client.calls == 1 and result.status == 'ok'
    assert result.verification_status == 'unverified' and result.source_review_pending
    assert result.verification_layers['claim_support']['ok']
    assert not result.verification_layers['source_review']['ok']
    assert {e['dataset_version'] for e in result.evidence_context} == {NEW_VERSION}
    assert all(e['filename'] == '同名.pdf' and e['page_number'] == 3 for e in result.evidence_context)
    assert '新版·当前考试' in client.last_messages[1]['content']
    assert 'PDF 第 3 页' in client.last_messages[1]['content']
    assert '第 17 页' not in client.last_messages[1]['content']
    assert '新版·当前考试' in result.answer


def test_old_supplement_retains_old_review_state_and_original_page():
    result, _ = ask(VersionedRetriever(*versions('无关内容：古典音乐与作曲史。')))
    assert result.verification_status == 'verified' and not result.source_review_pending
    assert '旧版·补充' in result.answer and result.citations[0].page.page_number == 17


@pytest.mark.parametrize('content', [
    structured_answer('工程风险包括技术因素。', [('工程风险包括技术因素。', ['S999'])]),
    structured_answer('事故造成999人死亡。', [('事故造成999人死亡。', ['S1'])]),
    'not a JSON object',
])
def test_invalid_new_generation_never_gets_pending_only_shortcut(ui, content):
    app, _ = ui
    result, _ = ask(VersionedRetriever(*versions()), content)
    assert result.verification_status in ('unverified', 'failed')
    assert not result.source_review_pending
    assert app.compact_exam_answer(result) is None


def test_pending_compact_label_warning_and_full_answer_retained(ui):
    app, records = ui
    result, _ = ask(VersionedRetriever(*versions()))
    compact = app.compact_exam_answer(result)
    assert compact and '[S1]' in compact['points'][0]
    app.render_answer(result)
    assert ('subheader', '笔试精简草稿（新版来源待审核）', ()) in records
    assert not any(kind == 'success' and '通过逐条' in text for kind, text, scope in records)
    assert any(kind == 'warning' and '不是 VERIFIED' in text and not scope for kind, text, scope in records)
    assert ('markdown', result.answer, ('详细分析（原始完整答案）',)) in records
    assert any(kind == 'warning' and '引用与事实校验通过，但新版来源待审核' in text
               for kind, text, scope in records)
    assert any(kind == 'markdown' and '新版·当前考试' in text and '物理第3页' in text
               for kind, text, scope in records)


def test_release_reset_only_clears_answers_and_diagnostics(ui):
    app, _ = ui
    state = dict(last_answer='stale', last_api_diagnostic='stale', daily_budget_cny=2, ai_enabled=True)
    app.reset_release_session(state)
    assert 'last_answer' not in state and 'last_api_diagnostic' not in state
    assert state['daily_budget_cny'] == 2 and state['ai_enabled']
    state['last_answer'] = 'fresh'
    app.reset_release_session(state)
    assert state['last_answer'] == 'fresh'


def test_same_filename_two_versions_download_correctly_and_reject_traversal(tmp_path):
    old, new = versions()
    assert source_pdf(old.pages[0], tmp_path) == tmp_path / 'data/pdfs/同名.pdf'
    assert source_pdf(new.pages[0], tmp_path) == tmp_path / 'data/pdfs_new/同名.pdf'
    with pytest.raises(ValueError):source_pdf(replace(new.pages[0], filename='../../outside.pdf'), tmp_path)
    # Identical text and file identity in two versions must still have separate block IDs.
    assert page_id(old.pages[0]) != page_id(replace(old.pages[0], dataset_version=NEW_VERSION))


@pytest.mark.parametrize('old_text,new_text', [
    ('事故结果\n事故造成10人死亡，多人受伤，具体事故结果以调查报告为准。',
     '事故结果\n事故造成12人死亡，多人受伤，具体事故结果以调查报告为准。'),
    ('安全隐患处理\n发现安全隐患应当停止施工，并及时记录发现的问题及其处理结果。',
     '安全隐患处理\n发现安全隐患应当继续施工，并及时记录发现的问题及其处理结果。'),
])
def test_conflict_warning_does_not_merge_versions(old_text, new_text):
    old, new = versions(new_text)
    old = make_corpus(replace(old.pages[0], text=old_text))
    question = '事故结果是什么？' if '死亡' in old_text else '安全隐患如何处理？'
    r = VersionedRetriever(old, new)
    result = r.search(question, mode='new_first')
    assert potential_conflicts(r.new.search(question,mode='expanded').hits,
                               r.old.search(question,mode='expanded').hits)
    assert result.diagnostics['conflicts']
    assert len({h.page.dataset_version for h in result.evidence_hits}) <= 1


def test_readonly_dense_cache_and_mismatched_content_rejected(tmp_path):
    _, corpus = versions()
    encoder = Encoder()
    path = tmp_path/'new.sqlite3'
    DenseIndex(corpus.pages, encoder, 'mock', path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    cached = DenseIndex.from_cache(corpus.pages, encoder, 'mock', path)
    assert cached.status['cache_hits'] == 1 and cached.status['encoded_blocks'] == 0
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    with pytest.raises(ValueError):
        DenseIndex.from_cache([replace(corpus.pages[0], text='changed')], encoder, 'mock', path)
    with pytest.raises(FileNotFoundError):
        DenseIndex.from_cache(corpus.pages, encoder, 'mock', tmp_path/'missing.sqlite3')


def test_dense_failure_keeps_bm25_version_priority():
    class Broken:
        def search(self, *a):raise ValueError('mock')
    indexes = {v:(Broken(), dict(state='failed')) for v in ('old', NEW_VERSION)}
    result = VersionedRetriever(*versions(), indexes=indexes).search(QUESTION, mode='new_first')
    assert result.enough_evidence and result.hits[0].page.dataset_version == NEW_VERSION
    assert all(not d['dense_enabled'] for d in result.diagnostics['versions'].values())


@pytest.mark.parametrize('fault', ['none', 'pdf_changed', 'json_changed', 'review_inherited', 'bad_id'])
def test_release_manifest_guards_source_identity_and_review_boundaries(tmp_path, fault):
    import json
    from src.corpus import CorpusError
    from tests.helpers import write_document, record
    olddir = tmp_path/'data/processed_v3';olddir.mkdir(parents=True)
    write_document(olddir, '旧.pdf', [record(1,TEXT,category='A',filename='旧.pdf')])
    pdfdir = tmp_path/'data/pdfs_new';pdfdir.mkdir()
    raw = b'synthetic-pdf-bytes';digest=hashlib.sha256(raw).hexdigest()
    (pdfdir/'新.pdf').write_bytes(raw)
    directory = tmp_path/'data/processed_exam_2026';directory.mkdir()
    identifier = 'wrong' if fault == 'bad_id' else digest
    path = write_document(directory, '新.pdf', [record(1,TEXT,filename='新.pdf',doc_id=identifier,
                         category='A' if fault=='review_inherited' else None)],doc_id=identifier)
    manifest = dict(page_count=1,documents=[dict(filename='新.pdf',sha256=digest,page_count=1,
                    json_filename=path.name,json_sha256=hashlib.sha256(path.read_bytes()).hexdigest())])
    mf=tmp_path/'data/versions/exam_2026.json';mf.parent.mkdir()
    mf.write_text(json.dumps(manifest))
    if fault == 'pdf_changed':(pdfdir/'新.pdf').write_bytes(b'changed')
    if fault == 'json_changed':path.write_text('{}')
    if fault == 'none':
        old,new=load_versions(tmp_path)
        assert old.pages[0].strict_eligible and not new.pages[0].strict_eligible
        assert new.pages[0].dataset_version == NEW_VERSION
    else:
        with pytest.raises(CorpusError):load_versions(tmp_path)


def test_mock_main_defaults_to_hybrid_and_does_not_load_real_runtime(ui, monkeypatch, tmp_path):
    from contextlib import nullcontext
    app, records = ui
    old, new = versions()
    retriever = VersionedRetriever(old, new)
    settings = Settings(api_state_path=tmp_path/'synthetic_ledger.sqlite3')
    def runtime():return settings,retriever.corpus,retriever
    monkeypatch.setattr(app,'load_runtime',runtime)
    fake = app.st
    fake.session_state = dict(last_answer='stale')
    fake.sidebar = nullcontext()
    for name in ('set_page_config','title','header','divider','link_button','dataframe'):
        setattr(fake,name,lambda *a,**kw:None)
    choices=[]
    def radio(label, *, options,index,**kw):
        choices.append(options[index]);return options[index]
    fake.radio=radio
    fake.slider=lambda *a,**kw:kw['value']
    fake.number_input=lambda *a,**kw:kw['value']
    fake.toggle=lambda *a,**kw:False
    fake.button=lambda *a,**kw:False
    fake.form=lambda *a,**kw:nullcontext()
    fake.text_area=lambda *a,**kw:''
    fake.form_submit_button=lambda *a,**kw:False
    app.main()
    assert choices == [QA_MODE_HYBRID]
    assert 'last_answer' not in fake.session_state
