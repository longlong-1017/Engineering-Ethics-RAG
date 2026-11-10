"""仅检查8个白名单页，保留不同提取方式、坐标与绘制顺序证据。"""

import hashlib
import json
from pathlib import Path

import pymupdf

from src.pdf_repair import TARGETS, display_lines, rotated_reading_order


def main():
    root = Path(__file__).resolve().parents[1]
    out = root / 'reports/pdf_repair'
    out.mkdir(exist_ok=False)
    comparisons = []
    for path in sorted((root / 'data/pdfs').glob('*.pdf')):
        document_id = hashlib.sha256(path.read_bytes()).hexdigest()
        with pymupdf.open(path) as doc:
            for number, action in TARGETS.get(document_id, {}).items():
                page = doc[number-1]
                key = f'{path.name[:2]}-p{number:03}'
                blocks = page.get_text('blocks')
                data = page.get_text('dict', flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)
                methods = {
                    'text_sort_true': page.get_text('text', sort=True),
                    'text_sort_false': page.get_text('text', sort=False),
                    'blocks_default': '\n'.join(b[4] for b in blocks if b[6] == 0),
                    'blocks_sort_true': '\n'.join(b[4] for b in page.get_text('blocks', sort=True) if b[6] == 0),
                    'dict_default': '\n'.join(''.join(s['text'] for s in line['spans']) for b in data['blocks'] if b['type'] == 0 for line in b['lines']),
                    'infinite_clip': page.get_text('text', clip=pymupdf.INFINITE_RECT(), sort=True),
                    'ignore_actualtext': page.get_text('text', flags=pymupdf.TEXTFLAGS_TEXT | pymupdf.TEXT_IGNORE_ACTUALTEXT, sort=True),
                    'accurate_bboxes': page.get_text('text', flags=pymupdf.TEXTFLAGS_TEXT | pymupdf.TEXT_ACCURATE_BBOXES, sort=True),
                }
                if action.startswith('rotated_'):
                    methods['dict_display_coordinates'] = rotated_reading_order(page, sidebar=action == 'rotated_sidebar')
                trace = [dict(seqno=s['seqno'], type=s['type'], opacity=s['opacity'], bbox=list(s['bbox']), text=''.join(chr(c[0]) if 0 <= c[0] <= 0x10ffff else '\ufffd' for c in s['chars'])) for s in page.get_texttrace()]
                images = page.get_image_info(xrefs=True)
                for item in images:
                    item['digest'] = item['digest'].hex()
                evidence = dict(key=key, filename=path.name, document_id=document_id, page_number=number,
                                rotation=page.rotation, methods=methods, dict=data,
                                blocks=[b for b in blocks if b[6] == 0], display_lines=display_lines(page),
                                images=images, texttrace=trace, bboxlog=page.get_bboxlog())
                with (out / f'{key}.json').open('x', encoding='utf-8') as handle:
                    json.dump(evidence, handle, ensure_ascii=False, indent=2)
                # 独立渲染，便于这次修复复查，不改写上次PNG。
                page.get_pixmap(dpi=150, alpha=False).save(out / f'{key}.png')
                comparisons.append(dict(key=key, methods={name: len(''.join(text.split())) for name, text in methods.items()}))
    print(json.dumps(comparisons, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
