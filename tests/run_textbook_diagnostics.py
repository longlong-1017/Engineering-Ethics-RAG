"""教材Mock测试：隔离临时文件，禁止真实凭据、生产数据与HTTP。"""
from pathlib import Path
import runpy
import tempfile

ROOT=Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT/'tests/run_api_diagnostics.py'),run_name='safe_setup')
if __name__=='__main__':
    import pytest
    with tempfile.TemporaryDirectory(prefix='textbook_diagnostic_',dir=ROOT/'tests') as tmp:
        raise SystemExit(pytest.main(['-q','-p','no:cacheprovider','--basetemp',str(Path(tmp)/'work'),'tests/test_textbook_kb.py']))
