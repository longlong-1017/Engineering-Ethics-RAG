"""只读教材验收；隔离凭据，仅编码查询，禁止生成或重算教材向量。"""
from pathlib import Path
import os
import sys

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__' and '--offline-worker' not in sys.argv:
    os.execve(str(ROOT/'.venv/bin/python'),[str(ROOT/'.venv/bin/python'),str(Path(__file__).resolve()),'--offline-worker',*sys.argv[1:]],
              dict(PATH='/usr/bin:/bin',PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
                   HF_HUB_DISABLE_TELEMETRY='1',TOKENIZERS_PARALLELISM='false',
                   HF_HOME=str(ROOT/'models/.offline_cache'),XDG_CACHE_HOME=str(ROOT/'models/.offline_cache')))

from manage_textbook_kb import ROOT, model_identity  # 同时启用凭据/网络访问阻断
import argparse
import json
import hashlib
import sqlite3

from src.textbook_kb import (DATASET,CACHE,SCAN,load_blocks,embed_text,TextbookVectors,TextbookRetriever)


def run(output):
    import pymupdf
    from tokenizers import Tokenizer
    from sentence_transformers import SentenceTransformer
    output=Path(output).resolve()
    if not output.is_relative_to(ROOT/'reports') or output.exists():
        raise ValueError('输出必须是报告目录中的新文件')
    blocks,manifest=load_blocks()
    pages=json.loads((DATASET/'pages.json').read_text('utf-8'))
    paragraphs=json.loads((DATASET/'paragraphs.json').read_text('utf-8'))
    repairs=json.loads((DATASET/'repairs.json').read_text('utf-8'))
    original=json.loads((SCAN/'page_index.json').read_text('utf-8'))
    original_index={(p['filename'],p['physical_page']):p for p in original}
    page_index={(p['filename'],p['physical_page']):p for p in pages}
    par_index={p['paragraph_id']:p for p in paragraphs}
    assert len(page_index)==len(pages)==len(original)==346
    fields=('print_candidates','printed_page_observed','printed_page_inferred','printed_page_status','chapter','content_type')
    for p in pages:
        raw=original_index[p['filename'],p['physical_page']]
        assert all(p[k]==raw[k] for k in fields)
        assert p['review_status']=='UNVERIFIED' and p['strict_eligible'] is False
        assert hashlib.sha256(p['original_text'].encode()).hexdigest()==raw['text_sha256']
    for doc in manifest['source_files']:
        content=(ROOT/'data/textbooks'/doc['filename']).read_bytes()
        assert hashlib.sha256(content).hexdigest()==doc['sha256']
        with pymupdf.open(stream=content,filetype='pdf') as pdf:
            assert len(pdf)==doc['page_count']
            for n,page in enumerate(pdf,1):
                assert page.get_text('text',sort=True)==page_index[doc['filename'],n]['original_text']
    for b in blocks:
        parts=[(par_index[s['paragraph_id']],s) for s in b['paragraph_spans']]
        assert '\n\n'.join(p['text'][s['start']:s['end']] for p,s in parts)==b['text']
        assert {p['chapter'] for p,s in parts}=={b['chapter']}
        assert {p['section_id'] for p,s in parts}=={b['section_id']}
        assert {(s['filename'],s['physical_page']) for s in b['sources']}=={(p['source']['filename'],p['source']['physical_page']) for p,s in parts}
        assert b['source_priority']==3 and not b['strict_eligible'] and b['review_status']=='UNVERIFIED'
        for source in b['sources']:
            raw=original_index[source['filename'],source['physical_page']]
            assert source['printed_page_candidates']==raw['print_candidates']
            assert source['printed_page_inferred']==raw['printed_page_inferred']
            assert source['printed_page_status']==raw['printed_page_status']
            assert source['printed_page']==(raw['printed_page_observed'] if raw['printed_page_status']=='observed_consistent_anchor' else None)
    assert {b['chapter'] for b in blocks}==set(range(13))
    assert len(manifest['page_conflicts'])==7 and len(repairs)==16
    assert sum(r['applied_count'] for r in repairs)==17
    model,identity=model_identity()
    tokenizer=Tokenizer.from_file(str(model/'tokenizer.json'));tokenizer.no_truncation()
    limit=json.loads((model/'sentence_bert_config.json').read_text())['max_seq_length']
    assert all(len(tokenizer.encode(embed_text(b)).ids)==b['token_count']<=limit for b in blocks)
    encoder=SentenceTransformer(str(model),device='cpu',local_files_only=True,token=False,trust_remote_code=False)
    class QueriesOnly:
        calls=0
        def encode(self,texts):
            if len(texts)!=1:raise AssertionError('验收禁止教材批量编码')
            if texts[0] in source_texts:raise AssertionError('验收禁止教材重新编码')
            self.calls+=1
            return encoder.encode(texts)
    source_texts={embed_text(b) for b in blocks};query_encoder=QueriesOnly()
    before=hashlib.sha256(CACHE.read_bytes()).hexdigest()
    dense=TextbookVectors(blocks,query_encoder,identity,CACHE,build=False)
    assert dense.encoded==0 and dense.cache_hits==len(source_texts)
    with sqlite3.connect(CACHE.resolve().as_uri()+'?mode=ro',uri=True) as db:
        assert db.execute('PRAGMA integrity_check').fetchall()==[('ok',)]
        total=db.execute('SELECT count(*) FROM embeddings WHERE model=?',(identity,)).fetchone()[0]
    results=[]
    questions=['工程伦理中的功利主义与义务论有什么区别？','工程风险的技术因素有哪些？',
               '环境工程中的生产安全与公共安全有什么区别？','工程师回避利益冲突的方式有哪些？',
               '工程风险的伦理评估原则有哪些？']
    for question in questions:
        row=dict(question=question,results={})
        for label,index in [('bm25',None),('hybrid',dense)]:
            result=TextbookRetriever(blocks,index).search(question,top_k=5)
            row['results'][label]=result
            assert all(h['review_status']=='UNVERIFIED' for h in result['hits'])
        results.append(row)
    assert not TextbookRetriever(blocks,dense).search(questions[0],strict=True)['hits']
    assert hashlib.sha256(CACHE.read_bytes()).hexdigest()==before
    payload=dict(dataset=str(DATASET),manifest=manifest,cache=dense.status,
                 cache_total_rows=total,inactive_historical_rows=total-len(dense.vectors),
                 cache_unchanged=True,query_encoding_calls=query_encoder.calls,
                 paragraphs=len(paragraphs),unknown_section_blocks=sum(b['section_id'] is None for b in blocks),
                 validated_physical_pages=len(pages),applied_corrections=sum(r['applied_count'] for r in repairs),
                 all_blocks_unverified=True,strict_pool_size=0,results=results)
    with output.open('x',encoding='utf-8') as f:json.dump(payload,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in payload.items() if k not in ('manifest','results')},ensure_ascii=False))
    for row in results:
        print(row['question'],[(h['block']['chapter'],h['block']['section_id'],[(s['filename'],s['physical_page']) for s in h['block']['sources']]) for h in row['results']['hybrid']['hits'][:3]])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True)
    run(p.parse_args([a for a in sys.argv[1:] if a!='--offline-worker']).output)
