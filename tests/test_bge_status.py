"""Mock Dense参与性、缓存元数据与显式降级，不加载真实配置。"""
import sqlite3
import pytest
from src.dense_index import DenseIndex,load_project_dense_status,page_id
from src.retriever import Retriever
from tests.test_retrieval_upgrade import corpus,Encoder,QUESTIONS


def test_persisted_vector_metadata_and_index_reuse(tmp_path):
    c=corpus();encoder=Encoder();path=tmp_path/'index.sqlite3'
    first=DenseIndex(c.expanded_pages,encoder,'mock',path)
    assert first.status['blocks']==7 and first.status['dimension']==2
    assert first.status['encoded_blocks']==7
    again=DenseIndex(c.expanded_pages,encoder,'mock',path)
    assert again.status['cache_hits']==7 and again.status['encoded_blocks']==0
    with sqlite3.connect(path) as db:
        rows=db.execute('SELECT id,filename,page_number,text FROM page_metadata WHERE model=?',('mock',)).fetchall()
    assert {(key,file,page,text) for key,file,page,text in rows}=={(page_id(p),p.filename,p.page_number,p.text) for p in c.expanded_pages}


def test_scores_are_labeled_and_dense_actually_runs(tmp_path):
    c=corpus();dense=DenseIndex(c.expanded_pages,Encoder(),'mock',tmp_path/'index.sqlite3')
    result=Retriever(c,dense_index=dense).search(QUESTIONS[5],top_k=5)
    d=result.diagnostics
    assert d['active_mode']=='bm25+bge+rrf' and d['dense_enabled']
    assert d['dense_hits']>0 and d['bm25_hits']>0
    assert d['vector_index']['state']=='ready'
    assert all(h.to_dict()['score_type']=='rrf' for h in result.hits)
    assert any(h.dense_score is not None for h in result.hits)
    assert all(h.dense_score is None or -1<=h.dense_score<=1.000001 for h in result.hits)


def test_corrupt_index_is_not_silently_reported_ready(tmp_path,monkeypatch):
    path=tmp_path/'bad.sqlite3';path.write_bytes(b'broken')
    c=corpus()
    def broken(_):return DenseIndex(c.expanded_pages,Encoder(),'mock',path)
    monkeypatch.setattr('src.dense_index.load_project_dense',broken)
    index,status=load_project_dense_status(c)
    assert index is None and status['state']=='failed'
    result=Retriever(c,dense_index=index,dense_status=status).search(QUESTIONS[5])
    assert result.hits and not result.diagnostics['dense_enabled']
    assert result.diagnostics['fallback'] and result.diagnostics['vector_index']['state']=='failed'


def test_query_failure_discards_partial_dense_channels():
    c=corpus()
    class Broken:
        def search(self,*args):raise RuntimeError('synthetic only')
    result=Retriever(c,dense_index=Broken()).search(QUESTIONS[5])
    assert result.hits and result.diagnostics['dense_hits']==0
    assert not result.diagnostics['dense_enabled']
    assert result.diagnostics['active_mode']=='bm25_expansion+rrf'
    assert all(h.dense_score is None for h in result.hits)
