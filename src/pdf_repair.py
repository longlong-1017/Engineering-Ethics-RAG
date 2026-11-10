"""只对已核实的文档哈希和物理页应用修复；其余页面原样保留。"""

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pymupdf


TARGETS = {
    '0a491c37060ef7f175463def3a6f3ff79406d018351df933930509a2f35965eb': {15: 'rotated_lines', 21: 'rotated_lines', 29: 'rotated_sidebar'},
    '13a4292eb210348f2f418a5ff8228926f2906947c7039524e970a2d980b8b9ea': {40: 'ocr_candidate'},
    '42d3b37228df85119c424421a7114f1b77650510d72b8014ab63bc25785ed918': {1: 'visibility_quarantine'},
    'e74dd975009f34e7499a39a2b6a393280034edf2271d94eadd54a50841021aaf': {37: 'ocr_candidate'},
    '71c1ea1f8852747751ac37359a42e0263a0c61c7fba1b42e8f3e1073c425b66c': {56: 'ocr_candidate', 63: 'ocr_candidate'},
}


def nonspace_counter(text):
    return Counter(c for c in text if not c.isspace())


def display_lines(page):
    """保留原文字，仅将dict的行框转换到实际显示坐标。"""
    lines = []
    data = page.get_text('dict', flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)
    for block in data['blocks']:
        if block['type'] != 0:
            continue
        for line in block['lines']:
            text = ''.join(span['text'] for span in line['spans']).strip()
            if text:
                box = pymupdf.Rect(line['bbox']) * page.rotation_matrix
                lines.append({'text': text, 'bbox': list(box), 'direction': list(line['dir'])})
    return lines


def rotated_reading_order(page, sidebar=False):
    """仅供已检查的90度单栏课件页使用，不作为全局阅读顺序算法。"""
    if page.rotation != 90:
        raise ValueError('目标页旋转不再为90度，拒绝套用已审查策略')
    lines = display_lines(page)
    key = lambda line: (line['bbox'][1], line['bbox'][0])
    if sidebar:
        header, label, body, footer = [], [], [], []
        for line in lines:
            x, y = line['bbox'][:2]
            if y < page.rect.height * .24:
                header.append(line)
            elif y >= page.rect.height * .82:
                footer.append(line)
            elif x < page.rect.width * .07:
                label.append(line)
            else:
                body.append(line)
        ordered = [*sorted(header, key=key), *sorted(label, key=key), *sorted(body, key=key), *sorted(footer, key=key)]
    else:
        ordered = sorted(lines, key=key)
    text = '\n'.join(line['text'] for line in ordered) + '\n'
    if nonspace_counter(text) != nonspace_counter(page.get_text('text', sort=True)):
        raise ValueError('重排行的字符集合与原提取不一致，拒绝修复')
    return text


def repair_document(original, pdf_path):
    """输出独立记录；除白名单目标页，不重新提取或替换任何正文。"""
    pdf_path = Path(pdf_path)
    content = pdf_path.read_bytes()
    document_id = hashlib.sha256(content).hexdigest()
    if document_id != original['document_id'] or pdf_path.name != original['filename']:
        raise ValueError('PDF文件名或内容哈希与原JSON不匹配')
    result = deepcopy(original)
    result['schema_version'] = 2
    result['repair_policy'] = 'reviewed_page_allowlist_v1'
    with pymupdf.open(stream=content, filetype='pdf') as doc:
        if len(doc) != original['page_count'] or len(original['pages']) != len(doc):
            raise ValueError('PDF与JSON页数不一致')
        for number, record in enumerate(result['pages'], 1):
            if (record['filename'], record['document_id'], record['page_number']) != (pdf_path.name, document_id, number):
                raise ValueError('页面来源元数据不一致')
            action = TARGETS.get(document_id, {}).get(number)
            record['extraction_method'] = 'original_json:get_text(text,sort=True)'
            record['repair_status'] = 'unchanged_not_reassessed'
            if action is None:
                continue
            page = doc[number - 1]
            if page.get_text('text', sort=True) != record['text']:
                raise ValueError(f'第{number}页原JSON文本与当前提取不一致，拒绝应用策略')
            record['original_text'] = record['text']
            record['repair_action'] = action
            if action.startswith('rotated_'):
                record['text'] = rotated_reading_order(page, sidebar=action == 'rotated_sidebar')
                record['extraction_method'] = 'dict_lines:rotation_matrix:display_y_x' + (':reviewed_sidebar_regions' if action == 'rotated_sidebar' else '')
                record['repair_status'] = 'reading_order_repaired_assistant_visual_checked'
                record['repair_note'] = '仅重排已有文字及格式空白，保留全部非空白字符；不是人工签核。'
            elif action == 'visibility_quarantine':
                # 已确认后绘制的幕布覆盖文字，但不将通用遮挡检测用于其他页面。
                record['text'] = ''
                record['status'] = 'visibility_quarantined'
                record['extraction_method'] = 'original_text_retained:reviewed_visibility_quarantine'
                record['repair_status'] = 'quarantined_pending_manual_confirmation'
                record['repair_note'] = '原提取文字保留于original_text；画面为幕布，先隔离不可见文字，等待人工确认是否纳入。不是空白页，也未执行OCR。'
                record['warnings'].append(record['repair_note'])
            else:
                record['repair_status'] = 'unresolved_ocr_or_manual_candidate'
                record['repair_note'] = '缺词区域为嵌入栅格图片；多种文字提取均无法恢复，保留原文，不补写。需局部OCR或人工补录后复核。'
                record['warnings'].append(record['repair_note'])
    result['repair_summary'] = dict(Counter(p['repair_status'] for p in result['pages']))
    return result


def export_v2(input_dir, pdf_dir, output_dir):
    """先核验全部源记录，再排他创建独立输出目录，拒绝覆盖已有结果。"""
    input_dir, pdf_dir, output_dir = map(Path, (input_dir, pdf_dir, output_dir))
    if output_dir.resolve().is_relative_to(input_dir.resolve()) or input_dir.resolve().is_relative_to(output_dir.resolve()):
        raise ValueError('输出目录必须独立于原JSON目录')
    paths = sorted(input_dir.glob('*.json'))
    if not paths:
        raise ValueError('没有原JSON，拒绝生成空输出')
    results = []
    seen = set()
    for path in paths:
        original = json.loads(path.read_text(encoding='utf-8'))
        filename = original['filename']
        if Path(filename).name != filename or filename in seen:
            raise ValueError('原JSON文件名不安全或重复')
        seen.add(filename)
        results.append((path.name, repair_document(original, pdf_dir / filename)))
    output_dir.mkdir(parents=True, exist_ok=False)
    for name, result in results:
        with (output_dir / name).open('x', encoding='utf-8') as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
    return [result for _, result in results]


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    exported = export_v2(root / 'data/processed', root / 'data/pdfs', root / 'data/processed_v2')
    print(json.dumps(dict(Counter(p['repair_status'] for d in exported for p in d['pages'])), ensure_ascii=False, indent=2))
