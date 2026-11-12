"""隔离临时目录的展示/双版本回归；复用禁止凭据、生产数据和HTTP的守卫。"""
from pathlib import Path
import runpy
import tempfile

ROOT = Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT / 'tests/run_api_diagnostics.py'), run_name='safe_setup')

if __name__ == '__main__':
    import pytest
    with tempfile.TemporaryDirectory(prefix='dual_diagnostic_', dir=ROOT / 'tests') as temporary:
        raise SystemExit(pytest.main([
            '-q', '-p', 'no:cacheprovider', '--basetemp', str(Path(temporary) / 'work'),
            'tests/test_dual_versions.py', 'tests/test_compact_display.py',
            'tests/test_corpus.py', 'tests/test_pdf_loader.py',
            'tests/test_bm25.py', 'tests/test_text_utils.py',
        ]))
