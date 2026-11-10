"""不联网的API集成回归：包括配额、保密、端到端引用和网页状态。"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import traceback

import pytest
import requests

from src.api_limits import LimitError, RequestLimiter
from src.config import Settings
from src.deepseek_client import DeepSeekClient, DeepSeekError
from src.qa import AnswerEngine
from src.retriever import Retriever
from tests.helpers import make_corpus, make_page, structured_answer
from tests.test_deepseek_client import FakeResponse, FakeSession

KEY = 'synthetic-phase4-key-not-a-real-credential'


@pytest.fixture
def config(tmp_path):
    return Settings(deepseek_api_key=KEY,api_enabled=True,api_state_path=tmp_path/'limits.sqlite3')


def response(content=None, **extra):
    if content is None:
        content = structured_answer(
            '安全协议包括双方约定的应急责任和信息共享规则。',
            [('安全协议包括双方约定的应急责任和信息共享规则。', ['S1'])],
        )
    data={'choices':[{'message':{'content':content},'finish_reason':'stop'}],
          'usage':{'prompt_tokens':120,'completion_tokens':30,'total_tokens':150}}
    data.update(extra)
    return FakeResponse(payload=data)


def client(config, *, resp=None, error=None):
    session=FakeSession(response=resp or response(),error=error)
    return DeepSeekClient(config,session=session),session


@pytest.mark.parametrize('enabled,allowed',[(False,False),(False,True),(True,False)])
def test_each_permission_gate_prevents_post(config,enabled,allowed):
    c,s=client(replace(config,api_enabled=enabled))
    with pytest.raises(DeepSeekError,match='总开关'):
        c.chat([{'role':'user','content':'测试'}],allow_api=allowed)
    assert not s.calls and not config.api_state_path.exists()


@pytest.mark.parametrize('url',['http://api.deepseek.com','https://api.example.test',
    'https://api.deepseek.com.evil.test','https://api.deepseek.com@evil.test',
    'https://api.deepseek.com/path','https://api.deepseek.com?key=secret','https://[invalid'])
def test_untrusted_or_malformed_endpoint_never_sends_key(config,url):
    c,s=client(replace(config,deepseek_base_url=url))
    with pytest.raises(DeepSeekError):c.chat([{'role':'user','content':'测试'}],allow_api=True)
    assert not s.calls


def test_old_model_is_rejected_before_potential_charge(config):
    c,s=client(replace(config,deepseek_model='deepseek-chat'))
    with pytest.raises(DeepSeekError,match='模型'):c.chat([{'role':'user','content':'测试'}],allow_api=True)
    assert not s.calls


def test_budget_persists_across_clients_and_counts_timeouts(config):
    config=replace(config,daily_budget_cny=.01)
    c,s=client(config,error=requests.Timeout(KEY))
    with pytest.raises(DeepSeekError,match='超时'):c.chat([{'role':'user','content':'测试'}],allow_api=True)
    second,session=client(config)
    with pytest.raises(DeepSeekError,match='预算'):second.chat([{'role':'user','content':'测试'}],allow_api=True)
    assert len(s.calls)==1 and not session.calls
    assert RequestLimiter(config.api_state_path).used()==1


def test_concurrent_budget_reservations_are_atomic(config):
    config=replace(config,daily_budget_cny=.024)
    def reserve(_):
        try:RequestLimiter(config.api_state_path).reserve(config,0,1000);return True
        except LimitError:return False
    with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(reserve,range(12)))
    assert sum(results)==3
    assert RequestLimiter(config.api_state_path).used()==3


def test_budget_resets_on_utc_date_only(config,monkeypatch):
    config=replace(config,daily_budget_cny=.008)
    limiter=RequestLimiter(config.api_state_path)
    monkeypatch.setattr(limiter,'_day',lambda:'2026-01-01');limiter.reserve(config,0,1000)
    monkeypatch.setattr(limiter,'_day',lambda:'2026-01-02');assert limiter.used()==0
    limiter.reserve(config,0,1000)
    monkeypatch.setattr(limiter,'_day',lambda:'2026-01-01')
    with pytest.raises(LimitError):limiter.reserve(config,0,1000)


def test_corrupt_ledger_fails_closed(config):
    config.api_state_path.write_text('broken sqlite')
    c,s=client(config)
    with pytest.raises(DeepSeekError,match='账本'):c.chat([{'role':'user','content':'测试'}],allow_api=True)
    assert not s.calls


@pytest.mark.parametrize('status',[302,400,401,402,422,429,500,503])
def test_http_error_never_echoes_response_body(config,status):
    c,s=client(config,resp=FakeResponse(status_code=status,text=f'Authorization: Bearer {KEY}'))
    with pytest.raises(DeepSeekError) as exc:c.chat([{'role':'user','content':'测试'}],allow_api=True)
    assert KEY not in str(exc.value) and KEY not in ''.join(traceback.format_exception(exc.value))
    assert len(s.calls)==1


def test_network_exception_context_does_not_leak_key(config):
    c,_=client(config,error=requests.ConnectionError(f'Bearer {KEY}'))
    with pytest.raises(DeepSeekError) as exc:c.chat([{'role':'user','content':'测试'}],allow_api=True)
    assert KEY not in ''.join(traceback.format_exception(exc.value))
    assert KEY not in repr(config)


def test_limits_and_non_thinking_payload(config):
    c,s=client(replace(config,max_output_tokens=123))
    c.chat([{'role':'user','content':'测试'}],allow_api=True,max_tokens=2000)
    call=s.calls[0]
    assert call['json']['max_tokens']==123
    assert call['json']['thinking']=={'type':'disabled'}
    assert call['json']['stream'] is False and call['timeout']==(5.0,30.0)
    assert call['allow_redirects'] is False


def test_oversized_input_does_not_truncate_or_send(config):
    c,s=client(config)
    with pytest.raises(DeepSeekError,match='字符上限'):
        c.chat([{'role':'user','content':'字'*(config.max_input_chars+1)}],allow_api=True)
    assert not s.calls


def test_truncated_completion_is_not_presented_as_complete(config):
    resp=response();resp._payload['choices'][0]['finish_reason']='length'
    c,_=client(config,resp=resp)
    with pytest.raises(DeepSeekError,match='截断'):c.chat([{'role':'user','content':'测试'}],allow_api=True)


def test_response_key_and_unsafe_usage_not_returned(config):
    c,_=client(config,resp=response(content=KEY,usage={'total_tokens':10,'authorization':KEY},model=KEY))
    result=c.chat([{'role':'user','content':'测试'}],allow_api=True)
    assert KEY not in repr(result) and result.usage=={'total_tokens':10}


def test_real_engine_to_mock_http_success_and_usage(config):
    page=make_page('安全协议包括双方约定的应急责任和信息共享规则。必须定期复核执行情况。',category='A')
    c,s=client(config,resp=response(structured_answer(
        '安全协议包括双方约定的应急责任和信息共享规则。',
        [('安全协议包括双方约定的应急责任和信息共享规则。', ['S1'])],
    )))
    engine=AnswerEngine(Retriever(make_corpus(page)),settings=config,client=c)
    result=engine.answer('安全协议包括哪些？',provider='deepseek',allow_api=True)
    assert result.provider=='deepseek' and result.citations[0].page==page
    assert len(s.calls)==1 and result.usage['total_tokens']==150
    assert s.calls[0]['json']['messages'][1]['content'].find('安全协议')>=0


def test_real_engine_invalid_model_claim_falls_back_but_preserves_usage(config):
    page=make_page('安全协议包括双方约定的应急责任和信息共享规则。必须定期复核执行情况。',category='A')
    c,s=client(config,resp=response(structured_answer(
        '允许公开所有客户信息。',
        [('允许公开所有客户信息。', ['S1'])],
    )))
    result=AnswerEngine(Retriever(make_corpus(page)),settings=config,client=c).answer('安全协议包括哪些？',provider='deepseek',allow_api=True)
    assert result.provider=='deepseek'
    assert result.verification_status=='unverified'
    assert '公开所有客户信息' in result.answer
    assert result.verification_status == "unverified"
    assert result.verification_errors
    assert result.citations==()
    assert result.usage['total_tokens']==150 and len(s.calls)==1


def test_insufficient_evidence_never_spends_quota(config):
    c,s=client(config)
    result=AnswerEngine(Retriever(make_corpus(make_page('安全协议的背景介绍。',category='A'))),settings=config,client=c).answer('量子船发动机是什么？',provider='deepseek',allow_api=True)
    assert result.status=='insufficient' and not s.calls and not config.api_state_path.exists()


def test_env_configuration_bounds_and_secret_repr(monkeypatch):
    monkeypatch.setattr('src.config.load_local_env',lambda:None)
    c=Settings.from_env(env={'DEEPSEEK_API_KEY':KEY,'DEEPSEEK_TIMEOUT':'nan','DEEPSEEK_CONNECT_TIMEOUT':'inf',
                            'DEEPSEEK_MAX_REQUESTS':'-3','DEEPSEEK_MAX_OUTPUT_TOKENS':'999999','DEEPSEEK_API_ENABLED':'true'})
    assert c.api_enabled and c.timeout_seconds==30 and c.connect_timeout_seconds==5
    assert c.max_requests is None and c.max_output_tokens==1000 and KEY not in repr(c)
    assert not Settings.from_env(env={}).api_enabled


def test_dotenv_is_local_and_environment_wins(tmp_path,monkeypatch):
    monkeypatch.setattr('src.config.PROJECT_ROOT',tmp_path)
    (tmp_path/'.env').write_text('DEEPSEEK_API_KEY=synthetic-dotenv-value\nDEEPSEEK_API_ENABLED=false\n')
    monkeypatch.delenv('DEEPSEEK_API_KEY',raising=False)
    assert Settings.from_env().deepseek_api_key=='synthetic-dotenv-value'
    monkeypatch.setenv('DEEPSEEK_API_KEY',KEY)
    assert Settings.from_env().deepseek_api_key==KEY


def test_engine_word_is_not_misclassified_as_motive():
    from src.evidence import analyze_question
    assert analyze_question('发动机的结构包括哪些？').kind=='list'


def test_gitignore_protects_secrets_and_keeps_template():
    import subprocess
    root=Path(__file__).resolve().parents[1]
    for name in ('.env','.env.local','deployment.env','.streamlit/secrets.toml','.venv/bin/python','data/runtime/api_limits.sqlite3'):
        assert subprocess.run(['git','check-ignore','--no-index','--quiet',name],cwd=root).returncode==0
    assert subprocess.run(['git','check-ignore','--no-index','--quiet','.env.example'],cwd=root).returncode==1


def test_model_refusal_keeps_usage_for_cost_notice(config):
    page=make_page('安全协议包括双方约定的应急责任和信息共享规则。必须定期复核执行情况。',category='A')
    c,_=client(config,resp=response('资料不足：不能完成该问题。'))
    result=AnswerEngine(Retriever(make_corpus(page)),settings=config,client=c).answer('安全协议包括哪些？',provider='deepseek',allow_api=True)
    assert result.status=='insufficient' and result.usage['total_tokens']==150
