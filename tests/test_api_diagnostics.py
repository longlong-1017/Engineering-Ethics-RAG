"""假配置、合成语料、Mock传输与无Streamlit运行时的展示回归。"""
from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import requests

from src.api_limits import RequestLimiter
from src.config import Settings
from src.deepseek_client import DeepSeekClient
from src.qa import AnswerEngine
from src.retriever import Retriever
from tests.helpers import make_corpus, make_page, structured_answer
from tests.test_deepseek_client import FakeResponse, FakeSession


@pytest.fixture
def rig(tmp_path):
    settings = Settings(deepseek_api_key='synthetic-diagnostic-only', api_enabled=True,
                        api_state_path=tmp_path / 'isolated_test_quota.sqlite3')
    page = make_page('安全协议包括双方约定的应急责任和信息共享规则。必须定期复核执行情况。', category='A')
    return settings, Retriever(make_corpus(page))


def engine(rig, *, status=200, content=None, error=None):
    settings, retriever = rig
    if content is None:
        content = structured_answer(
            '安全协议包括双方约定的应急责任和信息共享规则。',
            [('安全协议包括双方约定的应急责任和信息共享规则。', ['S1'])],
        )
    response = FakeResponse(status_code=status, text='忽略服务端原始错误正文', payload={
        'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}],
        'usage': {'total_tokens': 123},
    })
    session = FakeSession(response=response, error=error)
    client = DeepSeekClient(settings, session=session)
    return AnswerEngine(retriever, settings=settings, client=client), session


def ask(qa, provider='deepseek', allow=True):
    return qa.answer('安全协议包括哪些？', provider=provider, allow_api=allow)


@pytest.mark.parametrize('status,timeout,content,outcome,provider', [
    (200, False, None, 'accepted', 'deepseek'),
    (401, False, None, 'http_error', 'local'),
    (402, False, None, 'http_error', 'local'),
    (429, False, None, 'http_error', 'local'),
    (200, True, None, 'timeout', 'local'),
    (200, False, structured_answer('应该完全公开客户信息。', [('应该完全公开客户信息。', ['S1'])]), 'unverified', 'deepseek'),
    (200, False, '资料不足：无法根据原文回答。', 'model_refused', 'none'),
])
def test_full_mock_chain_records_what_happened_and_never_refunds(rig, status, timeout, content, outcome, provider):
    qa, session = engine(rig, status=status, content=content, error=requests.Timeout() if timeout else None)
    result = ask(qa)
    assert len(session.calls) == 1 and result.provider == provider
    assert result.api_outcome == outcome and result.api_attempted and result.api_quota_consumed
    assert RequestLimiter(rig[0].api_state_path).used() == 1
    if status != 200:
        assert result.api_http_status == status and str(status) in result.api_reason
    if provider == 'local':
        assert '未调用大模型' not in result.answer
        assert '本次曾尝试 API' in result.answer
    if status == 200 and not timeout:
        assert result.usage == {'total_tokens': 123}
    # 将本测试的费用预算调为0，第二次不发HTTP，不重置计数。
    qa.client.settings=replace(qa.client.settings,daily_budget_cny=0)
    blocked = ask(qa)
    assert len(session.calls) == 1 and blocked.api_outcome == 'budget_exhausted'
    assert not blocked.api_attempted and not blocked.api_quota_consumed
    assert RequestLimiter(rig[0].api_state_path).used() == 1
    # 离线能力仍可使用，不会多扣次数。
    local = ask(qa, provider='local', allow=False)
    assert local.provider == 'local' and local.api_outcome == 'not_requested'
    assert RequestLimiter(rig[0].api_state_path).used() == 1


def test_reservation_uses_one_utc_day_snapshot(rig, monkeypatch):
    limiter = RequestLimiter(rig[0].api_state_path)
    days = iter(['2030-01-01', '2030-01-02'])
    monkeypatch.setattr(limiter, '_day', lambda: next(days))
    limiter.reserve(rig[0],0,1000)
    monkeypatch.setattr(limiter, '_day', lambda: '2030-01-01')
    assert limiter.used() == 1
    monkeypatch.setattr(limiter, '_day', lambda: '2030-01-02')
    assert limiter.used() == 0


@pytest.fixture
def ui(monkeypatch):
    # 不启动实际Streamlit，不读取其全局配置/凭据或任何真实语料。
    messages = []
    from contextlib import contextmanager
    @contextmanager
    def _expander(*args, **kwargs):
        yield
    fake = SimpleNamespace(cache_resource=lambda **kw: lambda f: f,
                           expander=_expander,
                           code=lambda *args, **kwargs: messages.append(('code', args[0] if args else '')))
    for name in ('success', 'warning', 'error', 'caption', 'info'):
        setattr(fake, name, lambda text, name=name: messages.append((name, text)))
    monkeypatch.setitem(sys.modules, 'streamlit', fake)
    spec = importlib.util.spec_from_file_location('safe_diagnostic_app', Path(__file__).resolve().parents[1] / 'src/app.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, messages


@pytest.mark.parametrize('status,error,outcome,widget', [
    (200, None, 'accepted', 'success'),
    (401, None, 'http_error', 'error'),
    (402, None, 'http_error', 'error'),
    (429, None, 'http_error', 'error'),
    (200, requests.Timeout(), 'timeout', 'error'),
])
def test_safe_ui_shows_last_result_separately_from_next_mode(rig, ui, status, error, outcome, widget):
    app, messages = ui
    qa, _ = engine(rig, status=status, error=error)
    result = ask(qa)
    state = {}
    app.remember_api_diagnostic(state, result)
    app.render_api_diagnostic(state['last_api_diagnostic'])
    assert any(kind == widget for kind, _ in messages)
    assert state['last_api_diagnostic']['outcome'] == outcome
    reason = app.next_submission_status(rig[0], {'budget_blocked':True})
    assert '预算' in reason and '离线摘录' in reason
    # 后续本地回答不能覆盖上次API调用结果。
    app.remember_api_diagnostic(state, ask(qa, provider='local', allow=False))
    assert state['last_api_diagnostic']['outcome'] == outcome


def test_citation_rejection_notice_is_not_api_connectivity_failure(rig, ui):
    app, messages = ui
    qa, _ = engine(rig, content=structured_answer('没有依据的改写。', [('没有依据的改写。', ['S1'])]))
    result = ask(qa)
    app.render_api_diagnostic(result.to_dict()['api_diagnostic'])
    assert any(kind == 'warning' and 'API已返回' in text and ('校验' in text or '结构化' in text) for kind, text in messages)
    assert not any(kind == 'error' for kind, _ in messages)


def test_citation_rejection_reason_is_visible(rig, ui):
    app, messages = ui
    qa, _ = engine(rig, content=structured_answer('安全协议包括双方约定的应急责任。', [('安全协议包括双方约定的应急责任。', ['S1']), ('还可以忽略所有风险。', ['S1'])]))
    result = ask(qa)
    app.render_api_diagnostic(result.to_dict()['api_diagnostic'])
    assert any(kind == 'warning' and ('未支持' in text or '未通过' in text or '结构化' in text) for kind, text in messages)


def test_broken_ledger_does_not_show_fake_zero_usage(rig, ui):
    app, _ = ui
    assert '账本不可用' in app.next_submission_status(rig[0], {}, ledger_ok=False)


def test_master_switch_is_a_hard_gate_in_status(rig, ui):
    app, _ = ui
    disabled = replace(rig[0], api_enabled=False)
    assert '总开关' in app.next_submission_status(disabled, {})


def test_fake_settings_mapping_never_loads_local_configuration(monkeypatch):
    def forbidden():
        raise AssertionError('不能加载本地配置')
    monkeypatch.setattr('src.config.load_local_env', forbidden)
    assert not Settings.from_env(env={}).deepseek_configured


def test_exhausted_quota_does_not_hide_previous_failed_attempt(rig, ui):
    app, _ = ui
    qa, _ = engine(rig, status=429)
    state = {}
    app.remember_api_diagnostic(state, ask(qa))
    app.remember_api_diagnostic(state, ask(qa))
    assert state['last_api_diagnostic']['outcome'] == 'http_error'
    assert state['last_api_diagnostic']['http_status'] == 429


def test_legacy_session_result_has_unknown_diagnostic_without_crash(ui):
    from types import SimpleNamespace
    app, _ = ui
    old = SimpleNamespace(provider='local')
    state = {}
    app.remember_api_diagnostic(state, old)
    assert not state
    assert app.answer_api_diagnostic(old)['outcome'] == 'not_requested'
