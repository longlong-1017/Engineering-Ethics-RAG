"""v3实料回归：来源、局部修改边界、历史修复与待确认状态。"""

from copy import deepcopy
from collections import Counter
import hashlib
import json
from pathlib import Path

import pytest

from src.pdf_review import ROOT, export_v3, load_reviews, review_document
from src.pdf_repair import nonspace_counter


@pytest.fixture(scope='module')
def reviewed_corpus():
    reviews = load_reviews()
    originals, results = {}, {}
    for path in (ROOT/'data/processed_v2').glob('*.json'):
        original = json.loads(path.read_text(encoding='utf-8'))
        prefix = original['filename'][:2]
        originals[prefix] = original
        results[prefix] = review_document(original, ROOT/'data/pdfs'/original['filename'], reviews)
    return originals, results, reviews


def test_ten_documents_607_pages_sources_and_page_numbers(reviewed_corpus):
    originals, results, _ = reviewed_corpus
    assert len(results) == 10
    assert sum(len(d['pages']) for d in results.values()) == 607
    for prefix, before in originals.items():
        after = results[prefix]
        assert before['page_count'] == after['page_count']
        assert after['source_dataset'] == 'processed_v2'
        assert after['repair_summary'] == dict(Counter(p['repair_status'] for p in after['pages']))
        assert after['source_v2_repair_summary'] == before['repair_summary']
        for number, (old, new) in enumerate(zip(before['pages'], after['pages']), 1):
            assert new['page_number'] == old['page_number'] == number
            for name in ('filename', 'document_id'):
                assert old[name] == new[name] == before[name]


def test_145_unique_new_reviews_exclude_46_previously_reviewed(reviewed_corpus):
    _, results, reviews = reviewed_corpus
    q = json.loads((ROOT/'reports/high_risk_review/queue.json').read_text(encoding='utf-8'))
    assert len(reviews) == len(q['queue']) == 145
    assert q['risk_pages'] == 171 and q['excluded_prior_risk_pages'] == 26
    assert len(q['prior_keys']) == 46
    assert not ({r['key'] for r in reviews.values()} & set(q['prior_keys']))
    assert sum('high_risk_review' in p for d in results.values() for p in d['pages']) == 145


def test_only_50_approved_b_pages_change_text_and_no_characters_invented(reviewed_corpus):
    originals, results, reviews = reviewed_corpus
    changed = 0
    for prefix, before in originals.items():
        for old, new in zip(before['pages'], results[prefix]['pages']):
            decision = reviews.get((old['document_id'], old['page_number']))
            if decision and decision['strategy']:
                assert decision['category'] == 'B'
                assert new['text'] != old['text']
                assert nonspace_counter(new['text']) == nonspace_counter(old['text'])
                assert new['pre_v3_text'] == old['text']
                assert new['repair_history'][-1]['source_method'] == old['extraction_method']
                assert new['high_risk_review']['repair_applied'] is True
                changed += 1
            else:
                assert new['text'] == old['text']
    assert changed == 50


def test_462_non_target_page_records_are_completely_unchanged(reviewed_corpus):
    originals, results, reviews = reviewed_corpus
    unchanged = 0
    for prefix, before in originals.items():
        for old, new in zip(before['pages'], results[prefix]['pages']):
            if (old['document_id'], old['page_number']) not in reviews:
                assert old == new
                unchanged += 1
    assert unchanged == 462


@pytest.mark.parametrize('number', [15, 21, 29])
def test_three_previous_repairs_do_not_regress(reviewed_corpus, number):
    originals, results, _ = reviewed_corpus
    before, after = originals['00']['pages'][number-1], results['00']['pages'][number-1]
    assert after == before
    assert after['repair_status'] == 'reading_order_repaired_assistant_visual_checked'
    assert after['original_text'] != after['text']


def test_e_c_and_unresolved_b_are_never_marked_repaired_or_eligible(reviewed_corpus):
    _, results, _ = reviewed_corpus
    held = 0
    for doc in results.values():
        for page in doc['pages']:
            review = page.get('high_risk_review')
            if not review:
                continue
            if review['category'] in {'C','E'} or (review['category']=='B' and not review['repair_applied']):
                assert review['disposition'] == 'hold'
                assert review['repair_applied'] is False
                assert 'pre_v3_text' not in page
                held += 1
    assert held == 52


def test_prior_quarantine_and_four_ocr_candidates_remain_unresolved(reviewed_corpus):
    originals, results, _ = reviewed_corpus
    for prefix, number in [('07',1), ('01',40), ('09',37), ('10',56), ('10',63)]:
        assert originals[prefix]['pages'][number-1] == results[prefix]['pages'][number-1]
    assert results['07']['pages'][0]['repair_status'] == 'quarantined_pending_manual_confirmation'


def test_approved_layout_anchors(reviewed_corpus):
    _, results, _ = reviewed_corpus
    text = results['10']['pages'][60]['text']
    assert text.index('其身上使用，挽救人类生命') < text.index('是第一要务') < text.index('2014年试验性抗埃博拉')
    text = results['00']['pages'][61]['text']
    assert text.index('1、克隆技术') < text.index('7、磁悬浮') < text.index('8、引黄') < text.index('14、无人机')
    text = results['06']['pages'][3]['text']
    assert text.index('•地点') < text.index('湖南省凤凰县')
    text = results['00']['pages'][16]['text']
    assert text.index('4、工程伦理教育目的') < text.index('第二') < text.index('工程伦理规范是指')
    text = results['00']['pages'][34]['text']
    compact = ''.join(text.split())
    assert compact.index('美国') < compact.index('1947') < compact.index('公众的安全')


def test_no_inplace_mutation_and_reject_stale_review_text(reviewed_corpus):
    originals, _, reviews = reviewed_corpus
    source = originals['06']
    snapshot = deepcopy(source)
    review_document(source, ROOT/'data/pdfs'/source['filename'], reviews)
    assert source == snapshot
    altered = deepcopy(source)
    altered['pages'][3]['text'] += 'unaudited change'
    with pytest.raises(ValueError, match='审查证据'):
        review_document(altered, ROOT/'data/pdfs'/source['filename'], reviews)


def test_source_pdf_json_and_v2_all_30_hashes_unchanged():
    queue = json.loads((ROOT/'reports/high_risk_review/queue.json').read_text(encoding='utf-8'))
    assert len(queue['source_hashes']) == 30
    for name, expected in queue['source_hashes'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == expected


def test_export_roundtrip_and_no_overwrite(tmp_path, reviewed_corpus):
    _, _, reviews = reviewed_corpus
    queue = json.loads((ROOT/'reports/high_risk_review/queue.json').read_text(encoding='utf-8'))
    hashes = {Path(p).name:h for p,h in queue['source_hashes'].items() if p.startswith('data/processed_v2/')}
    output = tmp_path/'processed_v3'
    results = export_v3(ROOT/'data/processed_v2', ROOT/'data/pdfs', output, reviews, hashes)
    assert len(results) == len(list(output.glob('*.json'))) == 10
    snapshot = {p:p.read_bytes() for p in output.glob('*.json')}
    for path in snapshot:
        assert json.loads(path.read_text(encoding='utf-8')) in results
    with pytest.raises(FileExistsError):
        export_v3(ROOT/'data/processed_v2', ROOT/'data/pdfs', output, reviews, hashes)
    assert all(p.read_bytes()==content for p,content in snapshot.items())
