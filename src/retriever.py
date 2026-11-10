"""严格/扩展双范围检索：中文分词 + BM25 + 关键词覆盖率 + 证据状态标记。"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace, field
from src.query_expansion import expand_query, is_case_question, comparison_sides, theory_explanation_strength
from src.dense_index import page_id
from typing import Any, Iterable

from src.evidence import analyze_question, topic_match, plan_evidence, has_payload, body_paragraphs, heading
from src.bm25 import BM25Index
from src.corpus import Corpus, Page
from src.text_utils import (
    compact_text,
    has_direct_definition,
    is_definition_question,
    query_phrases,
    query_terms,
    shorten,
    tokenize,
)


MODE_STRICT = "strict"
MODE_EXPANDED = "expanded"
MODE_LABELS = {
    MODE_STRICT: "严格检索（仅严格合格页）",
    MODE_EXPANDED: "扩展检索（全部有文本页，含未审核）",
}
VALID_MODES = frozenset(MODE_LABELS)


@dataclass(frozen=True)
class Hit:
    page: Page
    score: float
    bm25_score: float
    coverage: float
    matched_terms: tuple[str, ...]
    phrase_match: bool
    snippet: str
    duplicate_count: int = 0
    rank: int = 0
    dense_score: float | None = None
    score_type: str = "bm25_adjusted"

    @property
    def evidence_id(self):
        return page_id(self.page)

    @property
    def citation(self) -> str:
        return self.page.citation

    @property
    def location(self) -> str:
        return self.page.location

    @property
    def review_label(self) -> str:
        return self.page.review_label

    @property
    def strict_eligible(self) -> bool:
        return self.page.strict_eligible

    @property
    def evidence_status(self) -> str:
        return self.page.evidence_status

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "evidence_id": self.evidence_id,
            "filename": self.page.filename,
            "page_number": self.page.page_number,
            "citation": self.citation,
            "location": self.location,
            "filename_with_page": self.location,
            "score": round(self.score, 4),
            "score_type": self.score_type,
            "dense_cosine_max": self.dense_score,
            "bm25_score": round(self.bm25_score, 4),
            "coverage": round(self.coverage, 4),
            "matched_terms": list(self.matched_terms),
            "phrase_match": self.phrase_match,
            "snippet": self.snippet,
            "duplicate_count": self.duplicate_count,
            "review_category": self.page.review_category,
            "repair_applied": self.page.repair_applied,
            "review_label": self.review_label,
            "strict_eligible": self.strict_eligible,
            "evidence_status": self.evidence_status,
            "page_status": self.page.page_status,
            "page_status_label": self.page.page_status_label,
            "review_note": self.page.review_note,
        }


@dataclass(frozen=True)
class SearchResponse:
    query: str
    mode: str
    terms: tuple[str, ...]
    hits: tuple[Hit, ...]
    pool_size: int
    strict_pool_size: int
    expanded_pool_size: int
    dropped_low_relevance: int = 0
    duplicates_merged: int = 0
    diagnostics: dict = field(default_factory=dict)

    @property
    def enough_evidence(self) -> bool:
        """主题身份和所问关系必须有正文支持，相关度不等于证据充分。"""
        return plan_evidence(self.query, self.hits).supported

    @property
    def has_unreviewed(self) -> bool:
        return any(hit.evidence_status == "unreviewed" for hit in self.hits)

    @property
    def has_hold(self) -> bool:
        return any(hit.evidence_status == "reviewed_hold" for hit in self.hits)

    @property
    def evidence_warning(self) -> str:
        if self.mode == MODE_STRICT:
            return ""
        parts = []
        if self.has_unreviewed:
            parts.append("检索结果包含未审核页面")
        if self.has_hold:
            parts.append("检索结果包含已审核但未通过严格标准的页面")
        if not parts:
            return ""
        return "；".join(parts) + "，以下内容不能视为已核实结论，请对照原文页码复核。"

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "diagnostics": self.diagnostics,
            "mode": self.mode,
            "mode_label": MODE_LABELS.get(self.mode, self.mode),
            "terms": list(self.terms),
            "pool_size": self.pool_size,
            "strict_pool_size": self.strict_pool_size,
            "expanded_pool_size": self.expanded_pool_size,
            "dropped_low_relevance": self.dropped_low_relevance,
            "duplicates_merged": self.duplicates_merged,
            "enough_evidence": self.enough_evidence,
            "has_unreviewed": self.has_unreviewed,
            "has_hold": self.has_hold,
            "evidence_warning": self.evidence_warning,
            "hits": [hit.to_dict() for hit in self.hits],
        }


def quality_score(content: str) -> float:
    """旧版启发式质量分，仅作为排序的轻微调节项。"""
    score = 0.0
    prefix = content[:120]
    outline_markers = ("课程目录", "课程内容", "教学内容", "本章目录", "主要内容")
    if any(marker in prefix for marker in outline_markers):
        score -= 25

    numbered_items = sum(f"{index}、" in content or f"{index}." in content for index in range(1, 7))
    if numbered_items >= 3 and len(content) < 250:
        score -= 20

    explanation_markers = ("是指", "原因", "主要包括", "应当", "必须", "原则", "例如", "导致", "因此")
    score += min(sum(marker in content for marker in explanation_markers) * 3, 12)

    history_markers = ("国内的工程伦理学研究与教育", "国外的工程伦理学研究与教育", "工程伦理学的发展")
    if any(marker in prefix for marker in history_markers):
        score -= 12
    return score


def _make_snippet(text: str, terms: Iterable[str], max_chars: int = 380) -> str:
    flat = re.sub(r"\s+", " ", text or "").strip()
    if not flat:
        return ""
    lowered = flat.casefold()
    positions = [
        position
        for term in terms
        if (position := lowered.find(term.casefold())) >= 0
    ]
    if not positions:
        return shorten(flat, max_chars)

    position = min(positions)
    start = max(0, position - 90)
    end = min(len(flat), start + max_chars)
    if start > 0:
        boundary = max(flat.rfind(mark, max(0, position - 130), position) for mark in "。！？；")
        if boundary >= 0:
            start = boundary + 1
            end = min(len(flat), start + max_chars)
    snippet = flat[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(flat):
        snippet = snippet.rstrip() + "…"
    return snippet


class Retriever:
    """对严格页与扩展页分别建立 BM25 索引。"""

    def __init__(self, corpus: Corpus, *, top_k_default: int = 6, retrieval_mode="hybrid", dense_index=None, dense_status=None) -> None:
        self.retrieval_mode=retrieval_mode
        self.dense_index=dense_index
        self.dense_status=dense_status or (getattr(dense_index,"status",{"state":"ready"}) if dense_index is not None else {"state":"unavailable"})
        self.corpus = corpus
        self.top_k_default = top_k_default
        self._pools: dict[str, tuple[Page, ...]] = {
            MODE_STRICT: corpus.strict_pages,
            MODE_EXPANDED: corpus.expanded_pages,
        }
        self._tokens: dict[tuple[str, int], tuple[str, ...]] = {}
        self._compact: dict[tuple[str, int], str] = {}
        for page in corpus.expanded_pages:
            key = (page.filename, page.page_number)
            self._tokens[key] = tokenize(page.text)
            self._compact[key] = compact_text(page.text)
        self._indexes: dict[str, BM25Index] = {
            mode: BM25Index([self._tokens[(page.filename, page.page_number)] for page in pages])
            for mode, pages in self._pools.items()
        }

    @property
    def stats(self) -> dict[str, Any]:
        return self.corpus.stats()

    def _phrase_match(
        self,
        compact_phrases: tuple[str, ...],
        terms: tuple[str, ...],
        page: Page,
    ) -> bool:
        key = (page.filename, page.page_number)
        compact_page = self._compact.get(key, "")
        # 只有 4 字及以上的短语才具备区分度；“工程师”“应对”等短词仍走覆盖率。
        if any(len(phrase) >= 4 and phrase in compact_page for phrase in compact_phrases):
            return True
        return any(len(term) >= 4 and term in compact_page for term in terms)

    def search(self,query,*,mode=MODE_STRICT,top_k=None):
        limit=self.top_k_default if top_k is None else max(1,int(top_k))
        base=self._search_original(query,mode=mode,top_k=limit)
        queries=expand_query(query) if self.retrieval_mode!='legacy' else (query,)
        diag=dict(active_mode="bm25_legacy" if self.retrieval_mode=="legacy" else "bm25",dense_enabled=False,vector_index=self.dense_status,original_question=query,subqueries=list(queries),bm25_hits=len(base.hits),dense_hits=0,
                  fused_candidates=len(base.hits),fallback=self.dense_index is None,
                  fallback_reason='Dense未配置；使用本地BM25' if self.dense_index is None else '',
                  selected_pages=[dict(evidence_id=h.evidence_id,filename=h.page.filename,page_number=h.page.page_number) for h in base.hits])
        # 简单问题已有可作答证据时保持旧排序；案例题才组合多知识点。
        if self.retrieval_mode=='legacy' or (base.enough_evidence and not is_case_question(query) and self.dense_index is None):
            return replace(base,diagnostics=diag)
        channels=[];lookup={};bm_ids=set();dense_ids=set();seeds=[];dense_scores={}
        for q in queries:
            result=self._search_original(q,mode=mode,top_k=max(10,limit))
            ids=[]
            for h in result.hits:
                key=page_id(h.page);lookup[key]=h;ids.append(key);bm_ids.add(key)
            channels.append(ids)
            if is_case_question(query):
                ordered=sorted(result.hits,key=lambda h:compact_text(q).replace('的','') in compact_text(h.page.text).replace('的',''),reverse=True)
                planned=plan_evidence(q,ordered)
                if planned.quotes:
                    primary=max(planned.quotes,key=lambda pair:compact_text(q).replace('的','') in compact_text(pair[1]).replace('的',''))
                    seed=page_id(primary[0].page)
                    if seed not in seeds:seeds.append(seed)
        if self.dense_index is not None:
            allowed={page_id(p) for p in self._pools[mode]}
            pages={page_id(p):p for p in self._pools[mode]}
            try:
                for q in queries:
                    ids=[]
                    for key,cosine in self.dense_index.search(q,allowed,max(10,limit)):
                        if key not in allowed:continue
                        if key not in lookup:
                            p=pages[key];lookup[key]=Hit(p,0.,0.,0.,(),False,_make_snippet(p.text,()))
                        dense_scores[key]=max(dense_scores.get(key,-1.),float(cosine))
                        ids.append(key);dense_ids.add(key)
                    channels.append(ids)
            except Exception:
                diag.update(fallback=True,fallback_reason='Dense不可用；回退BM25')
                channels=[c for c in channels[:len(queries)]];dense_ids=set();dense_scores={}
        scores=reciprocal_rank_fusion(channels)
        ranked=sorted(scores,key=lambda k:(-scores[k],k))
        if is_case_question(query):
            # 案例题进行知识点覆盖重排；RRF负责通道融合，不将分数当作验证。
            ranked=seeds+[key for key in ranked if key not in seeds]
        sides=comparison_sides(query) if self.retrieval_mode!='legacy' else ()
        if sides:
            # 每侧解释页各取一个，保留其余候选RRF次序，避免理论名单挤占。
            representatives=[]
            for group in sides:
                choices=[key for key in ranked if theory_explanation_strength(lookup[key].page.text,group)>0]
                if choices:
                    key=max(choices,key=lambda key:(theory_explanation_strength(lookup[key].page.text,group),scores[key]))
                    if key not in representatives:representatives.append(key)
            ranked=representatives+[key for key in ranked if key not in representatives]
        # 仅对明确列举/具体数量题提升“主体匹配且有直接答案结构”的页面。
        # 稳定分组不改变组内RRF顺序，也不提升只有关键词的标题/目录。
        ranked=sorted(ranked,key=lambda key:not direct_answer_page(query,lookup[key].page))
        hits=tuple(replace(lookup[k],score=scores[k],rank=i,dense_score=dense_scores.get(k),score_type="rrf") for i,k in enumerate(ranked[:limit],1))
        diag.update(active_mode="bm25+bge+rrf" if self.dense_index is not None and not diag["fallback"] else "bm25_expansion+rrf",dense_enabled=self.dense_index is not None and not diag["fallback"],bm25_hits=len(bm_ids),dense_hits=len(dense_ids),fused_candidates=len(ranked))
        diag['selected_pages']=[dict(evidence_id=h.evidence_id,filename=h.page.filename,page_number=h.page.page_number) for h in hits]
        response=replace(base,hits=hits,diagnostics=diag)
        diag['insufficient_reason']='' if response.enough_evidence else '候选相关，但未找到足够的主题与实质正文；不视为已验证依据'
        return response

    def _search_original(
        self,
        query: str,
        *,
        mode: str = MODE_STRICT,
        top_k: int | None = None,
    ) -> SearchResponse:
        if mode not in VALID_MODES:
            raise ValueError(f"未知检索范围：{mode}，可选 {sorted(VALID_MODES)}")
        query = (query or "").strip()
        limit = self.top_k_default if top_k is None else max(1, int(top_k))
        terms = query_terms(query)
        strict_size = len(self._pools[MODE_STRICT])
        expanded_size = len(self._pools[MODE_EXPANDED])
        if not terms:
            return SearchResponse(
                query=query,
                mode=mode,
                terms=(),
                hits=(),
                pool_size=len(self._pools[mode]),
                strict_pool_size=strict_size,
                expanded_pool_size=expanded_size,
            )

        pages = self._pools[mode]
        index = self._indexes[mode]
        scores = index.score(terms)
        idf = {term: index.idf(term) for term in terms}
        total_idf = sum(idf.values()) or 1.0
        compact_phrases = tuple(
            compact
            for phrase in query_phrases(query)
            if len(compact := compact_text(phrase)) >= 2
        )
        definition_query = is_definition_question(query)
        profile = analyze_question(query)
        min_coverage = 1.0 if len(terms) == 1 else 0.5 if len(terms) == 2 else 0.34

        candidates: list[Hit] = []
        dropped = 0
        for position, page in enumerate(pages):
            bm25_score = scores[position]
            matched = tuple(term for term in terms if index.document_matches(position, term))
            coverage = sum(idf[term] for term in matched) / total_idf
            phrase = self._phrase_match(compact_phrases, terms, page)
            if bm25_score <= 0 and not phrase:
                continue
            subject_match = topic_match(profile, page.text)
            if not phrase and not subject_match and coverage < min_coverage:
                dropped += 1
                continue
            score = (
                bm25_score
                + (18.0 if subject_match else 0.0)
                + (12.0 if subject_match and has_payload(profile, page.text) else 0.0)
                + 2.5 * coverage
                + (2.0 if phrase else 0.0)
                + quality_score(page.text) / 20.0
            )
            # 扩展检索仍优先展示严格合格证据；未审核页只在相关内容上补充。
            if mode == MODE_EXPANDED and page.strict_eligible:
                score += 2.0
            # 定义类问题优先展示直接定义，避免把“工程伦理规范是指……”当成
            # 对“工程伦理”的定义。
            if definition_query and has_direct_definition(query, page.text):
                score += 6.0
            candidates.append(
                Hit(
                    page=page,
                    score=score,
                    bm25_score=bm25_score,
                    coverage=coverage,
                    matched_terms=matched,
                    phrase_match=phrase,
                    snippet=_make_snippet(page.text, matched or terms),
                )
            )

        # 同标题的相邻页可能是跨页列表；只在当前池中提升，不跨审核范围。
        anchors = [h for h in candidates if topic_match(profile,h.page.text) and has_payload(profile,h.page.text)]
        if anchors:
            best = max(anchors,key=lambda h:h.score)
            section_heading = heading(best.page.text)
            existing = {(h.page.filename,h.page.page_number) for h in candidates}
            for position,page in enumerate(pages):
                if (page.filename,page.page_number) in existing:continue
                if page.filename==best.page.filename and abs(page.page_number-best.page.page_number)==1 and heading(page.text)==section_heading and has_payload(profile,page.text):
                    matched=tuple(term for term in terms if index.document_matches(position,term))
                    candidates.append(Hit(page,best.score-1,scores[position],sum(idf[t] for t in matched)/total_idf,matched,self._phrase_match(compact_phrases,terms,page),_make_snippet(page.text,matched or terms)))
            candidates = [replace(h,score=max(h.score,best.score-1)) if
                h.page.filename==best.page.filename and abs(h.page.page_number-best.page.page_number)==1
                and heading(h.page.text)==section_heading and has_payload(profile,h.page.text)
                else h for h in candidates]


        candidates.sort(
            key=lambda hit: (
                hit.score,
                hit.coverage,
                hit.bm25_score,
                hit.page.filename,
                -hit.page.page_number,
            ),
            reverse=True,
        )

        # 完全相同的正文只保留一条来源，避免同一幻灯片多次占位。
        # 扩展检索中若重复页同时存在严格合格来源，优先保留严格来源。
        unique: list[Hit] = []
        seen: dict[str, int] = {}
        merged = 0
        for hit in candidates:
            key = self._compact.get((hit.page.filename, hit.page.page_number), "")
            if not key:
                key = compact_text(hit.page.text)
            if key in seen:
                existing_index = seen[key]
                existing = unique[existing_index]
                if not existing.strict_eligible and hit.strict_eligible:
                    unique[existing_index] = replace(
                        hit, duplicate_count=existing.duplicate_count + 1
                    )
                else:
                    unique[existing_index] = replace(
                        existing, duplicate_count=existing.duplicate_count + 1
                    )
                merged += 1
                continue
            seen[key] = len(unique)
            unique.append(hit)

        unique.sort(
            key=lambda hit: (
                hit.score,
                hit.coverage,
                hit.bm25_score,
                hit.page.filename,
                -hit.page.page_number,
            ),
            reverse=True,
        )
        ranked = tuple(
            replace(hit, rank=rank) for rank, hit in enumerate(unique[:limit], start=1)
        )
        return SearchResponse(
            query=query,
            mode=mode,
            terms=terms,
            hits=ranked,
            pool_size=len(pages),
            strict_pool_size=strict_size,
            expanded_pool_size=expanded_size,
            dropped_low_relevance=dropped,
            duplicates_merged=merged,
        )


def reciprocal_rank_fusion(channels,k=60):
    scores={}
    for channel in channels:
        seen=set()
        for rank,key in enumerate(channel,1):
            if key in seen:continue
            seen.add(key);scores[key]=scores.get(key,0.)+1/(k+rank)
    return scores


def direct_answer_page(query, page):
    """只作排序信号，不代表事实验证；不使用题号、文件名或固定页码。"""
    if is_case_question(query) or is_definition_question(query) or re.search(r'关系|联系|区别|比较|为什么|原因|如何理解|概念',query):
        return False
    listing=bool(re.search(r'有哪些(?:方式|方法|措施|项目|方面)|包括哪|哪[几一二三四五六七八九十两0-9]*[项种类]|[一二三四五六七八九十两0-9]+种.*方式',query))
    numerical=bool(re.search(r'伤亡|死亡人数|受伤人数|经济损失|金额|多少人',query))
    if not (listing or numerical):
        return False
    profile=analyze_question(query)
    if not topic_match(profile,page.text) or not has_payload(profile,page.text):
        return False
    if listing:
        # 清单必须有实际条目，而非“包含五种方式”的引入句。
        markers=re.findall(r'[①②③④⑤⑥⑦⑧⑨⑩]|(?:^|\n)\s*[1-9][)）、]',page.text)
        return len(set(marker.strip() for marker in markers))>=2
    text=page.text
    if re.search(r'伤亡|死亡人数|受伤人数|多少人',query) and not re.search(r'\d+(?:\.\d+)?\s*(?:人|名)',text):
        return False
    if re.search(r'损失|金额',query) and not re.search(r'\d+(?:\.\d+)?\s*(?:亿|万)?元',text):
        return False
    return True
