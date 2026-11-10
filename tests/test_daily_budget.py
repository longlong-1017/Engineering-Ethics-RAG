"""合成usage与Mock传输，不使用本地配置/真实账本。"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import sqlite3

import pytest
import requests

from src.api_limits import RequestLimiter, Prices, usage_cost
from src.config import Settings
from src.deepseek_client import DeepSeekClient, DeepSeekError
from tests.test_deepseek_client import FakeSession, FakeResponse


@pytest.fixture
def config(tmp_path):
    return Settings(deepseek_api_key='synthetic-budget-test',api_enabled=True,
                    api_state_path=tmp_path/'synthetic.sqlite3')


def client(config,usage=None,error=None,status=200):
    response=FakeResponse(status_code=status,payload={
        'choices':[{'message':{'content':'模拟摘录 [S1]'},'finish_reason':'stop'}],
        'usage':usage if usage is not None else {'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}})
    transport=FakeSession(response=response,error=error)
    return DeepSeekClient(config,session=transport),transport


def call(c):return c.chat([{'role':'user','content':'合成测试'}],allow_api=True)


def test_continuous_questions_have_no_daily_count_limit(config):
    c,s=client(replace(config,max_requests=1))  # 旧参数也不得重新开启次数上限
    for _ in range(30):call(c)
    stats=c.limiter.stats(config)
    assert len(s.calls)==30 and stats['attempts']==30
    assert stats['total_tokens']==3600 and stats['prompt_tokens']==3000 and stats['completion_tokens']==600
    assert stats['known_estimate_cny']==pytest.approx(30*(100*2+20*8)/1e6)
    assert stats['unknown_calls']==0 and stats['protected_cny']==0


def test_default_budget_two_yuan_stops_next_call_at_limit(config):
    c,s=client(config,usage={'prompt_tokens':1_000_000,'completion_tokens':0,'total_tokens':1_000_000})
    result=call(c)
    assert result.accounting['estimated_cny']==2 and config.daily_budget_cny==2
    with pytest.raises(DeepSeekError,match='预算'):call(c)
    assert len(s.calls)==1 and c.limiter.used()==1


def test_configurable_price_and_cache_discount(config):
    cfg=replace(config,price_input_cny_per_m=3.,price_output_cny_per_m=9.,price_cache_hit_cny_per_m=.5)
    c,_=client(cfg,usage={'prompt_tokens':1000,'completion_tokens':200,'total_tokens':1200,
                        'prompt_cache_hit_tokens':400,'prompt_cache_miss_tokens':600})
    result=call(c)
    assert result.accounting['estimated_cny']==pytest.approx((600*3+400*.5+200*9)/1e6)
    assert '不是账单' in result.accounting['note']


@pytest.mark.parametrize('usage',[{}, {'total_tokens':12}, {'prompt_tokens':30},
    {'prompt_tokens':30,'completion_tokens':2,'total_tokens':999},
    {'prompt_tokens':30,'completion_tokens':2,'prompt_cache_hit_tokens':31}])
def test_incomplete_or_inconsistent_usage_is_unknown_not_free(config,usage):
    c,_=client(config,usage=usage)
    result=call(c)
    assert result.accounting['cost_status']=='unknown' and result.accounting['estimated_cny'] is None
    stats=c.limiter.stats(config)
    assert stats['unknown_calls']==1 and stats['protected_cny']>0


@pytest.mark.parametrize('status,error',[(401,None),(402,None),(429,None),(200,requests.Timeout())])
def test_failed_unknown_cost_retains_hold_and_never_auto_retries(config,status,error):
    c,s=client(config,usage={},status=status,error=error)
    with pytest.raises(DeepSeekError) as exc:call(c)
    assert len(s.calls)==1 and exc.value.accounting['cost_status']=='unknown'
    assert '未知' in str(exc.value)
    assert c.limiter.stats(config)['unknown_calls']==1
    assert c.limiter.stats(config)['protected_cny']>0


def test_http_failure_with_returned_usage_is_accounted(config):
    c,_=client(config,status=429)
    with pytest.raises(DeepSeekError) as exc:call(c)
    assert exc.value.accounting['cost_status']=='estimated'
    assert c.limiter.stats(config)['total_tokens']==120


def test_returned_usage_counted_even_for_truncated_answer(config):
    c,s=client(config)
    s.response._payload['choices'][0]['finish_reason']='length'
    with pytest.raises(DeepSeekError) as exc:call(c)
    assert exc.value.accounting['cost_status']=='estimated'
    assert c.limiter.stats(config)['total_tokens']==120


def test_concurrent_cost_reservations_cannot_oversubscribe(config):
    cfg=replace(config,daily_budget_cny=.024)
    def reserve(_):
        try:RequestLimiter(cfg.api_state_path).reserve(cfg,0,1000);return True
        except Exception as exc:
            from src.api_limits import LimitError
            assert isinstance(exc,LimitError);return False
    with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(reserve,range(12)))
    assert sum(results)==3
    assert RequestLimiter(cfg.api_state_path).stats(cfg)['protected_cny']==pytest.approx(.024)


def test_legacy_counts_survive_and_missing_usage_is_explicit(config):
    with sqlite3.connect(config.api_state_path) as db:
        db.execute('CREATE TABLE daily_requests (day TEXT PRIMARY KEY, attempts INTEGER NOT NULL)')
        db.execute('INSERT INTO daily_requests VALUES (?,?)',(RequestLimiter._day(),1))
    c,s=client(config)
    before=c.limiter.stats(config)
    assert before['legacy_unknown_calls']==1 and before['unknown_calls']==1
    assert before['total_tokens']==0 and before['protected_cny']>0
    call(c)
    after=c.limiter.stats(config)
    assert after['attempts']==2 and after['legacy_unknown_calls']==1
    assert after['total_tokens']==120 and len(s.calls)==1


def test_cost_settles_on_request_day_across_midnight(config,monkeypatch):
    ledger=RequestLimiter(config.api_state_path)
    monkeypatch.setattr(ledger,'_day',lambda:'2030-01-01')
    ticket=ledger.reserve(config,0,1000)
    monkeypatch.setattr(ledger,'_day',lambda:'2030-01-02')
    ledger.settle(ticket,{'prompt_tokens':10,'completion_tokens':20})
    assert ledger.stats(config)['attempts']==0
    monkeypatch.setattr(ledger,'_day',lambda:'2030-01-01')
    assert ledger.stats(config)['known_estimate_cny']>0 and ledger.stats(config)['protected_cny']==0


def test_settlement_idempotent_and_price_changes_do_not_reprice_history(config):
    ledger=RequestLimiter(config.api_state_path)
    ticket=ledger.reserve(config,0,1000)
    usage={'prompt_tokens':100,'completion_tokens':20}
    ledger.settle(ticket,usage);ledger.settle(ticket,usage)
    new=replace(config,price_input_cny_per_m=20,price_output_cny_per_m=80,price_cache_hit_cny_per_m=.4)
    assert ledger.stats(new)['known_estimate_cny']==pytest.approx(.00036)
    assert ledger.stats(new)['attempts']==1


def test_budget_configuration_never_reads_local_config(monkeypatch):
    monkeypatch.setattr('src.config.load_local_env',lambda:(_ for _ in ()).throw(AssertionError('禁止加载配置')))
    cfg=Settings.from_env(env={'DEEPSEEK_DAILY_BUDGET_CNY':'2.5','DEEPSEEK_PRICE_INPUT_CNY_PER_M':'4',
                              'DEEPSEEK_PRICE_OUTPUT_CNY_PER_M':'10','DEEPSEEK_PRICE_CACHE_HIT_CNY_PER_M':'1',
                              'DEEPSEEK_MAX_REQUESTS':'1'})
    assert cfg.daily_budget_cny==2.5 and cfg.prices==Prices(4,10,1) and cfg.max_requests is None
