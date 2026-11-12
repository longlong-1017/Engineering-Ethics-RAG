"""项目配置。密钥不进入 repr、日志、报告或页面，环境变量优先于 .env。"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from src.api_limits import Prices

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / 'data' / 'processed_v3'
DEFAULT_DEEPSEEK_BASE_URL = 'https://api.deepseek.com'
DEFAULT_DEEPSEEK_MODEL = 'deepseek-flash'
DEFAULT_TIMEOUT_SECONDS = 30.0


def load_local_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(PROJECT_ROOT / '.env', override=False)


def _number(source, name, default, minimum, maximum, cast=float):
    try:
        value = cast(source.get(name, default))
        return value if math.isfinite(value) and minimum <= value <= maximum else default
    except (ValueError, TypeError):
        return default


@dataclass(frozen=True)
class Settings:
    data_dir: Path = DEFAULT_DATA_DIR
    deepseek_api_key: str | None = field(default=None, repr=False)
    deepseek_base_url: str = DEFAULT_DEEPSEEK_BASE_URL
    deepseek_model: str = DEFAULT_DEEPSEEK_MODEL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    connect_timeout_seconds: float = 5.0
    api_enabled: bool = False
    # 兼容旧构造参数，但不读取旧次数环境配置，也不用于限制。
    max_requests: int | None = None
    daily_budget_cny: float = 2.0
    price_input_cny_per_m: float | None = None
    price_output_cny_per_m: float | None = None
    price_cache_hit_cny_per_m: float | None = None
    max_output_tokens: int = 1000
    case_max_output_tokens: int = 3600
    max_input_chars: int = 16000
    api_state_path: Path = PROJECT_ROOT / 'data/runtime/api_limits.sqlite3'

    def __post_init__(self):
        bounds = (
            (self.timeout_seconds, 1, 120), (self.connect_timeout_seconds, 1, 30),
            (self.daily_budget_cny, 0, 10000), (self.max_output_tokens, 1, 4096),
            (self.max_input_chars, 1000, 50000),
        )
        if any(isinstance(value,bool) or not isinstance(value,int) for value in (self.max_output_tokens,self.max_input_chars)):
            raise ValueError('API token和字符上限必须为整数')
        if any(not math.isfinite(value) or not low <= value <= high for value, low, high in bounds):
            raise ValueError('API 限制配置超出允许范围')
        prices=self.prices
        if not all(math.isfinite(v) and v>0 for v in (prices.input,prices.output)) or not math.isfinite(prices.cache_hit) or not 0<=prices.cache_hit<=prices.input:
            raise ValueError('估算单价须为有效人民币单价；缓存命中单价不得大于未命中单价')

    @classmethod
    def from_env(cls, data_dir: Path | str | None = None, env: dict[str, str] | None = None) -> 'Settings':
        if env is None:
            load_local_env()
        source = os.environ if env is None else env
        return cls(
            data_dir=Path(data_dir) if data_dir else DEFAULT_DATA_DIR,
            deepseek_api_key=(source.get('DEEPSEEK_API_KEY') or '').strip() or None,
            deepseek_base_url=(source.get('DEEPSEEK_BASE_URL') or DEFAULT_DEEPSEEK_BASE_URL).strip().rstrip('/'),
            deepseek_model=(source.get('DEEPSEEK_MODEL') or DEFAULT_DEEPSEEK_MODEL).strip(),
            timeout_seconds=_number(source, 'DEEPSEEK_TIMEOUT', 30.0, 1, 120),
            connect_timeout_seconds=_number(source, 'DEEPSEEK_CONNECT_TIMEOUT', 5.0, 1, 30),
            api_enabled=(source.get('DEEPSEEK_API_ENABLED') or '').strip().lower() == 'true',
            daily_budget_cny=_number(source, 'DEEPSEEK_DAILY_BUDGET_CNY', 2.0, 0, 10000),
            price_input_cny_per_m=_number(source, 'DEEPSEEK_PRICE_INPUT_CNY_PER_M', None, .000001, 100000),
            price_output_cny_per_m=_number(source, 'DEEPSEEK_PRICE_OUTPUT_CNY_PER_M', None, .000001, 100000),
            price_cache_hit_cny_per_m=_number(source, 'DEEPSEEK_PRICE_CACHE_HIT_CNY_PER_M', None, 0, 100000),
            max_output_tokens=_number(source, 'DEEPSEEK_MAX_OUTPUT_TOKENS', 1000, 1, 4096, int),
            case_max_output_tokens=_number(source, 'DEEPSEEK_CASE_MAX_OUTPUT_TOKENS', 3600, 1, 4096, int),
            max_input_chars=_number(source, 'DEEPSEEK_MAX_INPUT_CHARS', 16000, 1000, 50000, int),
        )

    @property
    def prices(self):
        # 2026-11-08官方人民币高峰价快照，故意不自动猜测节假日/空闲折扣。
        # https://api-docs.deepseek.com/zh-cn/quick_start/pricing/
        defaults=(9.0,27.0,.30) if self.deepseek_model=='deepseek-v4-pro' else (2.0,8.0,.04)
        values=(self.price_input_cny_per_m,self.price_output_cny_per_m,self.price_cache_hit_cny_per_m)
        return Prices(*(default if value is None else value for value,default in zip(values,defaults)))

    @property
    def deepseek_configured(self) -> bool:
        return bool(self.deepseek_api_key)
