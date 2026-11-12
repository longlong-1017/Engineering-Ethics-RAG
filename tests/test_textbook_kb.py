"""教材独立分块、审核边界和缓存回归；全用合成资料/Mock编码器。"""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

import pymupdf
import pytest

from src.textbook_kb import (sha,packed,section_heading,make_chunks,embed_text,build_dataset,
                             load_blocks,TextbookVectors,TextbookRetriever)


def paragraph(text='工程风险需要预防，工程师应当重视公众安全。',chapter=1,section='1.1',topic='',page=1,pid='p1'):
    return dict(text=text,chapter=chapter,chapter_title=f'第{chapter}章',section_id=section,
                section_title='工程风险' if chapter==1 else '工程责任',section_identification='synthetic',
                topic_heading=topic,paragraph_id=pid,quality_review_pending=True,
                source=dict(filename='任意名称.pdf',document_sha256='synthetic',physical_page=page,
                            printed_page=None,printed_page_candidates=[1],printed_page_inferred=32,
                            printed_page_status='candidate_conflicts_with_offset',page_mapping_review='pending',bboxes=[]))


def test_no_cross_chapter_section_or_topic_and_print_conflicts_preserved():
    parts=[paragraph(),paragraph(chapter=2,section='2.1',pid='p2'),
           paragraph(chapter=2,section='2.2',pid='p3'),paragraph(chapter=2,section='2.2',topic='安全',pid='p4')]
    blocks=make_chunks(parts)
    assert len(blocks)==4
    assert all(b['review_status']=='UNVERIFIED' and not b['strict_eligible'] and b['source_priority']==3 for b in blocks)
    assert all(b['sources'][0]['printed_page'] is None and b['sources'][0]['printed_page_candidates']==[1] for b in blocks)


def test_long_paragraph_token_limit_and_lossless_split():
    text='工程师应当重视公众安全。'*60
    blocks=make_chunks([paragraph(text)],token_count=len,max_tokens=90,max_chars=350)
    assert len(blocks)>1 and all(b['token_count']<=90 for b in blocks)
    assert ''.join(b['text'] for b in blocks)==text
    assert len({b['block_id'] for b in blocks})==len(blocks)
    spans=[s for b in blocks for s in b['paragraph_spans']]
    assert spans[0]['start']==0 and spans[-1]['end']==len(text)


@pytest.mark.parametrize('text,chapter,expected',[
    ('1.05 亿元，',1,None),('11.1 .2',11,None),('2.1.1 工程风险的来源',1,None),
    ('2.1.1 工程风险的来源',2,'2.1.1'),('11. 2. 1 环境工程中的生产安全',11,'11.2.1'),
    ('工程风险的来源',2,'2.1'),
])
def test_section_identification_does_not_invent_titles(text,chapter,expected):
    result=section_heading(text,chapter,{'2.1':'工程风险的来源'})
    assert (result[0] if result else None)==expected


class Encoder:
    def __init__(self):self.calls=[]
    def encode(self,texts):
        self.calls.extend(texts)
        return [[1,float('风险' in text)+.1] for text in texts]


def test_incremental_cache_reuses_content_and_isolates_models(tmp_path):
    blocks=make_chunks([paragraph(),paragraph('工程责任包括对社会的责任。',chapter=2,section='2.1',pid='p2')])
    path=tmp_path/'cache.sqlite3';enc=Encoder()
    first=TextbookVectors(blocks,enc,'mock',path,build=True)
    assert first.encoded==2
    again=TextbookVectors(blocks,enc,'mock',path,build=True)
    assert again.cache_hits==2 and again.encoded==0 and len(enc.calls)==2
    changed=make_chunks([paragraph('工程风险需要定期评估。'),paragraph('工程责任包括对社会的责任。',chapter=2,section='2.1',pid='p2')])
    delta=TextbookVectors(changed,enc,'mock',path,build=True)
    assert delta.encoded==1 and delta.cache_hits==1
    other=TextbookVectors(changed,enc,'other-model',path,build=True)
    assert other.encoded==2
    before=path.read_bytes();TextbookVectors(changed,enc,'mock',path)
    assert path.read_bytes()==before


def test_identical_chunks_encode_once_but_keep_distinct_source_ids(tmp_path):
    a=make_chunks([paragraph(pid='p1'),paragraph(pid='p2',page=2)],max_chars=35)
    assert len(a)==2 and a[0]['block_id']!=a[1]['block_id']
    index=TextbookVectors(a,Encoder(),'mock',tmp_path/'cache.sqlite3',build=True)
    assert index.encoded==1 and len(index.vectors)==1


@pytest.mark.parametrize('fault',['missing','corrupt','stale','nonfinite'])
def test_bad_cache_rejected_without_modifying_it(tmp_path,fault):
    blocks=make_chunks([paragraph()]);path=tmp_path/'cache.sqlite3';encoder=Encoder()
    if fault=='missing':
        with pytest.raises(FileNotFoundError):TextbookVectors(blocks,encoder,'mock',path)
        assert not path.exists();return
    if fault=='corrupt':path.write_bytes(b'broken')
    else:
        TextbookVectors(blocks,encoder,'mock',path,build=True)
        if fault=='stale':blocks=make_chunks([paragraph('正文内容已经改变。')])
        else:
            with sqlite3.connect(path) as db:db.execute("UPDATE embeddings SET vector='[NaN,1]'")
    before=path.read_bytes()
    with pytest.raises((ValueError,sqlite3.Error)):TextbookVectors(blocks,encoder,'mock',path)
    assert path.read_bytes()==before


def test_retrieval_bm25_dense_fallback_and_strict_boundary(tmp_path):
    blocks=make_chunks([paragraph(),paragraph('伦理责任是工程师对社会应尽的责任。',chapter=2,section='2.1',pid='p2')])
    dense=TextbookVectors(blocks,Encoder(),'mock',tmp_path/'cache.sqlite3',build=True)
    result=TextbookRetriever(blocks,dense).search('工程风险')
    assert result['mode']=='bm25+bge+rrf' and result['dense_enabled']
    assert result['original_query_weight']==2
    assert result['hits'][0]['block']['chapter']==1
    assert all(h['score_type']=='rrf' and h['review_status']=='UNVERIFIED' for h in result['hits'])
    assert not TextbookRetriever(blocks,dense).search('工程风险',strict=True)['hits']
    class Broken:
        def scores(self,*args):raise ValueError('synthetic')
    fallback=TextbookRetriever(blocks,Broken()).search('工程风险')
    assert fallback['hits'] and not fallback['dense_enabled'] and all(h['dense_cosine'] is None for h in fallback['hits'])
    filtered=TextbookRetriever(blocks).search('责任',chapter=2)
    assert filtered['hits'] and all(h['block']['chapter']==2 for h in filtered['hits'])


def test_expanded_concept_cannot_displace_direct_original_question(tmp_path):
    blocks=make_chunks([paragraph('工程风险包含技术风险与环境风险。'),
                       paragraph('工程师的伦理责任要求履行社会责任。',chapter=2,section='2.1',pid='p2')])
    dense=TextbookVectors(blocks,Encoder(),'mock',tmp_path/'cache.sqlite3',build=True)
    for index in (None,dense):
        result=TextbookRetriever(blocks,index).search('工程风险')
        assert '工程师的伦理责任' in result['queries']
        assert result['hits'][0]['block']['chapter']==1


@pytest.fixture
def fixture_dataset(tmp_path):
    pdfs=tmp_path/'pdfs';pdfs.mkdir();scan=tmp_path/'scan';scan.mkdir()
    files=[];pages=[]
    for chapter,name in [(1,'任意甲.pdf'),(2,'任意乙.pdf')]:
        with pymupdf.open() as doc:
            page=doc.new_page();page.insert_text((50,110),f'{chapter}.1 工程风险',fontname='china-s',fontsize=12)
            page.insert_text((74,150),'工程凤险需要预防，安全管理需要明确责任。',fontname='china-s',fontsize=11)
            page.insert_text((74,180),'工程师应当维护公众利益并及时报告隐患。',fontname='china-s',fontsize=11)
            page.insert_text((50,250),'参考文献',fontname='china-s',fontsize=12)
            page.insert_text((50,280),'不应进入正文的参考文献内容。',fontname='china-s',fontsize=11)
            doc.save(pdfs/name)
        raw=(pdfs/name).read_bytes();digest=sha(raw)
        with pymupdf.open(pdfs/name) as doc:text=doc[0].get_text('text',sort=True)
        files.append(dict(filename=name,sha256=digest,page_count=1,status='scan_only_not_imported'))
        pages.append(dict(filename=name,physical_page=1,document_sha256=digest,text_sha256=sha(text),
                          chapter=chapter,content_type='mixed_body_references',issues=['OCR待检查'],
                          print_candidates=[1],printed_page_observed=None,printed_page_inferred=9,
                          printed_page_status='candidate_conflicts_with_offset'))
    manifest=dict(files=files,page_count=2,chapters=[dict(chapter=1,title='工程风险'),dict(chapter=2,title='工程责任')])
    (scan/'scan_manifest.json').write_text(packed(manifest));(scan/'page_index.json').write_text(packed(pages))
    return pdfs,scan,tmp_path/'dataset',manifest


def test_build_uses_scan_identity_excludes_references_and_keeps_repairs_local(fixture_dataset):
    pdfs,scan,out,manifest=fixture_dataset
    repair=dict(filename='任意甲.pdf',physical_page=1,document_sha256=manifest['files'][0]['sha256'],
                before='工程凤险',after='工程风险',expected_count=1,basis='synthetic visual fixture')
    result=build_dataset(pdfs,scan,out,token_count=len,max_tokens=512,repairs=[repair])
    assert result['page_count']==2 and set(result['chapter_counts'])=={1,2}
    assert result['applied_repair_count']==1 and len(result['page_conflicts'])==2
    blocks,loaded=load_blocks(out)
    assert {b['chapter'] for b in blocks}=={1,2}
    assert all('不应进入正文' not in b['text'] for b in blocks)
    assert '工程风险需要' in ''.join(b['text'] for b in blocks if b['chapter']==1)
    assert '工程凤险需要' in ''.join(b['text'] for b in blocks if b['chapter']==2)
    rawpages=json.loads((out/'pages.json').read_text())
    assert all('工程凤险' in p['original_text'] for p in rawpages)
    assert all(s['printed_page'] is None and s['printed_page_candidates']==[1] for b in blocks for s in b['sources'])
    with pytest.raises(FileExistsError):build_dataset(pdfs,scan,out,token_count=len,max_tokens=512)


def test_changed_pdf_or_repair_provenance_is_rejected(fixture_dataset):
    pdfs,scan,out,manifest=fixture_dataset
    bad=dict(filename='任意甲.pdf',physical_page=1,document_sha256='wrong',before='凤险',after='风险')
    with pytest.raises(ValueError):build_dataset(pdfs,scan,out,token_count=len,max_tokens=512,repairs=[bad])
    (pdfs/'任意甲.pdf').write_bytes(b'changed')
    with pytest.raises(ValueError):build_dataset(pdfs,scan,out,token_count=len,max_tokens=512)
    assert not out.exists()


@pytest.mark.parametrize('tamper',['content','status'])
def test_dataset_tampering_and_review_escalation_rejected(fixture_dataset,tamper):
    pdfs,scan,out,manifest=fixture_dataset
    build_dataset(pdfs,scan,out,token_count=len,max_tokens=512)
    blocks=json.loads((out/'blocks.json').read_text())
    if tamper=='content':blocks[0]['text']='被修改的正文'
    else:blocks[0]['review_status']='VERIFIED';blocks[0]['strict_eligible']=True
    (out/'blocks.json').write_text(packed(blocks))
    if tamper=='status':
        m=json.loads((out/'manifest.json').read_text());m['file_hashes']['blocks.json']=sha((out/'blocks.json').read_bytes());(out/'manifest.json').write_text(packed(m))
    with pytest.raises(ValueError):load_blocks(out)
