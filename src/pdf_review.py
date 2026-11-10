"""基于逐页审查白名单输出v3；分类不由字符数或图像面积自动推断。"""

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pymupdf

from src.pdf_repair import display_lines, nonspace_counter, rotated_reading_order

ROOT = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def reviewed_order(page, strategy):
    """调用者必须先验证文档哈希、目标页原文与已审查策略。"""
    if strategy == 'rotated_sidebar':
        return rotated_reading_order(page, sidebar=True)
    lines = display_lines(page)
    key = lambda line: (line['bbox'][1], line['bbox'][0])
    if strategy == 'display_lines':
        ordered = sorted(lines, key=key)
    elif strategy in {'two_columns', 'body_then_caption'}:
        top = page.rect.height * (.24 if strategy == 'two_columns' else .2)
        split = page.rect.width * .5
        header = [l for l in lines if l['bbox'][1] < top]
        body = [l for l in lines if l['bbox'][1] >= top]
        left = [l for l in body if l['bbox'][0] < split]
        right = [l for l in body if l['bbox'][0] >= split]
        ordered = sorted(header, key=key)+sorted(left, key=key)+sorted(right, key=key)
    else:
        raise ValueError('未知的已审查策略')
    text = '\n'.join(l['text'] for l in ordered)+'\n'
    if nonspace_counter(text) != nonspace_counter(page.get_text('text', sort=True)):
        raise ValueError('非空白字符不守恒，拒绝修复')
    return text


def load_reviews(root=ROOT):
    """静态笔记来自助手实际查看后的记录；证据将策略绑定到文档内容和原页文本。"""
    from scripts.high_risk_decisions import REVIEWS
    directory = Path(root) / 'reports/high_risk_review'
    queue = json.loads((directory/'queue.json').read_text(encoding='utf-8'))
    if set(REVIEWS) != {r['key'] for r in queue['queue']} or set(REVIEWS) & set(queue['prior_keys']):
        raise ValueError('审查清单与排除历史页面后的队列不一致')
    reviews = {}
    for key, decision in REVIEWS.items():
        evidence = json.loads((directory/'evidence'/f'{key}.json').read_text(encoding='utf-8'))
        reviews[(evidence['document_id'], evidence['page_number'])] = dict(
            key=key, category=decision[0], note=decision[1], strategy=decision[2] if len(decision)==3 else None,
            filename=evidence['filename'], document_id=evidence['document_id'],
            before_text_sha256=sha(evidence['original_text'].encode('utf-8')),
            evidence=f'reports/high_risk_review/evidence/{key}.json',
            preview=f'reports/high_risk_review/previews/{key}.png')
    return reviews


def review_document(source, pdf_path, reviews):
    pdf_path = Path(pdf_path)
    content = pdf_path.read_bytes()
    identifier = sha(content)
    if source['document_id'] != identifier or source['filename'] != pdf_path.name:
        raise ValueError('文档来源哈希或文件名不匹配')
    if source['schema_version'] != 2:
        raise ValueError('必须从v2生成v3，避免丢失上一轮修复')
    result = deepcopy(source)
    result['schema_version'] = 3
    result['source_dataset'] = 'processed_v2'
    result['source_v2_repair_summary'] = deepcopy(source.get('repair_summary', {}))
    result['source_v2_repair_policy'] = source.get('repair_policy')
    result['repair_policy'] = 'high_risk_review_allowlist_v3'
    with pymupdf.open(stream=content, filetype='pdf') as doc:
        if len(doc) != source['page_count'] or len(doc) != len(source['pages']):
            raise ValueError('来源页数不匹配')
        for number, record in enumerate(result['pages'], 1):
            if (record['filename'], record['document_id'], record['page_number']) != (pdf_path.name, identifier, number):
                raise ValueError('来源页码元数据不匹配')
            decision = reviews.get((identifier, number))
            if decision is None:
                continue  # 包括上一轮3页修复和全部既有待确认页：页记录整体不变。
            if decision['filename'] != pdf_path.name or sha(record['text'].encode('utf-8')) != decision['before_text_sha256']:
                raise ValueError('目标页与审查证据不匹配')
            category, strategy = decision['category'], decision['strategy']
            if category not in 'ABCDE' or len(category) != 1:
                raise ValueError('无效的审查类别')
            review = dict(category=category, note=decision['note'],
                          basis='assistant_png_and_text_coordinate_review_not_human_signoff',
                          evidence=decision['evidence'], preview=decision['preview'],
                          repair_applied=False, disposition='eligible_text' if category == 'A' else 'hold')
            if strategy:
                if category != 'B':
                    raise ValueError('只允许修复证据充分且有策略的B类页面')
                page = doc[number-1]
                if record['text'] != page.get_text('text', sort=True):
                    raise ValueError('目标页当前文字层与审查基线不匹配')
                replacement = reviewed_order(page, strategy)
                if nonspace_counter(replacement) != nonspace_counter(record['text']):
                    raise ValueError('目标页修复不能增删非空白字符')
                old_method = record['extraction_method']
                record['pre_v3_text'] = record['text']
                record['text'] = replacement
                record['extraction_method'] = f'dict_display_coordinates:reviewed_{strategy}'
                record['repair_status'] = 'reading_order_repaired_v3_assistant_visual_checked'
                record.setdefault('repair_history', []).append(dict(
                    stage='v3', before_sha256=decision['before_text_sha256'], after_sha256=sha(replacement.encode('utf-8')),
                    source_method=old_method, applied_method=record['extraction_method'], evidence=decision['evidence']))
                review.update(repair_applied=True, disposition='eligible_after_reviewed_order_repair')
            elif category == 'D':
                review['disposition'] = 'omit_noncore_decoration_or_closing'
            record['high_risk_review'] = review
    result['high_risk_review_summary'] = dict(Counter(p['high_risk_review']['category'] for p in result['pages'] if 'high_risk_review' in p))
    result['repair_summary'] = dict(Counter(p['repair_status'] for p in result['pages']))
    return result


def export_v3(input_dir, pdf_dir, output_dir, reviews, expected_hashes):
    input_dir, pdf_dir, output_dir = map(Path, (input_dir, pdf_dir, output_dir))
    for protected in (input_dir, pdf_dir):
        if output_dir.resolve().is_relative_to(protected.resolve()) or protected.resolve().is_relative_to(output_dir.resolve()):
            raise ValueError('v3必须位于独立目录')
    if output_dir.exists():
        raise FileExistsError(output_dir)
    paths = sorted(input_dir.glob('*.json'))
    if len(paths) != 10:
        raise ValueError('本次审查要求恰好10份v2文档')
    results, seen = [], set()
    for path in paths:
        if sha(path.read_bytes()) != expected_hashes[path.name]:
            raise ValueError('v2内容在审查后发生变化')
        source = json.loads(path.read_text(encoding='utf-8'))
        filename = source['filename']
        if Path(filename).name != filename or filename in seen:
            raise ValueError('源文件名不安全或重复')
        seen.add(filename)
        result = review_document(source, pdf_dir/filename, reviews)
        result['source_json'] = dict(filename=path.name, sha256=expected_hashes[path.name], dataset='processed_v2')
        results.append((path.name, result))
    if sum(r['page_count'] for _, r in results) != 607:
        raise ValueError('总页数不等于607')
    output_dir.mkdir(parents=True, exist_ok=False)
    for name, result in results:
        with (output_dir/name).open('x', encoding='utf-8') as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
    return [r for _, r in results]


if __name__ == '__main__':
    queue = json.loads((ROOT/'reports/high_risk_review/queue.json').read_text(encoding='utf-8'))
    hashes = {Path(p).name: h for p, h in queue['source_hashes'].items() if p.startswith('data/processed_v2/')}
    results = export_v3(ROOT/'data/processed_v2', ROOT/'data/pdfs', ROOT/'data/processed_v3', load_reviews(), hashes)
    print(json.dumps(dict(Counter(p['high_risk_review']['category'] for r in results for p in r['pages'] if 'high_risk_review' in p)), ensure_ascii=False))
