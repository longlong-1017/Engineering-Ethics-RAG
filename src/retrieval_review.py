"""检索/引用联调沙箱。独立于正式QA和选择题路径，不生成答案或升级审核状态。"""
from copy import deepcopy
from difflib import SequenceMatcher
import hashlib
import itertools
import re

from src.evidence import analyze_question, has_payload, topic_match
from src.query_expansion import comparison_sides, theory_explanation_strength
from src.text_utils import query_terms, compact_text, is_outline_page


def normalize_actions(text):
    for alias in ('避免利益冲突','避开利益冲突'):
        text=text.replace(alias,'回避利益冲突')
    return text


def normalize_concepts(text):
    """统一已有概念别名；保留段落和列表结构，不改变来源原文。"""
    text=normalize_actions(text)
    for a,b in [('功利主义','功利论'),('义务伦理','义务论'),('道义论','义务论')]:
        text=text.replace(a,b)
    return text


def canonical(text):
    return normalize_concepts(compact_text(text))


def ppt_record(hit,kind):
    p=hit.page
    return dict(id=f'{kind}:{hit.evidence_id}',kind=kind,priority=1 if kind=='ppt_new' else 2,
                text=p.text,review_status=p.review_label,strict_eligible=p.strict_eligible,
                sources=[dict(filename=p.filename,document_sha256=p.document_id,physical_page=p.page_number)],
                original_rank=hit.rank,raw_scores=dict(rrf=hit.score if hit.score_type=='rrf' else None,
                                                      bm25=hit.bm25_score,dense_cosine=hit.dense_score))


def textbook_record(block,rank=0,scores=None):
    return dict(id=block['block_id'],kind='textbook',priority=3,text=block['text'],
                review_status=block['review_status'],strict_eligible=False,sources=deepcopy(block['sources']),
                book=block['book'],chapter=block['chapter'],chapter_title=block['chapter_title'],
                section_id=block['section_id'],section_title=block['section_title'],topic_heading=block['topic_heading'],
                original_rank=rank,raw_scores=scores or {},context_for=[])


def quiz_record(row):
    # 检索题干；干扰选项和历史作答不充当事实证据。
    return dict(id='quiz:'+row['id'],kind='quiz',priority=4,text=row['question'],
                review_status=row['verification_status'],strict_eligible=False,
                sources=[dict(filename=s['pdf_filename'],document_sha256=s['pdf_sha256'],
                              physical_page=p,role=role)
                         for s in row.get('pdf_sources',[]) for role,pages in
                         [('question',s['question_pages']),('answer',[s['answer_page']])] for p in pages],
                bank=deepcopy({k:row[k] for k in ('id','question','type','options','correct_answer','answer_status')}),
                original_rank=0,raw_scores={})


def features(question,record):
    normalized_question=normalize_concepts(question)
    normalized_body=normalize_concepts(record['text'])
    body=canonical(normalized_body);q=canonical(normalized_question)
    terms=[canonical(t) for t in query_terms(normalize_actions(question)) if canonical(t) not in {'工程','伦理','工程师'}]
    terms=list(dict.fromkeys(t for t in terms if len(t)>=2))
    coverage=sum(t in body for t in terms)/len(terms) if terms else 0
    profile=analyze_question(normalized_question)
    subject=canonical(profile.subject)
    anchors=[t for t in terms if len(t)==max(map(len,terms),default=0)]
    anchor=float(subject in body) if subject else 0
    if anchors:anchor=max(anchor,sum(t in body for t in anchors)/len(anchors))
    payload=float(not is_outline_page(normalized_body) and has_payload(profile,normalized_body))
    exact=float(q==body or bool(q and q in body))
    relation=float(topic_match(profile,normalized_body))
    sides=comparison_sides(normalized_question)
    if sides:relation=sum(theory_explanation_strength(normalized_body,side)>0 for side in sides)/len(sides)
    return (coverage,anchor,payload,exact,relation)


def _macro_f1(expected,predicted):
    total=0
    for label in (0,1,2):
        tp=sum(a==label and b==label for a,b in zip(expected,predicted))
        fp=sum(a!=label and b==label for a,b in zip(expected,predicted))
        fn=sum(a==label and b!=label for a,b in zip(expected,predicted))
        total+=(2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0)
    return total/3


class RelevanceCalibration:
    """由标注数据选择特征组合及两个边界。分数不是概率或向量余弦。"""
    def __init__(self,weights,low,high,provenance):
        self.weights=tuple(weights);self.low=low;self.high=high;self.provenance=provenance

    def score(self,values):return sum(w*v for w,v in zip(self.weights,values))/sum(self.weights)

    def predict(self,values):
        score=self.score(values)
        return 0 if score<self.low else 1 if score<self.high else 2

    @classmethod
    def fit(cls,examples,provenance):
        if {e['label'] for e in examples}!={0,1,2}:raise ValueError('校准必须包含三类标注')
        expected=[e['label'] for e in examples];best=None
        # 小型、确定性的候选组合；阈值只取训练分数的间隙，不用任意常数切分。
        weights=[w for w in itertools.product((0,1,2),repeat=5) if sum(w)>0]
        for w in weights:
            scores=[sum(a*b for a,b in zip(w,e['features']))/sum(w) for e in examples]
            values=sorted(set(scores));bounds=[values[0]]+[(a+b)/2 for a,b in zip(values,values[1:])]+[values[-1]+1e-9]
            for low,high in itertools.combinations_with_replacement(bounds,2):
                predicted=[0 if s<low else 1 if s<high else 2 for s in scores]
                key=(_macro_f1(expected,predicted),sum(a==b for a,b in zip(expected,predicted)),-sum(w),-low,-high)
                if best is None or key>best[0]:best=(key,w,low,high)
        _,w,low,high=best
        obj=cls(w,low,high,provenance)
        return obj

    def to_dict(self):return dict(weights=self.weights,low=self.low,high=self.high,provenance=self.provenance,
                                   feature_names=['term_coverage','anchor_coverage','payload','exact_question','topic_relation'])


def reference(record,rank):
    if record['kind']=='textbook' and (record['review_status']!='UNVERIFIED' or record['strict_eligible']):
        raise ValueError('教材联调禁止升级审核状态')
    sources=deepcopy(record['sources'])
    for s in sources:
        if not isinstance(s.get('physical_page'),int) or isinstance(s['physical_page'],bool) or s['physical_page']<1:raise ValueError('无效物理页码')
        if s.get('printed_page_status')=='candidate_conflicts_with_offset':
            if s.get('printed_page') is not None:raise ValueError('冲突印刷页不得自动确认')
    return dict(id=f'R{rank}',evidence_id=record['id'],source_kind=record['kind'],sources=sources,
                review_status=record['review_status'],strict_eligible=record['strict_eligible'],
                book=record.get('book'),chapter=record.get('chapter'),chapter_title=record.get('chapter_title'),
                section_id=record.get('section_id'),section_title=record.get('section_title'),
                text_sha256=hashlib.sha256(record['text'].encode()).hexdigest(),
                risks=(['教材UNVERIFIED，不属于严格证据池'] if record['kind']=='textbook' else [])+
                      (['小节归属待确认'] if record['kind']=='textbook' and record.get('section_id') is None else [])+
                      (['印刷页码冲突待审核'] if any(s.get('printed_page_status')=='candidate_conflicts_with_offset' for s in sources) else []))


def resolve_references(ids,mapping):
    if any(i not in mapping for i in ids):raise ValueError('引用编号不存在')
    return [deepcopy(mapping[i]) for i in ids]


def evidence_coverage(question,records,options=None):
    """资料充分性是可审阅规则推断，独立于相关性/人工审核，不声称语义蕴含金标。"""
    groups={k:[r for r in records if r['kind']==k] for k in ('ppt_new','ppt_old','textbook','quiz')}
    by_source={};sides=comparison_sides(question)
    domains=[t for t in ('生产安全','公共安全','社会公正','生态安全') if t in question]
    numbers=re.findall(r'\d{4}年(?:\d{1,2}月)?(?:\d{1,2}日)?',question)
    count_match=re.search(r'([五四三二两六七八九十\d]+)种',question)
    counts={'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
    requested=int(count_match[1]) if count_match and count_match[1].isdigit() else counts.get(count_match[1]) if count_match else None
    for kind,items in groups.items():
        text='\n'.join(r['text'] for r in items);facets={};complete=False
        if kind=='quiz':
            matched=[]
            for r in items:
                b=r['bank']
                same=canonical(question)==canonical(b['question'])
                same_options=options is not None and sorted(map(canonical,options.values()))==sorted(map(canonical,b['options'].values()))
                if same and same_options and b['correct_answer'] is not None and b['answer_status']=='confirmed_from_screenshot':matched.append(r['id'])
            facets={'exact_question_and_options_with_source_answer':bool(matched)};complete=bool(matched)
        elif sides:
            facets={side[0]:any(theory_explanation_strength(r['text'],side)>0 for r in items) for side in sides}
            complete=bool(items) and all(facets.values())
        elif len(domains)>=2:
            def explained(term,text):
                parts=[p.strip() for p in text.split('\n\n') if p.strip()]
                verbs=('是指','主要涉及','主要是指','指的是','定义为')
                for i,part in enumerate(parts):
                    if term not in part:continue
                    if any(v in part for v in verbs):return True
                    heading=part.replace('环境工程中的','').strip()
                    if heading==term and i+1<len(parts) and any(v in parts[i+1] for v in verbs):return True
                return False
            facets={term:any(explained(term,r['text']) for r in items) for term in domains}
            complete=bool(items) and all(facets.values())
        else:
            profile=analyze_question(normalize_concepts(question))
            facets={'subject_and_payload':any(topic_match(profile,normalize_concepts(r['text'])) and has_payload(profile,normalize_concepts(r['text'])) for r in items)}
            complete=facets['subject_and_payload']
        if options is not None and kind!='quiz':
            facets['options_individually_assessed']=False
            complete=False  # 正式选项推理属于下一阶段，题干相关不能代表选项均有依据。
        if requested:
            profile=analyze_question(normalize_concepts(question))
            list_text='\n'.join(r['text'] for r in items if topic_match(profile,normalize_concepts(r['text'])) and has_payload(profile,normalize_concepts(r['text'])))
            markers=set(re.findall(r'[①②③④⑤⑥⑦⑧⑨⑩]',list_text))
            enum=set(re.findall(r'(?:^|\n)\s*([1-9])\s*[)）]',list_text))
            facets['requested_list_items']=max(len(markers),len(enum))>=requested
            complete=complete and facets['requested_list_items']
        for number in numbers:facets['requested_date:'+number]=canonical(number) in canonical(text);complete=complete and facets['requested_date:'+number]
        by_source[kind]=dict(complete_reference=complete,facets=facets,evidence_ids=[r['id'] for r in items])
    ready=[k for k,v in by_source.items() if v['complete_reference']]
    state='complete_reference' if ready else 'partial_reference' if records else 'insufficient'
    return dict(state=state,complete_sources=ready,by_source=by_source,
                note='自动覆盖检查，仅供联调；不证明来源已审核，不自动混合跨来源结论',
                strict_verified=False)


def conflict_hints(records):
    hints=[]
    for a,b in itertools.combinations(records,2):
        if a['kind']==b['kind'] or 'quiz' in (a['kind'],b['kind']):continue
        # 只检测同一明确事实角色的数字差异，作为线索，不冒充语义冲突结论。
        def facts(text):
            return {(role,unit):number for role,number,unit in re.findall(r'(死亡|受伤|经济损失)\s*(\d+(?:\.\d+)?)\s*(人|万元|亿元)',text)}
        left,right=facts(a['text']),facts(b['text'])
        for key in left.keys() & right.keys():
            if left[key]!=right[key]:hints.append(dict(evidence_ids=[a['id'],b['id']],reason=f'{key[0]}数值不同，可能是不同案例或版本，待人工核对'))
    return hints


def review_results(question,candidates,calibration,*,top_k=8,strict=False,options=None):
    registry={};assessed=[];filtered=[]
    for raw in candidates:
        r=deepcopy(raw)
        if r['id'] in registry:
            if any(registry[r['id']].get(k)!=r.get(k) for k in ('text','sources','kind','review_status','strict_eligible','chapter','section_id')):raise ValueError('同一证据ID映射冲突')
            continue
        registry[r['id']]=r
        if strict and not r['strict_eligible']:
            filtered.append(dict(id=r['id'],reason='不属于严格审核池'));continue
        named_rule=re.search(r'(?:《([^》]+)》|([^？?。；;]+?(?:规范|条例|标准|定律)))第[一二三四五六七八九十百\d]+条',question)
        if named_rule and not any(canonical(x) in canonical(r['text']) for x in named_rule.groups() if x):
            filtered.append(dict(id=r['id'],reason='特定规范/法条标题未在证据中出现，不能借通用伦理规范替代'));continue
        values=features(question,r);label=calibration.predict(values);score=calibration.score(values)
        entry=dict(record=r,features=values,score=score,relevance=label)
        if label==0:filtered.append(dict(id=r['id'],reason='校准模型判为不相关',**{k:entry[k] for k in ('features','score','relevance')}))
        else:assessed.append(entry)
    # 相关性先于来源等级，来源只在同分时决定顺序。
    assessed.sort(key=lambda e:(-e['relevance'],-e['score'],e['record']['priority'],e['record']['original_rank'],e['record']['id']))
    selected=[]
    for e in assessed:
        r=e['record'];text=canonical(r['text']);duplicate=None
        for old in selected:
            other=old['record'];ot=canonical(other['text'])
            same_scope=r['kind']==other['kind'] and r.get('chapter')==other.get('chapter') and r.get('section_id')==other.get('section_id')
            if text==ot or same_scope and (text in ot or ot in text):duplicate=other['id'];break
        if duplicate:filtered.append(dict(id=r['id'],reason='完全重复或同范围全文包含',duplicate_of=duplicate));continue
        if len(selected)<top_k:selected.append(e)
        else:filtered.append(dict(id=r['id'],reason='相关但超过Top-K'))
    # 相邻块只作为明确标识的补充上下文，不伪装成独立高相关命中。
    seed_ids={e['record']['id'] for e in selected if e['record']['kind']=='textbook' and e['relevance']==2}
    chosen_ids={e['record']['id'] for e in selected};context=[]
    for raw in candidates:
        if strict or raw['id'] in chosen_ids or not seed_ids.intersection(raw.get('context_for',())):continue
        if raw['kind']!='textbook' or raw.get('section_id') is None:continue
        matches=[registry[i] for i in seed_ids.intersection(raw.get('context_for',()))]
        same_scope=any((r.get('chapter'),r.get('section_id'),r.get('topic_heading'))==
                       (raw.get('chapter'),raw.get('section_id'),raw.get('topic_heading'))
                       and any(a['filename']==b['filename'] and abs(a['physical_page']-b['physical_page'])<=1
                               for a in r['sources'] for b in raw['sources']) for r in matches)
        if not same_scope:
            filtered.append(dict(id=raw['id'],reason='上下文关联越过章节/小节/来源边界'));continue
        if any(canonical(raw['text'])==canonical(r['text']) for r in [e['record'] for e in selected]+context):continue
        item=deepcopy(raw);item['retrieval_role']='context_only_not_independent_relevant_hit'
        context.append(item);chosen_ids.add(raw['id'])
    refs={f'R{i}':reference(r,i) for i,r in enumerate([e['record'] for e in selected]+context,1)}
    for item in filtered:
        r=registry[item['id']]
        item.update(kind=r['kind'],sources=deepcopy(r['sources']),review_status=r['review_status'])
        if item['id'] in {r['id'] for r in context}:
            item['original_filter_reason']=item['reason'];item['reason']='不作为独立相关命中；仅保留为同节相邻上下文'
    coverage=evidence_coverage(question,[e['record'] for e in selected]+context,options)
    return dict(question=question,calibration=calibration.to_dict(),selected=selected,filtered=filtered,
                references=refs,context=context,coverage=coverage,strict=strict,
                conflict_hints=conflict_hints([e['record'] for e in selected]),cross_source_combination_allowed=False,
                warning='联调结果不替代正式回答；教材状态与相关性/覆盖判定独立，全部待人工验收')


class RetrievalReviewSession:
    """注入既有只读检索器，供任意问题联调；正式QA不引用本入口。"""
    def __init__(self,ppt_indexes,textbook,blocks,bank,calibration=None):
        self.ppt_indexes=ppt_indexes;self.textbook=textbook;self.blocks=blocks
        self.bank=list(bank);self.calibration=calibration
        self.positions={b['block_id']:i for i,b in enumerate(blocks)}

    def collect(self,question,strict=False):
        records=[];diagnostics={}
        for kind,index in self.ppt_indexes.items():
            result=index.search(question,mode='strict' if strict else 'expanded',top_k=10)
            records.extend(ppt_record(h,kind) for h in result.hits);diagnostics[kind]=result.diagnostics
        if not strict:
            result=self.textbook.search(question,top_k=10)
            diagnostics['textbook']={k:v for k,v in result.items() if k!='hits'}
            for h in result['hits']:
                records.append(textbook_record(h['block'],h['rank'],{k:h[k] for k in ('score','score_type','bm25_score','dense_cosine')}))
            for h in result['hits'][:5]:
                b=h['block'];i=self.positions[b['block_id']]
                for j in (i-1,i+1):
                    if not 0<=j<len(self.blocks):continue
                    other=self.blocks[j]
                    if b['section_id'] is not None and (b['chapter'],b['section_id'],b['topic_heading'])==(other['chapter'],other['section_id'],other['topic_heading']):
                        r=textbook_record(other,11);r['context_for']=[b['block_id']];records.append(r)
            matches=sorted(self.bank,key=lambda b:SequenceMatcher(None,canonical(question),canonical(b['question']),autojunk=False).ratio(),reverse=True)[:2]
            records.extend(quiz_record(b) for b in matches)
        unique={}
        for r in records:
            if r['id'] not in unique:unique[r['id']]=r
            elif r.get('context_for'):unique[r['id']].setdefault('context_for',[]).extend(r['context_for'])
        return list(unique.values()),diagnostics

    def search(self,question,*,options=None,strict=False,top_k=8):
        if self.calibration is None:raise ValueError('须先提供有标注依据的相关性校准，禁止静默使用固定阈值')
        records,diagnostics=self.collect(question,strict)
        result=review_results(question,records,self.calibration,options=options,strict=strict,top_k=top_k)
        result['retrieval_diagnostics']=diagnostics
        return result
