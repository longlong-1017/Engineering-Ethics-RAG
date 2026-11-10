"""不加载Settings，不读取凭据；仅本地检索与基准，禁止所有HTTP。"""
from pathlib import Path
import os,sys
ROOT=Path(__file__).resolve().parents[1]
if '--isolated' not in sys.argv:
    os.execve(str(ROOT/'.venv/bin/python'),[str(ROOT/'.venv/bin/python'),str(Path(__file__).resolve()),'--isolated'],
        {'PATH':'/usr/bin:/bin','HF_HOME':str(ROOT/'models/.offline_cache'),'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
         'HF_HUB_DISABLE_TELEMETRY':'1','TOKENIZERS_PARALLELISM':'false'})
sys.path.insert(0,str(ROOT))
import json,hashlib
import requests
requests.sessions.Session.request=lambda *a,**k:(_ for _ in ()).throw(AssertionError('本地评估禁止HTTP'))
from src.corpus import load_corpus
from src.retriever import Retriever
from src.dense_index import load_project_dense
from src.evidence import plan_evidence
from tests.test_retrieval_upgrade import QUESTIONS,metrics,corpus,GOLD

out=ROOT/'reports/retrieval_upgrade';out.mkdir(parents=True,exist_ok=True)
import torch,transformers,sentence_transformers
print('本地依赖导入成功',torch.__version__,transformers.__version__,sentence_transformers.__version__,flush=True)
c=load_corpus();model=load_project_dense(c)
pages={p.source_file for p in c.pages}
result={'synthetic':{'legacy':metrics('legacy'),'expanded_bm25_rrf':metrics('hybrid'),'dense_rrf':None},
        'metric_order':['Recall@5','Recall@10','MRR'],'labeled_questions':9,'unanswerable_questions':1,
        'dense_ready':model is not None,'real_courseware':{}}
q=QUESTIONS[5]
for mode in ['legacy','hybrid']:
    response=Retriever(c,retrieval_mode=mode,dense_index=model if mode=='hybrid' else None).search(q,mode='expanded',top_k=10)
    result['real_courseware'][mode]={'pages':[{'file':h.page.filename,'physical_page':h.page.page_number} for h in response.hits],
        'planned_evidence':[{'file':h.page.filename,'physical_page':h.page.page_number} for h,t in plan_evidence(q,response.hits).quotes],
        'diagnostics':response.diagnostics}
if model is not None:
    from src.dense_index import DenseIndex
    synthetic=corpus();d=DenseIndex(synthetic.pages,model.encoder,'local-bge-benchmark',ROOT/'data/retrieval_cache/benchmark.sqlite3')
    r=Retriever(synthetic,dense_index=d);values=[]
    for question,gold in zip(QUESTIONS,GOLD):
        if not gold:continue
        ids=[h.page.page_number for h in r.search(question,top_k=10).hits]
        ranks=[ids.index(i)+1 for i in gold if i in ids]
        values.append((len(gold&set(ids[:5]))/len(gold),len(gold&set(ids[:10]))/len(gold),1/min(ranks) if ranks else 0))
    result['synthetic']['dense_rrf']=[sum(v[i] for v in values)/len(values) for i in range(3)]
(out/'local_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
