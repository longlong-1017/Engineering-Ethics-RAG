"""跨来源联调合成/Mock测试，禁止凭据、生产数据和真实HTTP。"""
from pathlib import Path
import tempfile,runpy
ROOT=Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT/'tests/run_api_diagnostics.py'),run_name='safe_setup')
if __name__=='__main__':
    import pytest
    with tempfile.TemporaryDirectory(prefix='retrieval_review_',dir=ROOT/'tests') as tmp:
        raise SystemExit(pytest.main(['-q','-p','no:cacheprovider','--basetemp',str(Path(tmp)/'work'),'tests/test_retrieval_review.py']))
