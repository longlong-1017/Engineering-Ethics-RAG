"""本地只读审查源 PDF/JSON；审查产物排他写入 reports/pdf_quality/。"""

import csv
import hashlib
import json
import random
import re
import shutil
import subprocess
import math
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/pdf_quality"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, data):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def compact(text):
    return re.sub(r"\s+", "", text)


def main():
    OUT.mkdir(exist_ok=False)
    (OUT / "previews").mkdir()
    sources = sorted((ROOT / "data/pdfs").glob("*"))
    sources = [p for p in sources if p.suffix.lower() == ".pdf"]
    jsons = sorted((ROOT / "data/processed").glob("*.json"))
    baseline = {str(p.relative_to(ROOT)): digest(p) for p in sources + jsons}
    write_json(OUT / "source_hashes.json", baseline)
    records = [json.loads(p.read_text(encoding="utf-8")) for p in jsons]
    assert len(records) == len(sources) == 10, "源文件或 JSON 数量不符"
    assert len({r['filename'] for r in records}) == len(records)
    rows, docs, samples, no_text, texts = [], [], [], [], {}
    rng = random.Random(20261108)
    line_pages = defaultdict(set)
    for source in sources:
        record = next(r for r in records if r['filename'] == source.name)
        assert record['document_id'] == digest(source)
        assert record['schema_version'] == 1 and not record['errors']
        code = source.name[:2]
        with pymupdf.open(source) as doc:
            assert len(doc) == record['page_count'] == len(record['pages'])
            assert [p['page_number'] for p in record['pages']] == list(range(1, len(doc) + 1))
            eligible = [p['page_number'] for p in record['pages'] if p['text'].strip()]
            chosen = sorted(rng.sample(eligible, 3))
            image_frequency = Counter()
            for page in doc:
                image_frequency.update({i['digest'] for i in page.get_image_info(hashes=True)})
            common_images = {key for key, count in image_frequency.items() if count >= max(3, math.ceil(len(doc) * .5))}
            for number, page in enumerate(doc, 1):
                saved = record['pages'][number - 1]
                assert saved['document_id'] == record['document_id'] and saved['filename'] == source.name
                text = page.get_text('text', sort=True)
                assert text == saved['text'], f"文本不匹配: {source.name} p{number}"
                key = f'{code}-p{number:03}'
                texts[key] = text
                clean = compact(text)
                images = page.get_image_info(hashes=True)
                drawings = page.get_drawings()
                image_area = min(1.0, sum((pymupdf.Rect(i['bbox']) & page.rect).get_area() for i in images) / page.rect.get_area())
                content_image_area = min(1.0, sum((pymupdf.Rect(i['bbox']) & page.rect).get_area() for i in images if i['digest'] not in common_images) / page.rect.get_area())
                blocks = [b for b in page.get_text('blocks') if b[6] == 0 and len(compact(b[4])) >= 8]
                side_by_side = any(
                    min(a[3], b[3]) - max(a[1], b[1]) > 10
                    and (a[2] + 10 < b[0] or b[2] + 10 < a[0])
                    for i, a in enumerate(blocks) for b in blocks[i + 1:]
                )
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                single_ratio = sum(len(l) <= 2 for l in lines) / max(1, len(lines))
                suspicious = Counter(c for c in text if c == '\ufffd' or unicodedata.category(c) in {'Co', 'Cs'} or (unicodedata.category(c) == 'Cc' and c not in '\n\r\t'))
                reasons = []
                if not clean:
                    reasons.append('无文本')
                elif len(clean) < 30:
                    reasons.append('文本异常短候选(<30非空白字符)')
                if suspicious or re.search(r'\(cid:\d+\)', text):
                    reasons.append('疑似乱码/异常编码')
                if single_ratio > .35 and len(clean) >= 80:
                    reasons.append('短行碎片化/阅读顺序风险')
                if side_by_side:
                    reasons.append('并排文本块/阅读顺序风险')
                if content_image_area >= .12 or len(drawings) >= 10 or sum(c in '∑∫√≤≥±αβγδθλμσπ∞≈' for c in text) >= 2:
                    reasons.append('图表/公式/图片内容可能未被纯文本保留')
                if len(text) >= 100 and 1 - len(clean) / len(text) > .6:
                    reasons.append('空白字符占比过高(>60%)')
                row = dict(key=key, filename=source.name, page_number=number,
                           chars=len(text), nonspace_chars=len(clean), chinese_chars=sum('\u4e00' <= c <= '\u9fff' for c in text),
                           status=saved['status'], image_count=len(images), image_area_ratio=round(image_area, 4),
                           content_image_area_ratio=round(content_image_area, 4),
                           drawing_count=len(drawings), single_line_ratio=round(single_ratio, 3),
                           suspicious_codepoints=' '.join(f'U+{ord(c):04X}:{n}' for c, n in suspicious.items()),
                           flags='；'.join(reasons), text_match=True)
                rows.append(row)
                for line in set(lines):
                    if len(compact(line)) >= 6:
                        line_pages[line].add(key)
                if not clean or number in chosen:
                    preview = OUT / 'previews' / f'{key}.png'
                    renderer = shutil.which('pdftoppm')
                    if renderer:
                        subprocess.run([renderer, '-f', str(number), '-l', str(number), '-r', '120', '-singlefile', '-png', str(source), str(preview.with_suffix(''))], check=True, capture_output=True)
                    else:
                        page.get_pixmap(dpi=150, alpha=False).save(preview)
                    item = dict(key=key, filename=source.name, page_number=number,
                                preview=str(preview.relative_to(ROOT / 'reports')), text=text,
                                renderer='Poppler pdftoppm 120dpi' if renderer else 'PyMuPDF 150dpi')
                    (no_text if not clean else samples).append(item)
            subset = [r for r in rows if r['filename'] == source.name]
            docs.append(dict(filename=source.name, code=code, pages=len(doc), chars=sum(r['chars'] for r in subset),
                             text_pages=len(eligible), no_text_pages=[r['page_number'] for r in subset if not r['nonspace_chars']],
                             sample_pages=chosen))
    exact = defaultdict(list)
    shingles = {}
    for key, text in texts.items():
        normalized = re.sub(r'[\W\d_]+', '', text)
        if len(normalized) >= 40:
            exact[normalized].append(key)
        if len(normalized) >= 80:
            shingles[key] = {normalized[i:i+5] for i in range(len(normalized)-4)}
    duplicates = [keys for keys in exact.values() if len(keys) > 1]
    near = []
    items = list(shingles.items())
    for i, (key, a) in enumerate(items):
        for other, b in items[i+1:]:
            if min(len(a), len(b)) / max(len(a), len(b)) < .85:
                continue
            score = len(a & b) / len(a | b)
            if .85 <= score < 1:
                near.append(dict(pages=[key, other], jaccard=round(score, 3)))
    repeat_keys = {key for group in duplicates for key in group} | {k for pair in near for k in pair['pages']}
    for row in rows:
        if row['key'] in repeat_keys:
            row['flags'] += ('；' if row['flags'] else '') + '疑似重复内容'
    repeated_lines = [dict(text=l, pages=sorted(pages), count=len(pages)) for l, pages in line_pages.items() if len(pages) >= 10]
    repeated_lines.sort(key=lambda r: -r['count'])
    with (OUT / 'page_metrics.csv').open('x', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    data = dict(seed=20261108, documents=docs, pages=rows, samples=samples, no_text=no_text,
                duplicates=duplicates, near_duplicates=near, repeated_lines=repeated_lines)
    write_json(OUT / 'audit_results.json', data)
    for group_name, entries in [('no_text', no_text), ('samples', samples)]:
        for start in range(0, len(entries), 4):
            with pymupdf.open() as montage:
                sheet = montage.new_page(width=2000, height=1550)
                for pos, item in enumerate(entries[start:start+4]):
                    x, y = (pos % 2)*1000, (pos // 2)*775
                    sheet.insert_text((x+20, y+25), item['key'], fontsize=20)
                    sheet.insert_image(pymupdf.Rect(x+10, y+40, x+990, y+765), filename=str(ROOT / 'reports' / item['preview']))
                sheet.get_pixmap().save(OUT / f'{group_name}_{start//4+1:02}.png')
    assert all(digest(ROOT / path) == sha for path, sha in baseline.items()), '源文件被改变'
    print(json.dumps(dict(documents=docs, pages=len(rows), no_text=len(no_text), samples=len(samples),
                          flag_counts=dict(Counter(flag for r in rows for flag in r['flags'].split('；') if flag)),
                          duplicates=duplicates, near_duplicates=near), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
