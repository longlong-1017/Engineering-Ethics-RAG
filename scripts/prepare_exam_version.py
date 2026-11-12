"""显式生成独立新版数据/向量，绝不覆盖旧版或已有输出。启动时须使用干净环境。"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def offline_guard(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo'):
        raise PermissionError('本地处理禁止网络')
    if event == 'open' and args and isinstance(args[0], (str, bytes)):
        path = Path(args[0].decode() if isinstance(args[0], bytes) else args[0])
        if (path.name == '.env' or path.name.startswith('.env.') or path.name.endswith('.env')
                or path.name in ('token', '.netrc', 'secrets.toml')
                or any(p in path.parts for p in ('.ssh', '.aws', '.azure'))):
            raise PermissionError('禁止访问凭据')


sys.addaudithook(offline_guard)

import hashlib
import json
from src.pdf_loader import extract_pdf, save_result


def extract():
    target = ROOT / 'data/processed_exam_2026'
    manifest = ROOT / 'data/versions/exam_2026.json'
    if target.exists() or manifest.exists():
        raise FileExistsError('新版输出已存在，拒绝覆盖')
    inputs = sorted((ROOT / 'data/pdfs_new').glob('*.pdf'))
    if len(inputs) != 5:
        raise ValueError('本次发布要求5份新版PDF')
    results = [extract_pdf(p) for p in inputs]
    if sum(r['page_count'] for r in results) != 193 or any(r['status'] in ('error', 'partial') for r in results):
        raise ValueError('新版页数或提取状态不符合预期')
    documents = []
    for result in results:
        result['dataset_version'] = 'exam_2026'
        result['schema_version'] = 3
        for page in result['pages']:
            page['dataset_version'] = 'exam_2026'
            page['extraction_method'] = 'pymupdf:text:sort_true'
            page['review_state'] = 'pending'
            page['high_risk_review'] = dict(category=None, repair_applied=False,
                                            note='新版待审核，不继承旧版审核结论', basis='unreviewed')
            if not page['text'].strip():
                page['review_state'] = 'pending_visual_inspection'
                page['warnings'].append('待视觉检查：不能仅凭无文本认定空白，未执行OCR')
        output = save_result(result, target)
        documents.append(dict(filename=result['filename'], sha256=result['document_id'],
                              page_count=result['page_count'], json_filename=output.name,
                              json_sha256=hashlib.sha256(output.read_bytes()).hexdigest()))
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open('x', encoding='utf-8') as handle:
        json.dump(dict(release='dual-exam-2026-v1', dataset_version='exam_2026',
                       page_count=193, review_state='all_pending', documents=documents),
                  handle, ensure_ascii=False, indent=2)
    print(json.dumps(documents, ensure_ascii=False))


def vectors():
    from src.versioned_corpus import load_versions
    from src.dense_index import DenseIndex
    from sentence_transformers import SentenceTransformer
    cache = ROOT / 'data/retrieval_cache/exam_2026.sqlite3'
    if cache.exists():
        raise FileExistsError('新版向量缓存已存在，拒绝覆盖')
    _, new = load_versions()
    model = ROOT / 'models/bge-small-zh-v1.5'
    encoder = SentenceTransformer(str(model), device='cpu', local_files_only=True,
                                  token=False, trust_remote_code=False)
    stamp = ';'.join(f'{p.name}:{p.stat().st_size}:{p.stat().st_mtime_ns}'
                     for p in sorted(model.rglob('*')) if p.is_file())
    model_id = 'bge-small-zh-v1.5:' + hashlib.sha256(stamp.encode()).hexdigest()
    index = DenseIndex(new.expanded_pages, encoder, model_id, cache)
    print(json.dumps(index.status, ensure_ascii=False))


if __name__ == '__main__':
    vectors() if '--vectors' in sys.argv else extract()
