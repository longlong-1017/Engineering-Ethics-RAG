"""轻量本地精确余弦索引，编码器注入。无网络、无模型自动下载。

缓存以模型标识+片段ID+文本hash为键；只重算新增或变更页。
用于数百页课件；不把余弦相似度当作证据验证。
"""
import hashlib
import json
import math
import sqlite3
from pathlib import Path


def page_id(page):
    return f'{page.document_id}:{page.filename}:{page.page_number}'


class DenseIndex:
    def __init__(self,pages,encoder,model_id,cache_path):
        self.pages={page_id(p):p for p in pages}
        self.encoder=encoder
        self.vectors={}
        self.cache_hits=0
        self.encoded_pages=0
        self.cache_path=str(Path(cache_path).resolve())
        self.model_id=model_id
        path=Path(cache_path);path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE IF NOT EXISTS vectors (model TEXT,id TEXT,hash TEXT,vector TEXT,PRIMARY KEY(model,id))')
            db.execute('CREATE TABLE IF NOT EXISTS page_metadata (model TEXT,id TEXT,filename TEXT,page_number INTEGER,text_hash TEXT,review_category TEXT,text TEXT,PRIMARY KEY(model,id))')
            missing=[]
            for key,p in self.pages.items():
                digest=hashlib.sha256(p.text.encode('utf-8')).hexdigest()
                row=db.execute('SELECT vector FROM vectors WHERE model=? AND id=? AND hash=?',(model_id,key,digest)).fetchone()
                db.execute('INSERT OR REPLACE INTO page_metadata VALUES (?,?,?,?,?,?,?)',
                           (model_id,key,p.filename,p.page_number,digest,p.review_category,p.text))
                if row:
                    self.vectors[key]=self._normalize(json.loads(row[0]));self.cache_hits+=1
                else:missing.append((key,p.text,digest))
            self.encoded_pages=len(missing)
            if missing:
                encoded=list(encoder.encode([m[1] for m in missing]))
                if len(encoded)!=len(missing):raise ValueError('Dense编码数量不匹配')
                for (key,_,digest),vector in zip(missing,encoded):
                    vector=self._normalize(vector)
                    self.vectors[key]=vector
                    db.execute('INSERT OR REPLACE INTO vectors VALUES (?,?,?,?)',(model_id,key,digest,json.dumps(vector)))
        if len({len(v) for v in self.vectors.values()})>1:raise ValueError('Dense维度不一致')

    @property
    def status(self):
        return dict(state='ready',model_id=self.model_id,index_path=self.cache_path,
                    dimension=len(next(iter(self.vectors.values()),[])),blocks=len(self.vectors),
                    cache_hits=self.cache_hits,encoded_blocks=self.encoded_pages)

    @staticmethod
    def _normalize(vector):
        values=[float(v) for v in vector]
        if not values or not all(math.isfinite(v) for v in values):raise ValueError('无效Dense向量')
        norm=math.sqrt(sum(v*v for v in values))
        if not norm:raise ValueError('Dense零向量')
        return [v/norm for v in values]

    def search(self,query,allowed_ids,top_k=10):
        q=self._normalize(list(self.encoder.encode([query]))[0])
        scores=[]
        for key in allowed_ids:
            v=self.vectors.get(key)
            if v is None:continue
            if len(v)!=len(q):raise ValueError('Dense查询维度不一致')
            score=sum(a*b for a,b in zip(q,v))
            if score>0:scores.append((key,score))
        return sorted(scores,key=lambda x:(-x[1],x[0]))[:top_k]


def load_project_dense(corpus):
    """只加载项目内已完整下载的模型；缺包/缺模型时调用方自动降级。"""
    import importlib.util
    root=Path(__file__).resolve().parents[1]
    model=root/'models/bge-small-zh-v1.5'
    if not (model/'config.json').is_file() or importlib.util.find_spec('sentence_transformers') is None:
        return None
    from sentence_transformers import SentenceTransformer
    encoder=SentenceTransformer(str(model),device='cpu',local_files_only=True,token=False,trust_remote_code=False)
    stamp=';'.join(f'{p.name}:{p.stat().st_size}:{p.stat().st_mtime_ns}' for p in sorted(model.rglob('*')) if p.is_file())
    identity='bge-small-zh-v1.5:'+hashlib.sha256(stamp.encode()).hexdigest()
    return DenseIndex(corpus.expanded_pages,encoder,identity,root/'data/retrieval_cache/vectors.sqlite3')


def load_project_dense_status(corpus):
    """不把初始化异常静默吞掉；仅暴露错误类型，不输出配置或异常原文。"""
    try:
        dense=load_project_dense(corpus)
        if dense is None:return None,dict(state='unavailable',reason='本地模型文件或可选依赖缺失')
        return dense,dense.status
    except Exception as exc:
        return None,dict(state='failed',reason='本地Dense初始化失败：'+type(exc).__name__)
