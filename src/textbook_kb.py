"""独立、只读查询的待审核教材库；不接入考试路由或答案生成。"""
from __future__ import annotations

from collections import Counter
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

from src.bm25 import BM25Index
from src.text_utils import tokenize
from src.query_expansion import expand_query

ROOT = Path(__file__).resolve().parents[1]
SCAN = ROOT / 'reports/textbook_scan_20261112_112406'
DATASET = ROOT / 'data/textbook_kb/releases/v2'
CACHE = ROOT / 'data/textbook_kb/vectors.sqlite3'
BOOK = '工程伦理'
POLICY = 'textbook-chapter-section-paragraph-v2'
ELIGIBLE = {'body', 'introduction', 'mixed_body_references'}


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode('utf-8')).hexdigest()


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def section_heading(text, chapter, toc):
    """只接受明确小节编号或目录同章标题的精确匹配；不凭顺序猜编号。"""
    match = re.fullmatch(r'\s*(\d{1,2}\s*[.．]\s*\d{1,2}(?:\s*[.．]\s*\d{1,2})?)\s+([^\d].{1,65})', text)
    if match:
        sid = re.sub(r'\s+', '', match[1]).replace('．', '.')
        title=match[2].strip()
        # 金额1.05亿元不是小节，残缺“.2”也不能冒充标题。
        parts=sid.split('.')
        valid=(all(p==str(int(p)) and 0<int(p)<=30 for p in parts)
               and bool(re.search(r'[\u4e00-\u9fff]{2}',title))
               and not re.search(r'[，,。；;：:]',title))
        if valid and int(parts[0]) == chapter:
            return sid, title, 'explicit_ocr_heading_pending'
    compact = re.sub(r'\s+', '', text)
    matches = [(sid, title) for sid, title in toc.items()
               if int(sid.split('.')[0]) == chapter and compact == re.sub(r'\s+', '', title)]
    if len(matches) == 1:
        return *matches[0], 'exact_toc_title_match_pending'
    return None


def join_lines(lines):
    result = ''
    for line in lines:
        line = line.strip()
        if not line:continue
        sep = '' if result and re.search(r'[\u4e00-\u9fff]$', result) and re.match(r'[\u4e00-\u9fff]', line) else ' '
        result += (sep if result else '') + line
    return result


def embed_text(block):
    section = block.get('section_id') or ''
    return f"{BOOK} {block['chapter_title']} {section} {block.get('section_title') or ''} {block.get('topic_heading') or ''}\n{block['text']}"


def make_chunks(paragraphs, *, token_count=None, max_tokens=512, max_chars=350):
    """章节、小节、子标题均为硬边界；自然段过长才按完整句/字符拆开。"""
    blocks, buffer, active = [], [], None

    def candidate(parts):
        first = parts[0]
        text = '\n\n'.join(p['text'] for p in parts)
        sources = []
        for p in parts:
            key = (p['source']['filename'], p['source']['physical_page'])
            found=next((s for s in sources if (s['filename'],s['physical_page'])==key),None)
            if found is None:
                sources.append(dict(p['source'],bboxes=list(p['source'].get('bboxes',[]))))
            else:
                for box in p['source'].get('bboxes',[]):
                    if box not in found['bboxes']:found['bboxes'].append(box)
        block = dict(book=BOOK, authors=['李正风','丛杭青','王前等'], source_kind='textbook',
                     source_priority=3, priority_note='低于新版PPT及旧版PPT；本阶段不参与考试路由',
                     chapter=first['chapter'], chapter_title=first['chapter_title'],
                     section_id=first['section_id'], section_title=first['section_title'],
                     section_identification=first['section_identification'], topic_heading=first['topic_heading'],
                     text=text, content_sha256=sha(text), sources=sources,
                     paragraph_ids=list(dict.fromkeys(p['paragraph_id'] for p in parts)),
                     paragraph_spans=[dict(paragraph_id=p['paragraph_id'],start=p['piece_start'],end=p['piece_end']) for p in parts],
                     review_status='UNVERIFIED', strict_eligible=False,
                     quality_review_pending=any(p['quality_review_pending'] for p in parts), policy=POLICY)
        block['embedding_sha256'] = sha(embed_text(block))
        block['token_count'] = token_count(embed_text(block)) if token_count else None
        block['block_id'] = 'TB-' + sha(packed([POLICY,block['chapter'],block['section_id'],block['topic_heading'],
                                                 sources,block['paragraph_spans'],block['content_sha256']]))[:32]
        return block

    def flush():
        if buffer:blocks.append(candidate(buffer));buffer.clear()

    def fits(parts):
        b = candidate(parts)
        return len(b['text']) <= max_chars and (token_count is None or b['token_count'] <= max_tokens)

    for paragraph in paragraphs:
        key = paragraph['chapter'], paragraph['section_id'], paragraph['topic_heading']
        if key != active:flush();active=key
        pending = [(paragraph['text'],0)]
        while pending:
            text,start = pending.pop(0)
            part = dict(paragraph,text=text,piece_start=start,piece_end=start+len(text))
            if not fits([part]):
                # 优先在标点处拆分；二分只用于没有合适标点的超长OCR段落。
                middle = len(text)//2
                splits = [m.end() for m in re.finditer(r'[。！？；]',text) if 0<m.end()<len(text)]
                cut = min(splits,key=lambda n:abs(n-middle)) if splits else middle
                if cut <= 0:raise ValueError('上下文标题过长，无法无损满足模型长度')
                pending[:0] = [(text[:cut],start),(text[cut:],start+cut)]
                continue
            if buffer and not fits(buffer+[part]):flush()
            buffer.append(part)
    flush()
    if len({b['block_id'] for b in blocks}) != len(blocks):raise ValueError('教材块ID重复')
    return blocks


def build_dataset(pdf_dir, scan_dir, output, *, token_count, max_tokens, repairs=()):
    """复用第一阶段来源/章节/页码证据，独立导出，不覆盖已有输出。"""
    import pymupdf
    pdf_dir,scan_dir,output=map(Path,(pdf_dir,scan_dir,output))
    if output.exists():raise FileExistsError('教材版本输出已存在，拒绝覆盖')
    manifest=json.loads((scan_dir/'scan_manifest.json').read_text('utf-8'))
    page_index=json.loads((scan_dir/'page_index.json').read_text('utf-8'))
    if len(page_index)!=manifest['page_count']:raise ValueError('扫描页数不一致')
    index={(p['filename'],p['physical_page']):p for p in page_index}
    if len(index)!=len(page_index):raise ValueError('扫描页码重复')
    titles={c['chapter']:c['title'] for c in manifest['chapters']}
    repair_map={}
    for repair in repairs:
        key=repair['filename'],repair['physical_page']
        if repair['document_sha256']!=next(f['sha256'] for f in manifest['files'] if f['filename']==key[0]):
            raise ValueError('修正证据与源PDF哈希不符')
        repair_map.setdefault(key,[]).append(repair)
    documents={};toc={};sources=[]
    for item in manifest['files']:
        if Path(item['filename']).name!=item['filename']:raise ValueError('非法教材文件名')
        content=(pdf_dir/item['filename']).read_bytes()
        if sha(content)!=item['sha256']:raise ValueError('教材PDF已变化，需重新扫描')
        doc=pymupdf.open(stream=content,filetype='pdf')
        if doc.needs_pass or len(doc)!=item['page_count']:raise ValueError('教材页数/加密状态异常')
        documents[item['filename']]=doc;sources.append(dict(item,scan_status=item['status'],status='processed_unverified'))
        for n,page in enumerate(doc,1):
            text=page.get_text('text',sort=True)
            if sha(text)!=index[item['filename'],n]['text_sha256']:raise ValueError('第一阶段文字层基线已变化')
            if index[item['filename'],n]['content_type']=='contents':
                for line in text.splitlines():
                    m=re.match(r'\s*(\d{1,2}(?:\s*\.\s*\d{1,2}){1,2})\s+(.+?)(?:…|\.{2,})',line)
                    if m:toc[re.sub(r'\s+','',m[1])]=m[2].strip()
    paragraphs=[];pages=[];repair_log=[];section=None;topic='';active_chapter=None;paragraph_serial=0
    for row in page_index:
        filename,number=row['filename'],row['physical_page'];page=documents[filename][number-1]
        original=page.get_text('text',sort=True);chapter=row['chapter']
        record=dict(row,review_status='UNVERIFIED',strict_eligible=False,original_text=original,
                    body_text='',body_quality={},applied_repairs=[])
        if chapter!=active_chapter:section=None;topic='';active_chapter=chapter
        if row['content_type'] not in ELIGIBLE or chapter is None:
            pages.append(record);continue
        all_lines=[]
        for block in page.get_text('dict')['blocks']:
            for line in block.get('lines',[]):
                spans=line.get('spans',[]);text=''.join(s.get('text','') for s in spans).strip()
                if text:
                    all_lines.append(dict(text=text,bbox=list(line['bbox']),size=max(s['size'] for s in spans)))
        refs=[l['bbox'][1] for l in all_lines if re.sub(r'\s+','',l['text'])=='参考文献']
        cutoff=min(refs) if refs else page.rect.height*.94
        # 复用第一阶段页眉/页脚界限；小字页下注释仅留页面元数据，不当成正文。
        likely=[l for l in all_lines if page.rect.height*.10<=l['bbox'][3] and l['bbox'][1]<cutoff]
        sizes=sorted([l['size'] for l in likely for _ in range(min(80,len(l['text'])))])
        median=sizes[len(sizes)//2] if sizes else 10
        lines=[l for l in likely if not(l['bbox'][1]>page.rect.height*.78 and l['size']<median*.84)]
        lines.sort(key=lambda l:(l['bbox'][1],l['bbox'][0]))
        # 可见性证据是逐页白名单，不将纠错词典应用到其他页。
        for repair in repair_map.get((filename,number),[]):
            target,replacement=repair['before'],repair['after']
            if original.count(target)!=repair.get('expected_count',1):raise ValueError('修正原文与证据不匹配')
            count=0
            for line in lines:
                count+=line['text'].count(target);line['text']=line['text'].replace(target,replacement)
            if count!=repair.get('expected_count',1):raise ValueError('修正目标不在正文行中，拒绝应用')
            log=dict(repair,applied_count=count,original_page_text_sha256=sha(original))
            record['applied_repairs'].append(log);repair_log.append(log)
        lefts=sorted(l['bbox'][0] for l in lines);left=lefts[len(lefts)//5] if lefts else 0
        current=[];current_boxes=[];previous=None;body=[]
        source=dict(filename=filename,document_sha256=row['document_sha256'],physical_page=number,
                    printed_page=row['printed_page_observed'] if row['printed_page_status']=='observed_consistent_anchor' else None,
                    printed_page_candidates=row['print_candidates'],printed_page_inferred=row['printed_page_inferred'],
                    printed_page_status=row['printed_page_status'],page_mapping_review='pending')

        def flush_paragraph():
            nonlocal paragraph_serial
            if not current:return
            text=join_lines(current);paragraph_serial+=1
            paragraphs.append(dict(paragraph_id=f'{filename}:{number}:p{paragraph_serial}',
                                   chapter=chapter,chapter_title=titles[chapter],
                                   section_id=section[0] if section else None,section_title=section[1] if section else None,
                                   section_identification=section[2] if section else 'pending_unknown',topic_heading=topic,
                                   text=text,source=dict(source,bboxes=list(current_boxes)),
                                   quality_review_pending=bool(row['issues'])))
            body.append(text);current.clear();current_boxes.clear()

        for line in lines:
            heading=section_heading(line['text'],chapter,toc)
            subtopic=re.fullmatch(r'\s*(\d{1,2})\s*[.、]\s*([\u4e00-\u9fff].{1,28})',line['text'])
            if heading:
                flush_paragraph();section=heading;topic='';previous=None
            elif subtopic and len(line['text'])<=35:
                flush_paragraph();topic=line['text'];previous=None
            elif (current and previous and (line['bbox'][0]>left+median*.95
                   or line['bbox'][1]-previous['bbox'][3]>median*.9)):
                flush_paragraph()
            current.append(line['text']);current_boxes.append(line['bbox']);previous=line
        flush_paragraph()
        record['body_text']='\n\n'.join(body)
        record['body_quality']=dict(replacement_characters=record['body_text'].count('\ufffd'),
                                   suspect_ocr_forms=len(re.findall(r'凤险|凤陋|优理|[TtI]程|\{色',record['body_text'])),
                                   possible_digit_splits=len(re.findall(r'\d\s+\d',record['body_text'])),
                                   section_unknown=section is None)
        pages.append(record)
    for doc in documents.values():doc.close()
    blocks=make_chunks(paragraphs,token_count=token_count,max_tokens=max_tokens)
    if not blocks:raise ValueError('没有教材正文块')
    if {b['chapter'] for b in blocks}!={c['chapter'] for c in manifest['chapters']}:raise ValueError('分块章节覆盖不完整')
    output.mkdir(parents=True,exist_ok=False)
    payloads={'pages.json':pages,'paragraphs.json':paragraphs,'blocks.json':blocks,'repairs.json':repair_log}
    hashes={}
    for name,value in payloads.items():
        raw=packed(value)+'\n';(output/name).write_text(raw,encoding='utf-8');hashes[name]=sha(raw)
    result=dict(policy=POLICY,book=BOOK,source_priority=3,routing='independent_only',review_status='UNVERIFIED',
                source_files=sources,scan_manifest_sha256=sha((scan_dir/'scan_manifest.json').read_bytes()),
                page_index_sha256=sha((scan_dir/'page_index.json').read_bytes()),file_hashes=hashes,
                page_count=len(pages),paragraph_count=len(paragraphs),block_count=len(blocks),
                chapter_counts=dict(Counter(b['chapter'] for b in blocks)),
                quality_review_pending_pages=sum(bool(p['issues']) for p in pages),
                ocr_review_pending_pages=sum(any('OCR' in issue or '替换字符' in issue for issue in p['issues']) for p in pages),
                page_conflicts=[{k:p[k] for k in ('filename','physical_page','print_candidates','printed_page_inferred','printed_page_status')}
                                for p in pages if p['printed_page_status']=='candidate_conflicts_with_offset'],
                applied_repair_count=len(repair_log),max_model_tokens=max(b['token_count'] for b in blocks))
    (output/'manifest.json').write_text(packed(result)+'\n',encoding='utf-8')
    return result


def load_blocks(dataset=DATASET):
    dataset=Path(dataset);manifest=json.loads((dataset/'manifest.json').read_text('utf-8'))
    for name,h in manifest['file_hashes'].items():
        if Path(name).name!=name or sha((dataset/name).read_bytes())!=h:raise ValueError('教材数据哈希不匹配')
    blocks=json.loads((dataset/'blocks.json').read_text('utf-8'))
    if len(blocks)!=manifest['block_count'] or len({b['block_id'] for b in blocks})!=len(blocks):raise ValueError('教材块数量或ID异常')
    for block in blocks:
        if block['review_status']!='UNVERIFIED' or block['strict_eligible'] is not False:raise ValueError('未审核教材不得自动升级')
        if sha(block['text'])!=block['content_sha256'] or sha(embed_text(block))!=block['embedding_sha256']:raise ValueError('教材块内容不匹配')
        if not block['sources'] or any(s['physical_page']<1 for s in block['sources']):raise ValueError('教材来源页无效')
    return blocks,manifest


def normalized(vector):
    v=[float(x) for x in vector];norm=math.sqrt(sum(x*x for x in v))
    if not v or not math.isfinite(norm) or norm==0:raise ValueError('无效教材向量')
    return [x/norm for x in v]


class TextbookVectors:
    def __init__(self, blocks, encoder, model_id, path, *, build=False):
        self.encoder=encoder;self.model_id=model_id;self.vectors={};self.cache_hits=0;self.encoded=0
        self.path=str(Path(path).resolve());unique={b['embedding_sha256']:embed_text(b) for b in blocks}
        if build:
            Path(path).parent.mkdir(parents=True,exist_ok=True);db=sqlite3.connect(path)
            db.execute('CREATE TABLE IF NOT EXISTS embeddings(model TEXT,hash TEXT,vector TEXT,PRIMARY KEY(model,hash))')
        else:
            if not Path(path).is_file():raise FileNotFoundError('教材向量缓存缺失')
            db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
        try:
            with db:
                missing=[]
                for h,text in unique.items():
                    if sha(text)!=h:raise ValueError('向量键与文本不符')
                    row=db.execute('SELECT vector FROM embeddings WHERE model=? AND hash=?',(model_id,h)).fetchone()
                    if row:self.vectors[h]=normalized(json.loads(row[0]));self.cache_hits+=1
                    else:missing.append((h,text))
                if missing and not build:raise ValueError('教材缓存内容或模型不匹配')
                # 小批量编码，后续重复构建只处理缓存缺失的文本。
                for start in range(0,len(missing),64):
                    batch=missing[start:start+64];vectors=list(encoder.encode([t for h,t in batch]))
                    if len(vectors)!=len(batch):raise ValueError('编码数量不匹配')
                    for (h,_),vector in zip(batch,vectors):
                        v=normalized(vector);self.vectors[h]=v;self.encoded+=1
                        db.execute('INSERT INTO embeddings VALUES (?,?,?)',(model_id,h,json.dumps(v)))
                if len({len(v) for v in self.vectors.values()})>1:raise ValueError('向量维度不一致')
        finally:db.close()

    @property
    def status(self):
        return dict(path=self.path,dimension=len(next(iter(self.vectors.values()),[])),vectors=len(self.vectors),
                    cache_hits=self.cache_hits,encoded=self.encoded,model_id=self.model_id)

    def scores(self, query, blocks):
        q=normalized(list(self.encoder.encode([query]))[0]);result=[]
        for block in blocks:
            v=self.vectors[block['embedding_sha256']]
            if len(v)!=len(q):raise ValueError('查询向量维度不符')
            result.append(sum(x*y for x,y in zip(q,v)))
        return result


class TextbookRetriever:
    def __init__(self, blocks, dense=None, dense_error=''):
        self.blocks=blocks;self.dense=dense;self.dense_error=dense_error
        self.index=BM25Index([tokenize(b['text']) for b in blocks])

    def search(self, question, *, top_k=5, strict=False, chapter=None):
        if strict:return dict(hits=[],reason='教材全部UNVERIFIED，严格审核范围为空',dense_enabled=False)
        allowed=[i for i,b in enumerate(self.blocks) if chapter is None or b['chapter']==chapter]
        if not question.strip():return dict(hits=[],reason='问题为空',dense_enabled=False)
        channels=[];bm={};cos={};dense_ok=self.dense is not None;error=self.dense_error
        queries=expand_query(question)
        for query_index,query in enumerate(queries):
            values=self.index.score(tokenize(query))
            ids=sorted((i for i in allowed if values[i]>0),key=lambda i:(-values[i],self.blocks[i]['block_id']))[:30]
            # 原问题是用户明确的主题；扩展词是召回线索，不应与其等权挤占。
            channels.extend([ids]*(2 if query_index==0 else 1))
            for i in ids:bm[i]=max(bm.get(i,0),values[i])
        lexical_channels=list(channels)
        if self.dense:
            try:
                for query_index,query in enumerate(queries):
                    values=self.dense.scores(query,self.blocks)
                    ids=sorted((i for i in allowed if values[i]>0),key=lambda i:(-values[i],self.blocks[i]['block_id']))[:30]
                    channels.extend([ids]*(2 if query_index==0 else 1))
                    for i in ids:cos[i]=max(cos.get(i,-1),values[i])
            except Exception as exc:
                channels=lexical_channels;cos={};dense_ok=False;error=type(exc).__name__
        scores={}
        for ids in channels:
            for rank,i in enumerate(ids,1):scores[i]=scores.get(i,0)+1/(60+rank)
        ordered=sorted(scores,key=lambda i:(-scores[i],self.blocks[i]['block_id']))[:max(1,min(top_k,30))]
        hits=[dict(block=self.blocks[i],rank=rank,score=scores[i],score_type='rrf',
                   bm25_score=bm.get(i),dense_cosine=cos.get(i),review_status='UNVERIFIED') for rank,i in enumerate(ordered,1)]
        return dict(hits=hits,dense_enabled=dense_ok,dense_reason=error,
                    queries=list(queries),original_query_weight=2,
                    mode='bm25+bge+rrf' if dense_ok else 'bm25_expansion+rrf',
                    bm25_candidates=len(bm),dense_candidates=len(cos),reason='相关性排序不代表证据充分；教材待审核，未接入考试路由')
