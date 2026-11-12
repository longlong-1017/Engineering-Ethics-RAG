"""独立题库安全测试入口：隔离临时目录，禁止真实配置、生产数据和HTTP。"""
from pathlib import Path
import runpy
import tempfile

ROOT = Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT / 'tests/run_api_diagnostics.py'), run_name='safe_setup')

if __name__ == '__main__':
    import pytest
    with tempfile.TemporaryDirectory(prefix='quiz_diagnostic_', dir=ROOT / 'tests') as temporary:
        raise SystemExit(pytest.main([
            '-q', '-p', 'no:cacheprovider', '--basetemp', str(Path(temporary) / 'work'),
            'tests/test_quiz_bank.py',
        ]))
