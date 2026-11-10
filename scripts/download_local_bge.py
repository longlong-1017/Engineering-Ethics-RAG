"""仅下载公开模型文件；不使用HF SDK、认证、代理、netrc或真实进程环境。"""
from pathlib import Path
import os,sys
ROOT=Path(__file__).resolve().parents[1]
if '--isolated' not in sys.argv:
    os.execve(str(ROOT/'.venv/bin/python'),[str(ROOT/'.venv/bin/python'),str(Path(__file__).resolve()),'--isolated'],{'PATH':'/usr/bin:/bin','PYTHONNOUSERSITE':'1'})
import requests
import hashlib
session=requests.Session();session.trust_env=False
base='https://huggingface.co'
try:
    response=session.get(base+'/api/models/BAAI/bge-small-zh-v1.5',timeout=(15,60));response.raise_for_status()
    info=response.json();revision=info['sha'];available={x['rfilename'] for x in info['siblings']}
    weights='model.safetensors' if 'model.safetensors' in available else 'pytorch_model.bin'
    names=['config.json','tokenizer.json','tokenizer_config.json','special_tokens_map.json','vocab.txt',
           'sentence_bert_config.json','modules.json','1_Pooling/config.json',weights]
    target=ROOT/'models/bge-small-zh-v1.5';target.mkdir(parents=True,exist_ok=True)
    total=0
    for name in names:
        if name not in available:continue
        path=target/name
        if path.is_file():continue
        path.parent.mkdir(parents=True,exist_ok=True)
        r=session.get(base+'/BAAI/bge-small-zh-v1.5/resolve/'+revision+'/'+name,stream=True,timeout=(15,60));r.raise_for_status()
        temporary=path.with_suffix(path.suffix+'.part')
        with temporary.open('wb') as handle:
            for block in r.iter_content(1024*1024):handle.write(block)
        temporary.replace(path);total+=path.stat().st_size
        print('已下载',name,round(path.stat().st_size/1e6,2),'MB',flush=True)
    (target/'LOCAL_REVISION.txt').write_text(revision+'\n')
    print('新增模型文件MB',round(total/1e6,2))
except Exception as exc:
    print('公开下载诊断：',type(exc).__name__, 'HTTP',getattr(getattr(exc,'response',None),'status_code',None),flush=True)
    raise SystemExit('公开模型下载失败，未输出URL或响应；可保留BM25回退，稍后重试。') from None
