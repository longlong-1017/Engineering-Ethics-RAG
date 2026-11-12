"""DeepSeek 客户端：默认禁用、逐次授权、有界请求、脱敏错误、无自动重试。"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence
from urllib.parse import urlsplit

import requests

from src.api_limits import LimitError, RequestLimiter
from src.config import Settings


class DeepSeekError(RuntimeError):
    """只包含固定错误说明，不能带服务端正文或敏感异常。"""

    def __init__(self, message, *, code='blocked', attempted=False,
                 quota_consumed=False, http_status=None, usage=None, accounting=None):
        super().__init__(message)
        self.code = code
        self.attempted = attempted
        self.quota_consumed = quota_consumed
        self.http_status = http_status
        self.usage = usage or {}
        self.accounting = accounting or {}


@dataclass(frozen=True)
class ChatResult:
    content: str
    model: str
    usage: dict[str, Any]
    accounting: dict[str, Any] = field(default_factory=dict)


class DeepSeekClient:
    def __init__(self, settings: Settings | None = None, *, session: requests.Session | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self._session = session or requests.Session()
        if session is None:
            # 不使用隐式 netrc 认证；requests 默认不重试 POST。
            self._session.trust_env = False
        self.limiter = RequestLimiter(self.settings.api_state_path)

    @property
    def configured(self) -> bool:
        return self.settings.deepseek_configured

    @property
    def endpoint(self) -> str:
        return f'{self.settings.deepseek_base_url.rstrip("/")}/chat/completions'

    def chat(self, messages: Sequence[dict[str, str]], *, temperature: float = 0.2,
             max_tokens: int = 900, allow_api: bool = False) -> ChatResult:
        api_key = self.settings.deepseek_api_key
        if not api_key:
            raise DeepSeekError('未配置 DEEPSEEK_API_KEY，无法调用 DeepSeek API')
        if not self.settings.api_enabled or not allow_api:
            raise DeepSeekError('API 总开关未开启或本次未授权调用；未发送请求。')
        if self.settings.deepseek_model not in ('deepseek-flash', 'deepseek-v4-pro'):
            raise DeepSeekError('DEEPSEEK_MODEL 不在已核对的官方模型列表中；请核对官方文档后配置，未发送请求。')
        if not isinstance(temperature, (int,float)) or not math.isfinite(temperature) or not 0 <= temperature <= 2:
            raise ValueError('temperature 必须为0到2的有限数值')
        try:
            endpoint = urlsplit(self.settings.deepseek_base_url)
        except ValueError:
            raise DeepSeekError('DeepSeek 地址配置无效；未发送请求。') from None
        if (endpoint.scheme != 'https' or endpoint.netloc != 'api.deepseek.com'
                or endpoint.path.rstrip('/') not in ('', '/v1') or endpoint.query or endpoint.fragment):
            raise DeepSeekError('仅允许官方 HTTPS DeepSeek 地址（可含 /v1）；未发送请求。')
        if not messages or any(not isinstance(m, dict) or m.get('role') not in ('system', 'user', 'assistant')
                               or not isinstance(m.get('content'), str) for m in messages):
            raise ValueError('messages 必须是有效的非空文本消息列表')
        if sum(len(m['content']) for m in messages) > self.settings.max_input_chars:
            raise DeepSeekError('证据输入超过本地字符上限；未截断证据或发送请求，请减少证据页。')
        if not isinstance(max_tokens, int) or max_tokens <= 0:
            raise ValueError('max_tokens 必须是正整数')
        payload = dict(model=self.settings.deepseek_model, messages=list(messages), temperature=temperature,
                       max_tokens=min(max_tokens, self.settings.max_output_tokens), stream=False,
                       thinking={'type': 'disabled'})
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json', 'Accept': 'application/json'}
        # 预留仅是预算保护，不是账单或实际token统计。
        input_bound=sum(len(m['content'].encode('utf-8')) + 64 for m in messages) + 256
        try:
            ticket=self.limiter.reserve(self.settings,input_bound,payload['max_tokens'])
        except LimitError as exc:
            raise DeepSeekError(str(exc),code=exc.code) from None
        usage={}
        try:
            try:
                response=self._session.post(self.endpoint,headers=headers,json=payload,
                    timeout=(self.settings.connect_timeout_seconds,self.settings.timeout_seconds),allow_redirects=False)
            except requests.Timeout:
                raise DeepSeekError('DeepSeek连接或读取超时；用量和费用未知，不自动重试。',code='timeout',attempted=True,quota_consumed=True) from None
            except requests.RequestException:
                raise DeepSeekError('DeepSeek网络请求失败；用量和费用未知，不自动重试。',code='network_error',attempted=True,quota_consumed=True) from None
            try:
                data=response.json()
            except ValueError:
                data=None
            raw_usage=data.get('usage') if isinstance(data,dict) else None
            usage={key:value for key,value in (raw_usage.items() if isinstance(raw_usage,dict) else [])
                if key in ('prompt_tokens','completion_tokens','total_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens')
                and isinstance(value,int) and not isinstance(value,bool) and 0<=value<=1_000_000_000}
            if not 200 <= response.status_code < 300:
                hints={401:'认证失败',402:'账户余额不足',429:'服务端限流',400:'请求格式错误',422:'参数错误',500:'服务端错误',503:'服务暂不可用'}
                raise DeepSeekError(f'DeepSeek API返回HTTP {response.status_code}：{hints.get(response.status_code,"请求未成功或重定向已拒绝")}；不自动重试。',
                    code='http_error',attempted=True,quota_consumed=True,http_status=response.status_code)
            if not isinstance(data,dict):
                raise DeepSeekError('DeepSeek API返回结构异常或不是合法 JSON',code='invalid_response',attempted=True,quota_consumed=True)
            choices=data.get('choices')
            if not isinstance(choices,list) or not choices:
                raise DeepSeekError('DeepSeek API未返回任何回答',code='invalid_response',attempted=True,quota_consumed=True)
            first=choices[0] if isinstance(choices[0],dict) else {}
            finish_reason = first.get('finish_reason')
            if finish_reason == 'length':
                raise DeepSeekError(
                    'DeepSeek 输出达到 max_tokens 上限（finish_reason=length），回答被截断；'
                    '未采用不完整答案，不自动重试。',
                    code='output_truncated', attempted=True, quota_consumed=True,
                )
            if finish_reason not in (None, 'stop'):
                raise DeepSeekError(
                    f'DeepSeek 未正常结束（finish_reason={finish_reason}），拒绝不完整答案；不自动重试。',
                    code='finish_reason', attempted=True, quota_consumed=True,
                )
            message=first.get('message')
            content=message.get('content') if isinstance(message,dict) else None
            if not isinstance(content,str) or not content.strip():
                raise DeepSeekError('DeepSeek API返回了空回答',code='empty_response',attempted=True,quota_consumed=True)
        except DeepSeekError as exc:
            exc.usage=usage
            exc.accounting=self._settle(ticket,usage)
            if exc.accounting['cost_status']=='unknown' and '未知' not in str(exc):
                exc.args=(str(exc)+' 用量不完整，费用未知；保留保护预留。',)
            raise
        accounting=self._settle(ticket,usage)
        return ChatResult(content=content.strip().replace(api_key,'[REDACTED]'),model=self.settings.deepseek_model,
                          usage=usage,accounting=accounting)

    def _settle(self,ticket,usage):
        try:
            return self.limiter.settle(ticket,usage)
        except LimitError as exc:
            raise DeepSeekError(str(exc),code='accounting_error',attempted=True,quota_consumed=True,
                usage=usage,accounting={'cost_status':'unknown','estimated_cny':None,'note':'用量记录失败，费用未知，保留保护预留。'}) from None
