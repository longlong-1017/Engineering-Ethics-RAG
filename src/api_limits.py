"""UTC日调用统计与本地费用预算。金额为估算，账本不保存问题/回答/凭据。

已知费用按返回usage和请求时价格计算；在途/未知用量保留保护预留。
旧版daily_requests保留，历史缺失usage按保护性上界预留，不伪造token。
"""
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
import sqlite3
import uuid

SCALE = 1_000_000_000  # 纳元，避免浮点累计误差


class LimitError(RuntimeError):
    def __init__(self, message, *, code='ledger_error'):
        super().__init__(message)
        self.code = code


def nano(cny):
    return int((Decimal(str(cny)) * SCALE).to_integral_value(rounding=ROUND_CEILING))


@dataclass(frozen=True)
class Prices:
    input: float
    output: float
    cache_hit: float

    def cost(self, prompt, completion, hit=0):
        value = ((Decimal(prompt-hit)*Decimal(str(self.input)) + Decimal(hit)*Decimal(str(self.cache_hit))
                  + Decimal(completion)*Decimal(str(self.output))) / 1_000_000)
        return nano(value)


def valid_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 1_000_000_000


def usage_cost(usage, prices):
    """只有输入/输出及缓存信息自洽时才计已知费用；缺缓存明细按未命中估算。"""
    clean = {k:v for k,v in (usage or {}).items() if valid_count(v)}
    prompt, output = clean.get('prompt_tokens'), clean.get('completion_tokens')
    if prompt is None or output is None:
        return clean, None
    total = clean.get('total_tokens')
    if total is not None and total != prompt + output:
        return clean, None
    clean['total_tokens'] = prompt + output
    hit, miss = clean.get('prompt_cache_hit_tokens'), clean.get('prompt_cache_miss_tokens')
    if hit is None and miss is not None:
        hit = prompt - miss
    if hit is None:
        hit = 0
    if not 0 <= hit <= prompt or miss is not None and hit + miss != prompt:
        return clean, None
    return clean, prices.cost(prompt, output, hit)


@dataclass(frozen=True)
class Ticket:
    id: str
    day: str
    prices: Prices


class RequestLimiter:
    """无请求次数上限；通过SQLite事务对费用预留串行化。"""
    def __init__(self, path: Path):
        self.path = Path(path)

    @staticmethod
    def _day():
        return datetime.now(timezone.utc).date().isoformat()

    @staticmethod
    def _schema(db):
        db.execute('CREATE TABLE IF NOT EXISTS daily_requests (day TEXT PRIMARY KEY, attempts INTEGER NOT NULL)')
        db.execute('''CREATE TABLE IF NOT EXISTS api_call_costs (
            id TEXT PRIMARY KEY, day TEXT NOT NULL, model TEXT NOT NULL,
            state TEXT NOT NULL, hold_nano INTEGER NOT NULL, cost_nano INTEGER,
            prompt INTEGER, output INTEGER, total INTEGER,
            input_price REAL NOT NULL, output_price REAL NOT NULL, hit_price REAL NOT NULL)''')

    @staticmethod
    def _summary(db, day, settings):
        row = db.execute('SELECT attempts FROM daily_requests WHERE day=?', (day,)).fetchone()
        attempts = int(row[0]) if row else 0
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='api_call_costs'").fetchone()
        rows = db.execute('SELECT state,hold_nano,cost_nano,prompt,output,total FROM api_call_costs WHERE day=?', (day,)).fetchall() if exists else []
        legacy = max(0, attempts-len(rows))
        # 旧请求无价格/usage，使用当前已支持模型中最高价格及最大输入输出做保护预留。
        legacy_hold = legacy * Prices(9.0, 27.0, .30).cost(settings.max_input_chars*4 + 1024, settings.max_output_tokens)
        known = sum(r[2] or 0 for r in rows)
        hold = legacy_hold + sum(r[1] for r in rows if r[0] != 'known')
        unknown = legacy + sum(r[0] == 'unknown' for r in rows)
        pending = sum(r[0] == 'pending' for r in rows)
        return dict(attempts=attempts, prompt_tokens=sum(r[3] or 0 for r in rows),
                    completion_tokens=sum(r[4] or 0 for r in rows), total_tokens=sum(r[5] or 0 for r in rows),
                    known_estimate_cny=known/SCALE, protected_cny=hold/SCALE,
                    unknown_calls=unknown, pending_calls=pending, legacy_unknown_calls=legacy,
                    occupied_nano=known+hold, budget_cny=settings.daily_budget_cny,
                    budget_blocked=known+hold >= nano(settings.daily_budget_cny))

    def stats(self, settings):
        if not self.path.exists():
            return dict(attempts=0,prompt_tokens=0,completion_tokens=0,total_tokens=0,known_estimate_cny=0.,
                        protected_cny=0.,unknown_calls=0,pending_calls=0,legacy_unknown_calls=0,
                        occupied_nano=0,budget_cny=settings.daily_budget_cny,budget_blocked=settings.daily_budget_cny <= 0)
        try:
            with closing(sqlite3.connect(self.path, timeout=3)) as db:
                db.execute('BEGIN')  # 统计在同一快照中读取
                return self._summary(db,self._day(),settings)
        except (sqlite3.Error, OSError):
            raise LimitError('费用统计账本不可读，已暂停API；仍可离线摘录。') from None

    def used(self):
        if not self.path.exists():
            return 0
        try:
            with closing(sqlite3.connect(self.path, timeout=3)) as db:
                row=db.execute('SELECT attempts FROM daily_requests WHERE day=?',(self._day(),)).fetchone()
                return int(row[0]) if row else 0
        except (sqlite3.Error,OSError):
            raise LimitError('调用统计账本不可读，已暂停API。') from None

    def reserve(self, settings, input_token_bound, output_cap):
        prices=settings.prices
        hold=prices.cost(input_token_bound,output_cap)
        day=self._day()
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with closing(sqlite3.connect(self.path,timeout=3,isolation_level=None)) as db:
                db.execute('BEGIN IMMEDIATE')
                self._schema(db)
                summary=self._summary(db,day,settings)
                occupied=summary['occupied_nano']
                if occupied+hold > nano(settings.daily_budget_cny) or summary['budget_blocked']:
                    db.rollback()
                    raise LimitError('本日估算费用/保护预留已达预算，或剩余预算不足以预留本次请求；API暂停，未发送请求，可继续离线摘录。',code='budget_exhausted')
                ticket=Ticket(uuid.uuid4().hex,day,prices)
                db.execute('INSERT INTO api_call_costs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                           (ticket.id,day,settings.deepseek_model,'pending',hold,None,None,None,None,prices.input,prices.output,prices.cache_hit))
                db.execute('INSERT INTO daily_requests VALUES (?,?) ON CONFLICT(day) DO UPDATE SET attempts=excluded.attempts',
                           (day,summary['attempts']+1))
                db.commit()
                return ticket
        except (sqlite3.Error,OSError):
            raise LimitError('费用预留账本不可写，已暂停API。') from None

    def settle(self, ticket, usage):
        clean,cost=usage_cost(usage,ticket.prices)
        try:
            with closing(sqlite3.connect(self.path,timeout=3,isolation_level=None)) as db:
                db.execute('BEGIN IMMEDIATE')
                # 幂等结算；未知费用保留保护预留，不伪装成已消费金额。
                db.execute('''UPDATE api_call_costs SET state=?,cost_nano=?,prompt=?,output=?,total=?
                              WHERE id=? AND state='pending' ''',
                           ('known' if cost is not None else 'unknown',cost,clean.get('prompt_tokens'),
                            clean.get('completion_tokens'),clean.get('total_tokens'),ticket.id))
                db.commit()
        except (sqlite3.Error,OSError):
            raise LimitError('API已尝试，但用量结算记录失败；费用未知，保留保护预留且不自动重试。') from None
        return dict(cost_status='estimated' if cost is not None else 'unknown',
                    estimated_cny=cost/SCALE if cost is not None else None,
                    note='按返回token及请求时配置单价估算，不是账单；缺少缓存明细时按未命中单价估算。' if cost is not None else
                         '用量缺失或不完整，费用未知；保留保护预留，不作为零费用。')
