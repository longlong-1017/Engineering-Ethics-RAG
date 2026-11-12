"""隔离凭据环境的教材专用离线入口；禁止网络、禁止自动下载。"""
from pathlib import Path
import os
import sys

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__' and '--offline-worker' not in sys.argv:
    os.execve(str(ROOT/'.venv/bin/python'),[str(ROOT/'.venv/bin/python'),str(Path(__file__).resolve()),'--offline-worker',*sys.argv[1:]],
              dict(PATH='/usr/bin:/bin',PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
                   HF_HUB_DISABLE_TELEMETRY='1',TOKENIZERS_PARALLELISM='false',
                   HF_HOME=str(ROOT/'models/.offline_cache'),XDG_CACHE_HOME=str(ROOT/'models/.offline_cache')))


def guard(event,args):
    if event in ('socket.connect','socket.getaddrinfo'):raise PermissionError('教材处理禁止网络')
    if event=='open' and args and isinstance(args[0],(str,bytes)):
        p=Path(args[0].decode() if isinstance(args[0],bytes) else args[0])
        if (p.name=='.env' or p.name.startswith('.env.') or p.name.endswith('.env')
                or p.name in ('token','.netrc','secrets.toml') or any(x in p.parts for x in ('.ssh','.aws','.azure'))):
            raise PermissionError('教材处理禁止读取或修改凭据')


sys.addaudithook(guard)
sys.path.insert(0,str(ROOT))

import argparse
import json
import hashlib
from src.textbook_kb import (SCAN,DATASET,CACHE,build_dataset,load_blocks,TextbookVectors,TextbookRetriever)


def model_identity():
    model=ROOT/'models/bge-small-zh-v1.5'
    if not (model/'tokenizer.json').is_file():raise FileNotFoundError('本地模型缺失，不自动下载')
    digest=hashlib.sha256()
    for path in sorted(model.rglob('*')):
        if path.is_file():
            digest.update(str(path.relative_to(model)).encode());digest.update(path.read_bytes())
    return model,'bge-small-zh-v1.5-content:'+digest.hexdigest()


def main(argv):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare','index','search','stats'))
    parser.add_argument('--dataset',type=Path,default=DATASET)
    parser.add_argument('--cache',type=Path,default=CACHE)
    parser.add_argument('--repairs',type=Path)
    parser.add_argument('--question',default='')
    parser.add_argument('--top-k',type=int,default=5)
    parser.add_argument('--chapter',type=int)
    parser.add_argument('--strict',action='store_true')
    args=parser.parse_args(argv)
    if not args.dataset.resolve().is_relative_to(ROOT/'data/textbook_kb') or not args.cache.resolve().is_relative_to(ROOT/'data/textbook_kb'):
        parser.error('仅允许独立教材数据/缓存路径')
    if args.repairs and not args.repairs.resolve().is_relative_to(ROOT/'reports'):
        parser.error('纠错证据必须来自本地报告')
    if args.command=='prepare':
        from tokenizers import Tokenizer
        model,identity=model_identity()
        tokenizer=Tokenizer.from_file(str(model/'tokenizer.json'));tokenizer.no_truncation()
        settings=json.loads((model/'sentence_bert_config.json').read_text())
        repairs=json.loads(args.repairs.read_text('utf-8')) if args.repairs else []
        result=build_dataset(ROOT/'data/textbooks',SCAN,args.dataset,
                             token_count=lambda text:len(tokenizer.encode(text).ids),
                             max_tokens=settings['max_seq_length'],repairs=repairs)
    else:
        blocks,manifest=load_blocks(args.dataset)
        if args.command=='stats':result=manifest
        elif args.command=='search' and args.strict:result=TextbookRetriever(blocks).search(args.question,strict=True)
        else:
            dense=None;error=''
            try:
                from sentence_transformers import SentenceTransformer
                model,identity=model_identity()
                encoder=SentenceTransformer(str(model),device='cpu',local_files_only=True,token=False,trust_remote_code=False)
                dense=TextbookVectors(blocks,encoder,identity,args.cache,build=args.command=='index')
            except Exception as exc:
                if args.command=='index':raise
                error='教材Dense不可用，回退BM25：'+type(exc).__name__
            result=dense.status if args.command=='index' else TextbookRetriever(blocks,dense,error).search(
                args.question,top_k=args.top_k,chapter=args.chapter)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main([a for a in sys.argv[1:] if a!='--offline-worker'])
