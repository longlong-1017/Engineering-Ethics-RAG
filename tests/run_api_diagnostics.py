"""受限诊断入口：只跑合成/Mock测试，禁止配置、生产数据/额度和真实HTTP。"""
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def deny_sensitive_files(event, args):
    if event not in ('open', 'sqlite3.connect') or not args or not isinstance(args[0], (str, bytes, Path)):
        return
    path = Path(args[0].decode() if isinstance(args[0], bytes) else args[0]).absolute()
    name = path.name
    forbidden_name = name == '.env' or name.startswith('.env.') or name.endswith('.env')
    forbidden_directory = any(part in ('.ssh', '.aws', '.azure', '.streamlit') for part in path.parts)
    if forbidden_name or forbidden_directory or path.is_relative_to(ROOT / 'data'):
        raise PermissionError('安全诊断禁止访问配置/凭据文件及生产数据或生产配额。')


sys.addaudithook(deny_sensitive_files)

import pytest
import requests
from src import config


def forbidden(*args, **kwargs):
    raise AssertionError('安全诊断禁止真实配置读取及真实HTTP请求。')


config.load_local_env = forbidden
original_from_env = config.Settings.from_env


def fake_mapping_only(cls, data_dir=None, env=None):
    if env is None:
        forbidden()
    return original_from_env(data_dir=data_dir, env=env)


config.Settings.from_env = classmethod(fake_mapping_only)
requests.sessions.Session.request = forbidden


if __name__ == '__main__':
    # 不复用/清理原pytest目录，避免触碰任何已有文件。
    with tempfile.TemporaryDirectory(prefix='api_diagnostic_', dir=ROOT / 'tests') as temporary:
        raise SystemExit(pytest.main([
            '-q', '-p', 'no:cacheprovider', '--basetemp', str(Path(temporary) / 'work'),
            'tests/test_theory_comparison.py', 'tests/test_bge_status.py', 'tests/test_claim_layers.py', 'tests/test_retrieval_upgrade.py', 'tests/test_retriever.py', 'tests/test_deepseek_client.py', 'tests/test_qa.py',
            'tests/test_phase3_evidence.py', 'tests/test_phase4_api.py',
            'tests/test_source_display.py', 'tests/test_focused_rag.py', 'tests/test_citation_validation.py', 'tests/test_qa_modes.py',
            'tests/test_api_diagnostics.py', 'tests/test_verification_states.py', 'tests/test_daily_budget.py',
            '-k', 'not dotenv and not gitignore',
        ]))
