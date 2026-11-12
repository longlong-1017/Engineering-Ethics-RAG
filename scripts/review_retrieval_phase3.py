"""独立跨来源检索验收；只读缓存、仅生成查询向量，不启动QA。"""
from pathlib import Path
import os,sys
ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__' and '--offline-worker' not in sys.argv:
    os.execve(str(ROOT/'.venv/bin/python'),[str(ROOT/'.venv/bin/python'),str(Path(__file__).resolve()),'--offline-worker',*sys.argv[1:]],
              dict(PATH='/usr/bin:/bin',PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
                   HF_HUB_DISABLE_TELEMETRY='1',TOKENIZERS_PARALLELISM='false',HF_HOME=str(ROOT/'models/.offline_cache'),XDG_CACHE_HOME=str(ROOT/'models/.offline_cache')))
from manage_textbook_kb import model_identity
import argparse,json,hashlib
from difflib import SequenceMatcher
from src.versioned_corpus import load_versions
from src.dense_index import DenseIndex
from src.retriever import Retriever
from src.textbook_kb import load_blocks,TextbookVectors,TextbookRetriever,embed_text,CACHE
from src.quiz_bank import query_questions
from src.retrieval_review import (canonical,ppt_record,textbook_record,quiz_record,features,
                                  RelevanceCalibration,review_results,_macro_f1,RetrievalReviewSession)


def cases(bank):
    return [dict(id='Q01',split='train',question='工程伦理中的功利主义与义务论有什么区别？',category='完整答案；跨来源表述差异'),
            dict(id='Q02',split='train',question='工程师回避利益冲突的五种方式有哪些？',category='完整列举；跨块连续性'),
            dict(id='Q03',split='test',question='工程风险的技术因素有哪些？',category='完整答案；小节未确认'),
            dict(id='Q04',split='train',question='环境工程中的生产安全与公共安全有什么区别？',category='跨概念比较'),
            dict(id='Q05',split='train',question='量子纠缠工程伦理跃迁定律的三个公式是什么？',category='无相关答案'),
            dict(id='Q06',split='test',question='火星采矿项目星际伦理规范第九条是什么？',category='无相关答案'),
            dict(id='Q07',split='train',question='工程风险的技术因素有哪些？并给出2027年宁静港事故的伤亡人数。',category='仅部分答案'),
            dict(id='Q08',split='train',question='如何用VaR模型计算股票投资组合的金融风险？',category='关键词相似但语义不相关'),
            dict(id='Q09',split='test',question='避免利益冲突的五种方式有哪些？',category='不同表达同义概念'),
            dict(id='Q10',split='train',question=bank['3.11-01']['question'],options=bank['3.11-01']['options'],category='选择题干扰选项'),
            dict(id='Q11',split='test',question=bank['2.14-11']['question'],options=bank['2.14-11']['options'],category='题库缺正确答案'),
            dict(id='Q12',split='train',question='工程社团的伦理章程为什么能够提高工程师的伦理意识？',category='印刷页码待审核')]


def harvest(output):
    from sentence_transformers import SentenceTransformer
    old,new=load_versions();blocks,manifest=load_blocks();bank={q['id']:q for q in query_questions()}
    model,identity=model_identity();encoder=SentenceTransformer(str(model),device='cpu',local_files_only=True,token=False,trust_remote_code=False)
    class QueryEncoder:
        memo={};calls=0
        def encode(self,texts):
            if len(texts)!=1 or texts[0] in banned:raise AssertionError('禁止重新编码文档')
            q=texts[0]
            if q not in self.memo:self.memo[q]=encoder.encode([q])[0];self.calls+=1
            return [self.memo[q]]
    banned={p.text for p in old.pages+new.pages}|{embed_text(b) for b in blocks};enc=QueryEncoder()
    stamp=';'.join(f'{p.name}:{p.stat().st_size}:{p.stat().st_mtime_ns}' for p in sorted(model.rglob('*')) if p.is_file())
    ppt_id='bge-small-zh-v1.5:'+hashlib.sha256(stamp.encode()).hexdigest()
    indexes={}
    for kind,corpus,name in [('ppt_new',new,'exam_2026.sqlite3'),('ppt_old',old,'vectors.sqlite3')]:
        dense=DenseIndex.from_cache(corpus.expanded_pages,enc,ppt_id,ROOT/'data/retrieval_cache'/name)
        indexes[kind]=Retriever(corpus,dense_index=dense,dense_status=dense.status)
    tb=TextbookVectors(blocks,enc,identity,CACHE);textbook=TextbookRetriever(blocks,tb)
    session=RetrievalReviewSession(indexes,textbook,blocks,bank.values());data=[]
    for case in cases(bank):
        records,diagnostics=session.collect(case['question'])
        data.append(dict(case=case,candidates=records,diagnostics=diagnostics))
        print(case['id'],'candidates',len(records),flush=True)
    payload=dict(annotation_status='awaiting_assistant_candidate_labels_then_human_confirmation',cases=data,
                 textbook_blocks=len(blocks),textbook_cache=tb.status,query_encodings=enc.calls,
                 provenance='真实材料只读召回；不是人工金标；没有答案生成')
    with output.open('x',encoding='utf-8') as f:json.dump(payload,f,ensure_ascii=False,indent=2)


def evaluate(harvest_path,labels_path,output,frozen_calibration=None):
    payload=json.loads(harvest_path.read_text());labels=json.loads(labels_path.read_text());lookup={r['case']['id']:r for r in payload['cases']}
    examples=[]
    for item in labels['pairs']:
        row=lookup[item['query_id']];record=next(r for r in row['candidates'] if r['id']==item['evidence_id'])
        if row['case']['split']=='train':examples.append(dict(features=features(row['case']['question'],record),label=item['relevance']))
    if frozen_calibration is None:
        cal=RelevanceCalibration.fit(examples,labels['provenance'])
    else:
        saved=json.loads(frozen_calibration.read_text())['calibration']
        cal=RelevanceCalibration(saved['weights'],saved['low'],saved['high'],saved['provenance'])
    results=[]
    for row in payload['cases']:
        case=row['case'];results.append(dict(case=case,result=review_results(case['question'],row['candidates'],cal,options=case.get('options'))))
    predicted={};test_expected=[];test_predicted=[];mistakes=[]
    for pair in labels['pairs']:
        row=lookup[pair['query_id']];r=next(r for r in row['candidates'] if r['id']==pair['evidence_id'])
        prediction=cal.predict(features(row['case']['question'],r));predicted[(pair['query_id'],pair['evidence_id'])]=prediction
        if row['case']['split']=='test':
            test_expected.append(pair['relevance']);test_predicted.append(prediction)
            if prediction!=pair['relevance']:mistakes.append(dict(pair,predicted=prediction))
    coverage_errors=[]
    for row in results:
        gold=labels['query_coverage'].get(row['case']['id'])
        if gold and gold!=row['result']['coverage']['state']:coverage_errors.append(dict(query_id=row['case']['id'],candidate_label=gold,predicted=row['result']['coverage']['state']))
    result=dict(calibration=cal.to_dict(),calibration_mode='frozen' if frozen_calibration else 'fit_train_only',training_pairs=len(examples),heldout_pairs=len(test_expected),
                assistant_candidate_macro_f1=_macro_f1(test_expected,test_predicted),
                assistant_candidate_accuracy=sum(a==b for a,b in zip(test_expected,test_predicted))/len(test_expected),
                relevance_errors=mistakes,coverage_errors=coverage_errors,results=results,
                formal_human_gold_metrics=None,requires_human_confirmation=True,annotation_provenance=labels['provenance'])
    with output.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='results'},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('harvest','evaluate'));p.add_argument('--output',type=Path,required=True);p.add_argument('--harvest',type=Path);p.add_argument('--labels',type=Path);p.add_argument('--frozen-calibration',type=Path)
    a=p.parse_args([x for x in sys.argv[1:] if x!='--offline-worker'])
    for path in (a.output,a.harvest,a.labels,a.frozen_calibration):
        if path and not path.resolve().is_relative_to(ROOT/'reports'):p.error('仅允许报告目录中的评测文件')
    if a.output.exists():p.error('拒绝覆盖已有评测结果')
    harvest(a.output) if a.command=='harvest' else evaluate(a.harvest,a.labels,a.output,a.frozen_calibration)
