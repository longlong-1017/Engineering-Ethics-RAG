"""双版本纯本地验收；不创建客户端、不加载配置、不修改旧索引。"""
from prepare_exam_version import ROOT  # 同时启用网络/凭据访问阻断
from pathlib import Path
import hashlib
import json
from src.versioned_corpus import load_versions, load_version_indexes, VersionedRetriever, source_pdf
from src.evidence import plan_evidence


def run(output='local_results.json'):
    if not output.startswith('local_results') or Path(output).name != output or not output.endswith('.json'):
        raise ValueError('仅允许输出本目录local_results*.json文件')
    old, new = load_versions()
    indexes = load_version_indexes(old, new)
    retriever = VersionedRetriever(old, new, indexes=indexes)
    rows = []
    for question in ['工程伦理中的功利主义与义务论有什么区别？',
                     '工程师回避利益冲突的五种方式有哪些？']:
        modes = {}
        for mode in ('strict', 'expanded', 'new_first'):
            result = retriever.search(question, mode=mode, top_k=10)
            quotes = plan_evidence(question, result.evidence_hits).quotes
            if mode == 'strict':
                assert all(h.strict_eligible and h.page.dataset_version == 'old' for h in result.hits)
            assert len({h.rank for h in result.hits}) == len(result.hits)
            for h in result.hits:
                path = source_pdf(h.page)
                assert path.is_file()
                assert hashlib.sha256(path.read_bytes()).hexdigest() == h.page.document_id
            modes[mode] = dict(enough_evidence=result.enough_evidence,
                               diagnostics=result.diagnostics,
                               top10=[h.to_dict() for h in result.hits],
                               evidence=[dict(version=h.page.dataset_version, filename=h.page.filename,
                                              page_number=h.page.page_number, rank=h.rank, text=t) for h, t in quotes])
        rows.append(dict(question=question, results=modes))
    payload = dict(old=old.stats(), new=new.stats(),
                   indexes={v: status for v, (_, status) in indexes.items()}, questions=rows)
    directory = ROOT / 'reports/dual_version_acceptance'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / output).open('x', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps(dict(old=old.stats(), new=new.stats(), indexes=payload['indexes']), ensure_ascii=False))
    for row in rows:
        for mode, result in row['results'].items():
            print(json.dumps(dict(question=row['question'], mode=mode, sufficient=result['enough_evidence'],
                                  answer_version=result['diagnostics'].get('answer_version'),
                                  top5=[(h['version_label'],h['filename'],h['page_number']) for h in result['top10'][:5]],
                                  evidence=[(e['version'],e['filename'],e['page_number']) for e in result['evidence']]), ensure_ascii=False))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='local_results.json')
    run(parser.parse_args().output)
