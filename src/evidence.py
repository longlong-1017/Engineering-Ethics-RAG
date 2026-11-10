"""离线、保守的证据规划：主题身份与问题所需关系必须同时出现在正文中。

不读取题库、金标页或答案词表；候选只来自当前检索范围。
它是可审计的词法/结构约束，不声称具有通用语义蕴含能力。
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from src.text_utils import compact_text, has_direct_definition, is_definition_question, is_outline_page, join_wrapped_lines, query_terms

NOISE = ('电子信息工程学院自动化教研室','谢谢','end')
FACET_RE = r'时间|地点|后果|伤亡|直接经济损失|经济损失|设计参数|桥梁设计参数|用途|动机|直接原因|根本原因|结果'


def identity(text):
    return re.sub(r'的|中|现代|相关|活动', '', compact_text(text))


@dataclass(frozen=True)
class Question:
    text: str
    kind: str
    subject: str
    focus: tuple[str,...]
    dates: tuple[str,...]


def analyze_question(question: str) -> Question:
    text = question.strip()
    if is_definition_question(text): kind='definition'
    elif re.search(r'为什么|为何|原因|(?<!发)动机',text): kind='reason'
    elif re.search(r'结果|后果|伤亡|损失|多少|时间|地点|用途|参数|决定',text): kind='fact'
    elif re.search(r'哪些|哪.*[种类层]|包括|[两二三四五六七八九十0-9]+种|方式|思路',text): kind='list'
    else: kind='explanation'
    # 主体先于提问动作；不把“结果是什么”中的结果当作概念。
    first = re.split(r'[？?；;，,]',text)[0]
    subject = re.sub(r'^(?:请问|请|简述|简要说明|说明|什么是|何为|何谓)', '',first)
    subject = re.split(r'为什么|为何|如何|应(?:承担|做到|当|该)|包括|有哪些|有哪|是什么|指什么|的定义|的概念',subject)[0]
    subject = re.split(r'的(?='+FACET_RE+r')',subject)[0]
    subject = re.sub(r'(?:事故|事件)?中$', '',subject)
    subject = re.sub(r'的[两二三四五六七八九十0-9]+种.*$', '',subject)
    subject = re.sub(r'(?:的)?(?:用途|后果|结果|动机|含义|内涵)[？?]?$', '',subject)
    subject = re.sub(r'[？?。]+$', '',subject)
    focus = []
    # 所问的关系必须出现在正文，不能只凭机构或学科名回答。
    for marker in ('综合性','社会公正','目的','意义','研究方法','可接受性','社会责任','理解','回避','信息公开'):
        if marker in text: focus.append(marker)

    quoted = re.findall(r'[“「"]([^”」"]{2,})[”」"]',text)
    if quoted:
        focus.extend(quoted)
        subject = re.split(r'[“「"]',subject)[0]
    # 动作的宾语是要检索的主题，动作本身仍是必需关系。
    action = re.search(r'(回避|应对|处理)(.+?)(?:的|[？?]|$)',text)
    if action and kind != 'reason':
        focus.append(action[1]);subject=action[2]
    if '座谈会' in subject:
        focus.append('座谈会');subject=subject.split('公众参与')[0].split('座谈会')[0]
    subject=re.sub(r'(事件|事故|问题)$','',subject)
    dates=tuple(re.findall(r'\d{4}年\d{1,2}月\d{1,2}日',text))
    return Question(text,kind,subject,tuple(focus),dates)


def topic_match(profile: Question, text: str) -> bool:
    body=identity(text);subject=identity(profile.subject)
    if any(not any(identity(alt) in body for alt in ({'理解':('理解','思路')}.get(f,(f,)))) for f in profile.focus): return False
    if profile.dates and any(compact_text(date) not in compact_text(text) for date in profile.dates): return False
    if not subject: return bool(profile.focus)
    if subject in body: return True
    if len(subject)<=4: return False
    if subject.endswith('学') and len(subject)>=5 and subject[:-1] in body: return True
    # 细分主题必须保留修饰语，防止把技术因素回答成人为因素。
    if re.search(r'因素|原则|规范|责任|目的|意义|方法|能力',subject):
        pieces=re.split(r'中的|的|中',profile.subject)
        last=identity(pieces[-1])
        return len(last)>=4 and last in body and (identity(pieces[0]).rstrip('学') in body or any(identity(t) in body for t in query_terms(pieces[0]) if len(t)>=3))
    # 长对象可以分散书写（如地名+爆炸）；至少要求最长实词命中，不能只靠“事故/损失”。
    terms=[t for t in query_terms(profile.subject) if t not in {'工程','伦理','事故','事件','问题','包括','公正','分配','活动','公众','参与'}]
    if not terms: return False
    longest=max(map(len,terms))
    anchors=[identity(t) for t in terms if len(t)==longest]
    if longest>=3:
        if not all(anchor in body for anchor in anchors): return False
        # 分配等限定关系仍须满足，不能用器官移植目录作答分配问题。
        for relation in ('公正分配','隐私','信息公开'):
            if relation in subject and relation not in body:return False
        return True
    return all(identity(t) in body for t in terms)


def body_paragraphs(text):
    clean='\n'.join(line for line in text.splitlines() if compact_text(line) not in NOISE)
    return [p for p in join_wrapped_lines(clean) if compact_text(p)]


def plain_list_items(text):
    lines=[line.strip() for line in text.splitlines() if compact_text(line) and compact_text(line) not in NOISE]
    items=lines[1:]
    if len(items)>=3 and all(4<=len(compact_text(line))<=24 and not re.search(r'[，,。；;：:！？]',line) for line in items):
        return items
    return []


def list_structure(text):
    markers=re.findall(r'[①②③④⑤⑥⑦⑧⑨⑩]|(?:^|\n)\s*[1-9][)）]',text)
    named=re.findall(r'(?:由|、|和|及|：)([\u4e00-\u9fff]{2,6}原则)',text)
    return max(len(plain_list_items(text)),len(markers),len(named))


def has_payload(profile: Question, text: str) -> bool:
    if is_outline_page(text): return False
    if profile.kind=='list' and plain_list_items(text): return True
    paras=body_paragraphs(text)
    body='\n'.join(paras)
    if profile.kind=='definition':return has_direct_definition(profile.text,text)
    # 标题与目录中的长短语不是事实或解释。
    substantive=[p for p in paras if len(compact_text(p))>=28 or re.search(r'[①②③④⑤⑥⑦⑧⑨⑩]|[1-9][)）]|第一|第二|第三',p)]
    if not substantive and not re.search(r'包括|是指|时间[：:]|地点[：:]',body):return False
    if profile.kind=='reason':
        if '动机' in profile.text:return bool(re.search(r'动机|为了|出于|私利|利益',body))
        return bool(re.search(r'因为|由于|导致|原因|因此|才能|否则|为了|使得|总是|包含|要素|利益|责任',body))
    if profile.kind=='fact':
        if '结果' in profile.text and not re.search(r'结果|造成|导致|爆炸|死亡|殉职|反对|支持|召回|畸形|伤|坍塌|毁',body):return False
        if re.search(r'伤亡|损失|多少',profile.text) and not re.search(r'\d+(?:\.\d+)?(?:人|多|亿|万|%|米|m|年)',body):return False
        if '决定' in profile.text and not re.search(r'决定|宣布|通过|批准|否决|缓建|停建',body):return False
    if profile.kind=='list':
        count = re.search(r'([两二三四五六七八九十0-9]+)(?:种|层)',profile.text)
        declared = re.findall(r'([两二三四五六七八九十0-9]+)(?:种|层)',body)
        relevant_count = any(any(f in p for f in profile.focus) and re.search(r'[两二三四五六七八九十0-9]+(?:种|层)',p) for p in paras) if profile.focus else True
        if count and declared and relevant_count and count[1] not in declared: return False
        return bool(re.search(r'[①②③④⑤⑥⑦⑧⑨⑩]|[1-9][)）]|[一二三四五]是|包括|分为|构成|含义|第一|培养|主要表现在|有限的资源|还要|保证|既有',body))
    return True


def heading(text):
    lines=[compact_text(line) for line in text.splitlines() if compact_text(line)]
    return lines[0] if lines else ''


def fact_features(question, text):
    features=set()
    patterns=(('时间',r'\d{4}年|\d{4}[.．]\d'),('地点',r'地点|省|市|县|中心'),
              ('参数',r'米|\d+(?:\.\d+)?m'),('伤亡',r'死亡|死|伤|殉职'),
              ('损失',r'亿元|万元|损失'),('用途',r'用于|治疗|控制|防止|安眠|用途'),
              ('结果',r'反对|支持|造成|导致|畸形|死亡|召回|宣布|爆炸|殉职'),
              ('污染物',r'三聚|污染|检测'),('健康',r'肾|患|疾病|健康影响'))
    for key,pattern in patterns:
        requested=key in question or key=='结果' and '后果' in question
        if requested and re.search(pattern,text):features.add(key)
    return features


@dataclass(frozen=True)
class EvidencePlan:
    quotes: tuple  # (Hit, 原文段落)
    checks: tuple[dict,...]

    @property
    def supported(self):return bool(self.quotes)


def plan_evidence(question: str, hits) -> EvidencePlan:
    from src.query_expansion import comparison_sides, theory_explanation_strength
    sides=comparison_sides(question)
    if sides:
        selected={};checks=[]
        for group in sides:
            choices=[]
            for hit in hits:
                strength=theory_explanation_strength(hit.page.text,group)
                checks.append(dict(rank=hit.rank,comparison_side=group[0],substantive=bool(strength)))
                if strength and not is_outline_page(hit.page.text):choices.append((strength,hit))
            if not choices:return EvidencePlan((),tuple(checks))
            _,hit=max(choices,key=lambda item:(item[0],-item[1].rank))
            selected[(hit.page.filename,hit.page.page_number)]=(hit,'\n'.join(body_paragraphs(hit.page.text)))
        return EvidencePlan(tuple(selected.values()),tuple(checks))
    profile=analyze_question(question)
    checks=[];accepted=[]
    for hit in hits:
        topic=topic_match(profile,hit.page.text)
        payload=has_payload(profile,hit.page.text) if topic else False
        checks.append(dict(rank=hit.rank,topic_match=topic,payload=payload,kind=profile.kind,subject=profile.subject))
        if topic and payload:accepted.append(hit)
    # 先取直接证据，再保留同一小节的互补内容；不把所有相关页都当答案。
    if accepted:
        primary=accepted[0]
        if profile.kind=='fact':
            primary=max(accepted,key=lambda h:len(fact_features(question,h.page.text)))
        if profile.kind=='list':
            structured=max(accepted,key=lambda h:list_structure(h.page.text))
            if list_structure(structured.page.text)>=3:primary=structured
            count=re.search(r'([两二三四五六七八九十0-9]+)(?:种|层)',question)
            if count:
                exact=[h for h in accepted if re.search(re.escape(count[1])+r'(?:种|层)',h.page.text)]
                if exact:primary=exact[0]
        selected=[primary]
        # “关系/联系/影响”类问题通常需要多页互补（如安全页 + 公正页），
        # 只保留一页会让模型拿到残缺证据。这里只取已通过主题和正文检查的页。
        relationship = bool(re.search(r'关系|联系|影响|作用|为什么', question)) and profile.kind == 'explanation'
        if relationship:
            selected = list(accepted[:4])
        count_match=re.search(r'([两二三四五六七八九十0-9]+)(?:种|层)',question)
        numeral={'两':2,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
        requested_count=(int(count_match[1]) if count_match and count_match[1].isdigit() else numeral.get(count_match[1],0) if count_match else 0)
        circled='①②③④⑤⑥⑦⑧⑨⑩'
        complete_list=bool(requested_count and requested_count<=10 and all(circled[i] in primary.page.text or re.search(rf'(?:^|\n)\s*{i+1}[)）]',primary.page.text) for i in range(requested_count)))
        # 完整的无编号短行清单无需附带整页背景论述。
        complete_plain=profile.kind=='list' and bool(plain_list_items(primary.page.text))
        named_items=re.findall(r'(?:由|、|和|及|：)([\u4e00-\u9fff]{2,6}原则)',primary.page.text)
        covered=fact_features(question,primary.page.text)
        for hit in ([] if relationship else hits):
            if hit==primary or complete_list or complete_plain:continue
            same_file=hit.page.filename==primary.page.filename
            same_heading=same_file and heading(hit.page.text)==heading(primary.page.text)
            same_topic=hit in accepted
            adjacent=same_file and abs(hit.page.page_number-primary.page.page_number)<=1
            continued=bool(re.search(r'二是|其次|再次|第三|②|[34][)）]',hit.page.text))
            if profile.kind=='fact':
                features=fact_features(question,hit.page.text)
                keep=same_topic and (bool(features-covered) or same_heading and adjacent and hit.page.page_number<primary.page.page_number and bool(features))
                if keep: covered |= features
            else:
                keep=profile.kind in {'list','reason'} and same_heading and (same_topic or adjacent and continued and hit.page.page_number>primary.page.page_number) and has_payload(profile,hit.page.text)
            if keep and profile.kind=='list' and len(named_items)>=3 and not any(item in hit.page.text for item in named_items):keep=False
            if keep:selected.append(hit)
        accepted=selected
    # 保留同一主体的正文，不把高覆盖率无关页作为兜底引用。
    quotes=[];seen=set()
    accepted.sort(key=lambda hit:(hit.page.filename,hit.page.page_number))
    for hit in accepted[:5]:
        paras=body_paragraphs(hit.page.text)
        # 先保留全段，避免按句截断编号项、百分比范围和案例结果。
        text='\n'.join(paras)
        if text not in seen:
            quotes.append((hit,text));seen.add(text)
    if not quotes:
        from src.query_expansion import expand_query, is_case_question
        if is_case_question(question):
            groups=[];combined={};primary=[]
            for subquery in expand_query(question)[1:]:
                ordered=sorted(hits,key=lambda hit:identity(subquery) in identity(hit.page.text),reverse=True)
                sub=plan_evidence(subquery,ordered)
                if sub.quotes:
                    groups.append(subquery)
                    primary.append(max(sub.quotes,key=lambda pair:identity(subquery) in identity(pair[1])))
                for hit,text in sub.quotes:combined[(hit.page.filename,hit.page.page_number)]=(hit,text)
            # 仅作为案例分析所需的相关课件背景；不证明案例叙述本身为课件事实。
            if len(groups)>=2 and len(combined)>=2:
                ordered={}
                for hit,text in primary+list(combined.values()):ordered[(hit.page.filename,hit.page.page_number)]=(hit,text)
                quotes=list(ordered.values())[:5]
    return EvidencePlan(tuple(quotes),tuple(checks))
