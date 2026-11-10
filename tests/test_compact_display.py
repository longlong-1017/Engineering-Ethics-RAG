"""手机精简展示：只用合成答案及 Streamlit Mock，不启动配置/模型加载。"""
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def ui(monkeypatch):
    records, stack = [], []

    @contextmanager
    def expander(label, expanded=False):
        records.append(('expander', label, expanded))
        stack.append(label)
        try:
            yield
        finally:
            stack.pop()

    fake = NS(cache_resource=lambda **kw: lambda f: f, expander=expander)
    for name in ('markdown', 'caption', 'warning', 'success', 'error', 'info',
                 'subheader', 'text', 'code', 'write', 'download_button'):
        setattr(fake, name, lambda text, *args, name=name, **kw:
                records.append((name, text, tuple(stack))))
    monkeypatch.setitem(sys.modules, 'streamlit', fake)
    spec = importlib.util.spec_from_file_location(
        'safe_compact_app', Path(__file__).resolve().parents[1] / 'src/app.py')
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    # 不打开真实 PDF 或语料，来源映射使用下方合成数据。
    monkeypatch.setattr(app, 'render_evidence', lambda *a: None)
    return app, records


def answer(points=3, **changes):
    content = [
        '公众安全优先，不能以经济利益替代公众健康。[S2]',
        '【基于课件的案例分析】建议比较环境风险与社会公正。[S7]',
        '工程师责任包括报告隐患，但不等于确认事故已经发生。[S2] [S7]',
        '仅在风险已确认时采取对应措施。[S7]',
        '损失为10万元，不是100万元。[S2]',
        '第六条保留完整原文，不因精简而丢失。[S7]',
    ][:points]
    text = ('【简明答案】\n应优先保护公众健康。\n\n【分点论述】\n'
            + '\n'.join(f'{i}. {p}' for i, p in enumerate(content, 1))
            + '\n\n【总结】\n兼顾风险与公正。\n\n'
            '【AI补充（未经课件核实）】\n补充示例9999，不作为课件依据。\n\n'
            '【参考依据】\n【参考课件】\n'
            '- [S2] 合成责任.pdf第12页\n- [S7] 合成环境.pdf第39页')
    context = tuple(dict(id=ref, filename=file, page_number=page,
                         quality='来源未审核', text='合成课件内容')
                    for ref, file, page in (('S2', '合成责任.pdf', 12),
                                            ('S7', '合成环境.pdf', 39)))
    data = dict(answer=text, status='ok', verification_status='verified',
                general_knowledge=False, citations=(), evidence_context=context,
                provider='deepseek', api_attempted=False, usage=None, warnings=(),
                qa_mode_label='严格课件', source_label='合成来源',
                verification_label='已验证', provider_label='Mock',
                verification_errors=(), model_calls=0,
                search=NS(terms=('公众安全', '公众健康', '环境风险', '社会公正', '工程师责任'),
                          hits=(), diagnostics={}, pool_size=2, strict_pool_size=0,
                          expanded_pool_size=2, dropped_low_relevance=0,
                          duplicates_merged=0, evidence_warning=''))
    data.update(changes)
    return NS(**data), content


def test_extracts_verbatim_points_and_keeps_nonconsecutive_citations(ui):
    app, _ = ui
    result, points = answer()
    compact = app.compact_exam_answer(result)
    assert compact['points'] == tuple(points)
    assert compact['sources'] == (('S2', '合成责任.pdf', 12), ('S7', '合成环境.pdf', 39))
    assert 3 <= len(compact['keywords']) <= 5
    assert all(word in '\n'.join([compact['summary'], *points]) for word in compact['keywords'])
    assert '9999' not in str(compact)


@pytest.mark.parametrize('count', [1, 3, 5, 6])
def test_limits_without_padding_or_changing_numbers_and_qualifiers(ui, count):
    app, _ = ui
    result, points = answer(points=count)
    compact = app.compact_exam_answer(result)
    assert compact['points'] == tuple(points[:5])
    assert compact['omitted'] == max(0, count - 5)


@pytest.mark.parametrize('changes', [
    {'status': 'insufficient'}, {'status': 'error'},
    {'verification_status': 'unverified'}, {'verification_status': 'failed'},
    {'general_knowledge': True},
])
def test_risky_answers_never_get_compact_standard_answer(ui, changes):
    app, records = ui
    result, _ = answer(**changes)
    assert app.compact_exam_answer(result) is None
    app.render_answer(result)
    assert not any(kind == 'subheader' and text == '笔试精简答案'
                   for kind, text, _ in records)
    assert any(kind in ('warning', 'error') and not scope
               for kind, _, scope in records)


@pytest.mark.parametrize('fault', ['unknown', 'conflict', 'invalid_page', 'no_refs'])
def test_bad_source_mapping_prevents_compaction(ui, fault):
    app, _ = ui
    result, _ = answer()
    if fault == 'unknown':
        result.answer = result.answer.replace('[S7]', '[S999]')
    elif fault == 'conflict':
        result.citations = (NS(rank=2, page=NS(filename='另一文件.pdf', page_number=12)),)
    elif fault == 'invalid_page':
        result.evidence_context[0]['page_number'] = 0
    else:
        result.answer = result.answer.replace('[S2]', '').replace('[S7]', '')
    assert app.compact_exam_answer(result) is None


def test_render_keeps_full_answer_and_supplements_collapsed_and_risk_visible(ui):
    app, records = ui
    result, _ = answer(points=6)
    original = result.answer
    app.render_answer(result)
    assert result.answer == original and result.verification_status == 'verified'
    assert ('markdown', original, ('详细分析（原始完整答案）',)) in records
    for label in ('详细分析（原始完整答案）', 'AI 补充', '检索诊断', '课件来源与完整证据'):
        assert ('expander', label, False) in records
    assert any(kind == 'markdown' and '9999' in text and scope == ('AI 补充',)
               for kind, text, scope in records)
    warning = next(i for i, (kind, text, scope) in enumerate(records)
                   if kind == 'warning' and '来源未人工复核' in text and not scope)
    heading = records.index(('subheader', '笔试精简答案', ()))
    assert warning < heading
    for ref, filename, page in app.compact_exam_answer(result)['sources']:
        assert ('markdown', f'[{ref}] {filename}｜物理第{page}页', ()) in records


def test_multisentence_qualification_is_not_silently_discarded(ui):
    app, _ = ui
    result, _ = answer()
    result.answer = result.answer.replace('应优先保护公众健康。',
                                          '应优先保护公众健康。但这不等于已经确认危害。')
    assert app.compact_exam_answer(result)['summary'] == '应优先保护公众健康。但这不等于已经确认危害。'
