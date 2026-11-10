"""本地BGE实测：不加载Settings、不继承凭据环境，强制离线并禁止socket连接。"""
from pathlib import Path
import os,sys
ROOT=Path(__file__).resolve().parents[1]
if '--isolated' not in sys.argv:
    os.execve(str(ROOT/'.venv/bin/python'),[str(ROOT/'.venv/bin/python'),str(Path(__file__).resolve()),'--isolated'],
        {'PATH':'/usr/bin:/bin','HF_HOME':str(ROOT/'models/.offline_cache'),'HF_HUB_OFFLINE':'1',
         'TRANSFORMERS_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1','TOKENIZERS_PARALLELISM':'false'})
sys.path.insert(0,str(ROOT))
def audit(event,args):
    if event=='socket.connect':raise PermissionError('本地验证禁止网络连接')
    if event=='open' and args and isinstance(args[0],(str,bytes)):
        p=Path(args[0].decode() if isinstance(args[0],bytes) else args[0])
        if p.name in ('.env','.netrc','token','secrets.toml') or p.name.startswith('.env.'):
            raise PermissionError('本地验证禁止读取凭据')
sys.addaudithook(audit)
import hashlib,json,time
from src.corpus import load_corpus
from src.dense_index import load_project_dense_status
from src.retriever import Retriever

def digest():
    files=list((ROOT/'data/pdfs').glob('*.pdf'))+list((ROOT/'data/processed_v3').glob('*.json'))
    files += [ROOT/'src'/name for name in ('citations.py','structured_answer.py','config.py','api_limits.py','deepseek_client.py')]
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}

before=digest();c=load_corpus();started=time.monotonic()
dense,status=load_project_dense_status(c)
print('Dense加载及索引状态：',json.dumps(status,ensure_ascii=False),flush=True)
questions=[
'某化工企业排放废水虽然满足现行标准，但可能长期影响周边居民健康。工程师应该如何进行伦理判断？',
'某工程项目能够带来显著经济收益，但可能对当地生态环境造成不可逆损害，应如何进行伦理决策？',
'当工程师发现项目存在安全隐患，但管理层要求继续施工时，应如何处理？']
results=[]
for question in questions:
    row={'question':question,'results':{}}
    for label,index in [('BM25扩展+RRF',None),('BM25+BGE+RRF',dense)]:
        response=Retriever(c,dense_index=index,dense_status=status if index is not None else None).search(question,mode='expanded',top_k=5)
        row['results'][label]={'diagnostics':response.diagnostics,'top5':[h.to_dict() for h in response.hits]}
    results.append(row)
reused=None
if dense is not None:
    again,reused=load_project_dense_status(c)
    assert again is not None and reused['encoded_blocks']==0,'缓存复用验证失败'
    for k,p in dense.pages.items():
        assert k in dense.vectors and p.page_number>=1
out=ROOT/'reports/bge_verification';out.mkdir(exist_ok=True,parents=True)
payload=dict(index=status,cache_second_load=reused,protected_unchanged=before==digest(),
             protected_files=len(before),elapsed_seconds=round(time.monotonic()-started,2),results=results,
             metrics_note='真实问题没有人工金标，不计算或声称Recall/MRR提升。')
(out/'offline_results.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
lines=['# BGE本地接入验证（2026-11-10）','',payload['metrics_note'],'','索引状态：','', '```json',json.dumps(status,ensure_ascii=False,indent=2),'```','']
for row in results:
    lines += ['## '+row['question'],'','BM25基线也使用相同的查询扩展与覆盖重排；差别仅为是否接入BGE通道。','',
              '|通道|名次|真实课件|物理页|排序分类型|排序分|Dense余弦最大值|','|---|---:|---|---:|---|---:|---:|']
    for label,entry in row['results'].items():
        for hit in entry['top5']:
            lines.append(f"|{label}|{hit['rank']}|{hit['filename']}|{hit['page_number']}|{hit['score_type']}|{hit['score']:.5f}|{hit['dense_cosine_max']}|")
lines += ['',f"保护检查：{payload['protected_files']}个原始资料/关键源码文件未变化：{payload['protected_unchanged']}。",'',
          '二次加载缓存状态：','```json',json.dumps(reused,ensure_ascii=False,indent=2),'```',
          '', '索引单元沿用现有页级文本块；非空有文本页参与编码，空白页不编造向量。Dense余弦和RRF分数仅用于召回，不代表审核状态或事实验证。']
(out/'BGE接入验证报告.md').write_text('\n'.join(lines)+'\n')
print('报告已保存；缓存复用：',reused,'保护检查：',payload['protected_unchanged'],flush=True)
