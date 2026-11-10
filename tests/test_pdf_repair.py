"""真实课件回归：只允许已审查页面变化，其他页面所有既有字段保持不变。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pymupdf
import pytest

from src.pdf_loader import extract_pdf
from src.pdf_repair import TARGETS, export_v2, nonspace_counter, repair_document, rotated_reading_order


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def corpus():
    originals, repaired = {}, {}
    for path in (ROOT / 'data/processed').glob('*.json'):
        original = json.loads(path.read_text(encoding='utf-8'))
        prefix = original['filename'][:2]
        originals[prefix] = original
        repaired[prefix] = repair_document(original, ROOT / 'data/pdfs' / original['filename'])
    assert len(originals) == 10
    return originals, repaired


@pytest.mark.parametrize(('number', 'anchors'), [
    (15, ['3、工程教育认证', 'G6 工程与社会', '能够基于', 'G7 环境和可持续发展', '能够理解和评价', 'G8 职业规范', '具有人文', '电子信息工程学院']),
    (21, ['四、国内外工程伦理', '教育发展']),
    (29, ['国外的工程伦理学研究与教育', '美\n国', '•3', '为相关思考的依据', '•4', '•5', '的使命', '•6', '是否有违反', '电子信息工程学院']),
])
def test_reviewed_reading_order_and_all_characters_preserved(corpus, number, anchors):
    originals, repaired = corpus
    before, after = originals['00']['pages'][number-1], repaired['00']['pages'][number-1]
    positions = [after['text'].index(anchor) for anchor in anchors]
    assert positions == sorted(positions)
    assert after['text'] != before['text']
    assert nonspace_counter(after['text']) == nonspace_counter(before['text'])
    assert after['original_text'] == before['text']
    assert after['repair_status'] == 'reading_order_repaired_assistant_visual_checked'


@pytest.mark.parametrize(('prefix', 'number'), [('01', 40), ('09', 37), ('10', 56), ('10', 63)])
def test_image_text_is_not_invented_or_marked_fixed(corpus, prefix, number):
    originals, repaired = corpus
    before, after = originals[prefix]['pages'][number-1], repaired[prefix]['pages'][number-1]
    assert after['text'] == before['text'] == after['original_text']
    assert after['repair_status'] == 'unresolved_ocr_or_manual_candidate'
    assert after['warnings'] and 'OCR' in after['repair_note']


def test_hidden_text_is_quarantined_but_recoverable(corpus):
    originals, repaired = corpus
    before, after = originals['07']['pages'][0], repaired['07']['pages'][0]
    assert '工程伦理' in before['text']
    assert after['text'] == ''
    assert after['original_text'] == before['text']
    assert after['status'] == 'visibility_quarantined'
    assert after['repair_status'] == 'quarantined_pending_manual_confirmation'
    with pymupdf.open(ROOT / 'data/pdfs' / originals['07']['filename']) as doc:
        page = doc[0]
        log = page.get_bboxlog()
        cover = [(i, pymupdf.Rect(box)) for i, (kind, box) in enumerate(log)
                 if kind == 'fill-image' and i > 13 and pymupdf.Rect(box).height > page.rect.height * .9]
        assert len(cover) == 2
        for span in page.get_texttrace():
            rect = pymupdf.Rect(span['bbox'])
            pieces = [rect & box for i, box in cover if i > span['seqno']]
            union_area = sum(r.get_area() for r in pieces) - (pieces[0] & pieces[1]).get_area()
            assert union_area >= rect.get_area() * .99


def test_all_599_non_target_pages_keep_every_original_field(corpus):
    originals, repaired = corpus
    preserved = 0
    for prefix, before in originals.items():
        for old, new in zip(before['pages'], repaired[prefix]['pages']):
            if old['page_number'] in TARGETS.get(before['document_id'], {}):
                continue
            assert all(new[key] == value for key, value in old.items())
            assert new['repair_status'] == 'unchanged_not_reassessed'
            preserved += 1
    assert preserved == 599


def test_all_607_pages_keep_source_metadata_and_method(corpus):
    originals, repaired = corpus
    count = 0
    for prefix, before in originals.items():
        after = repaired[prefix]
        assert after['page_count'] == before['page_count']
        for old, new in zip(before['pages'], after['pages']):
            for key in ('filename', 'document_id', 'page_number'):
                assert old[key] == new[key]
            assert new['extraction_method']
            count += 1
    assert count == 607


def test_original_objects_are_not_mutated(corpus):
    originals, _ = corpus
    original = originals['00']
    snapshot = deepcopy(original)
    repair_document(original, ROOT / 'data/pdfs' / original['filename'])
    assert original == snapshot


def test_changed_original_text_is_rejected(corpus):
    originals, _ = corpus
    changed = deepcopy(originals['00'])
    changed['pages'][14]['text'] = 'unexpected text'
    with pytest.raises(ValueError, match='原JSON文本'):
        repair_document(changed, ROOT / 'data/pdfs' / changed['filename'])


def test_wrong_document_hash_is_rejected(corpus):
    originals, _ = corpus
    changed = deepcopy(originals['00'])
    changed['document_id'] = '0' * 64
    with pytest.raises(ValueError, match='内容哈希'):
        repair_document(changed, ROOT / 'data/pdfs' / changed['filename'])


def test_sources_match_quality_audit_hashes():
    hashes = json.loads((ROOT / 'reports/pdf_quality/source_hashes.json').read_text(encoding='utf-8'))
    assert len(hashes) == 20
    for path, expected in hashes.items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected


def test_export_is_utf8_and_refuses_overwrite(tmp_path):
    output = tmp_path / 'v2'
    exported = export_v2(ROOT / 'data/processed', ROOT / 'data/pdfs', output)
    assert len(exported) == len(list(output.glob('*.json'))) == 10
    snapshots = {p: p.read_bytes() for p in output.glob('*.json')}
    for path in snapshots:
        record = json.loads(path.read_text(encoding='utf-8'))
        assert record in exported
        assert '\u5de5' in path.read_text(encoding='utf-8')
    with pytest.raises(FileExistsError):
        export_v2(ROOT / 'data/processed', ROOT / 'data/pdfs', output)
    assert all(p.read_bytes() == content for p, content in snapshots.items())


def test_lookalike_page_is_not_repaired_without_reviewed_hash(tmp_path):
    path = tmp_path / '00_TEST_ONLY.pdf'
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 60), 'TEST ONLY')
        page.set_rotation(90)
        doc.save(path)
    original = extract_pdf(path)
    repaired = repair_document(original, path)
    assert repaired['pages'][0]['text'] == original['pages'][0]['text']
    assert repaired['pages'][0]['repair_status'] == 'unchanged_not_reassessed'


def test_rotation_strategy_rejects_unreviewed_orientation():
    with pymupdf.open() as doc:
        page = doc.new_page()
        with pytest.raises(ValueError, match='90度'):
            rotated_reading_order(page)
