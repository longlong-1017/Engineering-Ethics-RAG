"""汇总未审查候选页并输出本地文字/坐标/PNG证据，不自动判定入库资格。"""

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import pymupdf

from src.pdf_repair import display_lines

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/high_risk_review'
RISK_NAMES = ('文本异常短', '阅读顺序风险', '图表/公式', '疑似重复')


def main():
    OUT.mkdir(exist_ok=False)
    (OUT / 'previews').mkdir()
    (OUT / 'evidence').mkdir()
    rows = list(csv.DictReader((ROOT / 'reports/pdf_quality/reviewed_page_metrics.csv').open(encoding='utf-8-sig')))
    risks = [row for row in rows if any(name in row['flags'] for name in RISK_NAMES)]
    prior = {row['key'] for row in rows if row['visual_review'] != '未抽查'}
    queue = [row for row in risks if row['key'] not in prior]
    queue.sort(key=lambda row: (row['filename'][:2] == '00', row['filename'], int(row['page_number'])))
    source_paths = [p for d in ['data/pdfs', 'data/processed', 'data/processed_v2'] for p in (ROOT / d).iterdir() if p.suffix.lower() in {'.pdf', '.json'}]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    manifest = dict(risk_pages=len(risks), prior_review_pages=len(prior), excluded_prior_risk_pages=len(risks)-len(queue),
                    queue=queue, prior_keys=sorted(prior), source_hashes=hashes,
                    categories={name: sum(name in r['flags'] for r in rows) for name in RISK_NAMES})
    with (OUT / 'queue.json').open('x', encoding='utf-8') as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    documents = {d['filename']: d for p in (ROOT / 'data/processed_v2').glob('*.json') for d in [json.loads(p.read_text(encoding='utf-8'))]}
    all_evidence = []
    for filename in dict.fromkeys(row['filename'] for row in queue):
        group = []
        with pymupdf.open(ROOT / 'data/pdfs' / filename) as doc:
            for row in [r for r in queue if r['filename'] == filename]:
                key, number = row['key'], int(row['page_number'])
                page = doc[number-1]
                baseline = documents[filename]['pages'][number-1]['text']
                assert baseline == page.get_text('text', sort=True)
                lines = display_lines(page)
                candidate = '\n'.join(line['text'] for line in sorted(lines, key=lambda l: (l['bbox'][1], l['bbox'][0])))+'\n'
                blocks = [b for b in page.get_text('blocks') if b[6] == 0]
                item = dict(key=key, filename=filename, document_id=documents[filename]['document_id'], page_number=number,
                            risks=row['flags'], rotation=page.rotation, original_text=baseline,
                            unsorted_text=page.get_text('text'), blocks=blocks, display_lines=lines,
                            display_candidate=candidate,
                            images=page.get_image_info(), drawing_count=len(page.get_drawings()))
                with (OUT / 'evidence' / f'{key}.json').open('x', encoding='utf-8') as handle:
                    json.dump(item, handle, ensure_ascii=False, indent=2)
                page.get_pixmap(dpi=140, alpha=False).save(OUT / 'previews' / f'{key}.png')
                group.append(item)
                all_evidence.append(item)
        for offset in range(0, len(group), 6):
            with pymupdf.open() as montage:
                sheet = montage.new_page(width=2200, height=2400)
                for pos, item in enumerate(group[offset:offset+6]):
                    x, y = pos%2*1100, pos//2*800
                    sheet.insert_text((x+15,y+25),item['key'],fontsize=22)
                    sheet.insert_image(pymupdf.Rect(x+10,y+40,x+1090,y+790),filename=str(OUT/'previews'/f"{item['key']}.png"))
                sheet.get_pixmap().save(OUT/f'{filename[:2]}_sheet_{offset//6+1:02}.png')
    with (OUT / 'text_comparisons.md').open('x', encoding='utf-8') as handle:
        for item in all_evidence:
            handle.write(f"## {item['key']}\n\n原JSON：\n\n```text\n{item['original_text']}\n```\n\n显示坐标候选（未经自动采用）：\n\n```text\n{item['display_candidate']}\n```\n\n")
    print(json.dumps(dict(risks=len(risks), prior=len(prior), excluded=len(risks)-len(queue), queue=len(queue), per_pdf=dict(Counter(r['filename'][:2] for r in queue))),ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
