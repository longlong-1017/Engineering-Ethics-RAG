"""Streamlit 网页界面：提问、答案、原文证据与 PDF 页码。"""

from __future__ import annotations

import sys
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from src.api_limits import LimitError, RequestLimiter
from src.dense_index import load_project_dense_status
from src.config import Settings
from src.corpus import CorpusError, REVIEW_CATEGORY_LABELS, UNREVIEWED_LABEL, load_corpus
from src.qa import (
    PROVIDER_AUTO,
    PROVIDER_LOCAL,
    QA_MODE_GENERAL,
    QA_MODE_HYBRID,
    QA_MODE_LABELS,
    QA_MODE_RAG,
    VERIFICATION_FAILED,
    VERIFICATION_UNVERIFIED,
    AnswerEngine,
    STATUS_ERROR,
    STATUS_INSUFFICIENT,
)
from src.retriever import MODE_STRICT, Retriever
from src.text_utils import query_terms


EXAMPLES = [
    "工程风险的技术因素有哪些？",
    "工程师在利益冲突中应如何应对？",
    "公众安全、健康和福利为什么应优先？",
    "环境工程中的安全与社会公正有什么关系？",
    "责任伦理与法律责任有什么区别？",
    "工程伦理中的功利主义与义务论有什么区别？",
]


@st.cache_resource(show_spinner=False)
def load_runtime():
    settings = Settings.from_env()
    corpus = load_corpus(settings.data_dir)
    dense,dense_status=load_project_dense_status(corpus)
    return settings, corpus, Retriever(corpus,dense_index=dense,dense_status=dense_status)



MOBILE_CSS = """<style>
@media (max-width: 768px) {
  [data-testid="stMainBlockContainer"] { padding: 1rem .85rem 2rem; }
  [data-testid="stMain"] h1 { font-size: 1.5rem; }
  [data-testid="stMain"] h2 { font-size: 1.25rem; }
  [data-testid="stMain"] textarea, [data-testid="stMain"] input { font-size: 16px !important; }
  [data-testid="stMain"] button { min-height: 44px; white-space: normal; }
  [data-testid="stMain"] [data-testid="stVerticalBlock"] { min-width: 0; }
}
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li,
[data-testid="stCaptionContainer"] { overflow-wrap: anywhere; }
[data-testid="stMain"] pre { white-space: pre-wrap; overflow-wrap: anywhere; }
[data-testid="stMain"] table { display: block; max-width: 100%; overflow-x: auto; }
</style>"""


def answer_keywords(answer, limit=8, body=None):
    """仅从已展示的答题内容摘取词项，不调用模型，不从扩展词制造新论点。"""
    if answer.status in (STATUS_ERROR, STATUS_INSUFFICIENT):
        return ()
    if body is None:
        body=re.split(r'【(?:参考|AI补充)',answer.answer)[0]
    body=re.sub(r'【[^】]*】|\[S\d+\]','',body)
    stop={'简明','答案','分点','论述','总结','包括','需要','应当','主要','可以','问题','方面','这种','因此','进行','相关','以及','同时','工程','伦理'}
    result=[]
    for term in (*answer.search.terms,*query_terms(body)):
        if (2<=len(term)<=8 and term not in stop and term in body
                and re.fullmatch(r'[\u4e00-\u9fff]+',term) and term not in result):
            result.append(term)
        if len(result)>=limit:break
    return tuple(result)


def answer_sections(text):
    # 只识别独占一行的顶层栏目，不能吃掉论点中的【基于课件的案例分析】。
    parts=re.split(r'(?m)^【(简明答案|分点论述|总结|参考依据|参考课件|AI补充[^】]*)】[ \t]*(?:\n|$)',text)
    return {parts[i]:parts[i+1].strip() for i in range(1,len(parts)-1,2)}


def compact_exam_answer(answer):
    """保守摘录：保留完整论点及其引用，不重写、不截数字/限定词、不凑要点。"""
    if (answer.status!='ok' or getattr(answer,'verification_status','unverified')!='verified'
            or getattr(answer,'general_knowledge',False)):
        return None
    sections=answer_sections(answer.answer)
    summary=sections.get('简明答案','').strip()
    details=sections.get('分点论述','')
    if not summary or not details:return None
    points=[m.group(1).strip() for m in re.finditer(
        r'^\s*\d+[.、)）]\s*(.+?)(?=^\s*\d+[.、)）]\s|\Z)',details,re.M|re.S)]
    if not points:return None
    sources={}
    for h in getattr(answer,'citations',()):
        sources[f'S{h.rank}']=(h.page.filename,h.page.page_number)
    for e in getattr(answer,'evidence_context',()):
        pair=(e['filename'],e['page_number'])
        if e['id'] in sources and sources[e['id']]!=pair:return None
        sources[e['id']]=pair
    if any(not filename or not isinstance(page,int) or isinstance(page,bool) or page<1
           for filename,page in sources.values()):
        return None
    chosen=points[:5]
    refs=[]
    for text in [summary,*chosen]:
        ids=re.findall(r'\[(S\d+)\]',text)
        if text in chosen and not ids:return None
        for ref in ids:
            if ref not in sources:return None
            if ref not in refs:refs.append(ref)
    if not refs:return None
    # 结论若带多句限定，保留原段而不擅自删减；不做生成式压缩。
    return dict(summary=summary,points=tuple(chosen),omitted=len(points)-len(chosen),
                sources=tuple((ref,*sources[ref]) for ref in refs),
                keywords=answer_keywords(answer,limit=5,body='\n'.join([summary,*chosen])))

def _status_markdown(hit) -> str:
    if hit.strict_eligible:
        return f":green[**{hit.page.strict_label}**]"
    if hit.evidence_status == "unreviewed":
        return f":orange[**{hit.review_label}**]"
    return f":red[**{hit.review_label}**]"


def render_evidence(hits, title: str) -> None:
    st.subheader(title)
    if not hits:
        st.info("没有可展示的证据页。")
        return
    for hit in hits:
        with st.container(border=True):
            st.markdown(f"**[S{hit.rank}] {hit.citation}**")
            st.markdown(_status_markdown(hit))
            with st.expander('检索分数与匹配词', expanded=False):
                matched = "、".join(hit.matched_terms) if hit.matched_terms else "无"
                st.caption(
                    f"关键词覆盖率 {hit.coverage:.0%}｜BM25原始分 {hit.bm25_score:.2f}｜{hit.score_type}排序分 {hit.score:.5f}｜"
                    f"匹配词：{matched}｜页面状态：{hit.page.page_status_label}"
                )
                if hit.dense_score is not None:
                    st.caption(f"BGE余弦相似度（子查询最大值）：{hit.dense_score:.4f}；RRF分数不是余弦相似度。")
            st.write(hit.snippet)
            if hit.duplicate_count:
                st.caption(f"相同正文还出现在其他 {hit.duplicate_count} 个页面。")
            if hit.page.review_note:
                st.caption(f"审核备注：{hit.page.review_note}")
            pdf_root=(ROOT / "data/pdfs").resolve()
            pdf=(pdf_root / hit.page.filename).resolve()
            if pdf.parent==pdf_root and pdf.is_file():
                st.download_button("下载来源PDF（请打开物理第%d页）" % hit.page.page_number,
                                   pdf.read_bytes(), file_name=pdf.name, mime="application/pdf",
                                   key=f"pdf_{title}_{hit.rank}_{hit.page.filename}_{hit.page.page_number}",on_click="ignore")
            with st.expander("查看该页完整提取文本"):
                st.text(hit.page.text or "（无文本）")
                st.caption(f"来源文件：{hit.page.filename}｜物理页码：{hit.page.page_number}")


def next_submission_status(settings, stats, *, ledger_ok=True):
    if not ledger_ok:
        return '费用统计账本不可用，API暂停；仍可离线摘录。'
    if not settings.api_enabled:
        return 'API总开关未开启（DEEPSEEK_API_ENABLED=false）；仅使用离线摘录。'
    if stats.get('budget_blocked'):
        return '每日估算预算或保护预留已达上限，API暂停；仍可离线摘录。'
    if not settings.deepseek_configured:
        return 'API配置不可用；仍可离线摘录。'
    return '不限制每日问答次数；开启AI后每次提交默认使用DeepSeek RAG。'


def select_answer_provider(ai_enabled):
    return (PROVIDER_AUTO, True) if ai_enabled else (PROVIDER_LOCAL, False)


def answer_api_diagnostic(answer):
    # 兼容代码热更新前已留在会话中的结果，不推断其未知调用状态。
    return {
        'outcome': getattr(answer, 'api_outcome', 'not_requested'),
        'reason': getattr(answer, 'api_reason', ''),
        'attempted': getattr(answer, 'api_attempted', False),
        'quota_consumed': getattr(answer, 'api_quota_consumed', False),
        'http_status': getattr(answer, 'api_http_status', None),
        'accounting': getattr(answer, 'api_accounting', None),
        'qa_mode': getattr(answer, 'qa_mode', 'rag'),
        'general_knowledge': getattr(answer, 'general_knowledge', False),
        'model_calls': getattr(answer, 'model_calls', 0),
        'raw_output': getattr(answer, 'model_raw_output', None),
        'verification_status': getattr(answer, 'verification_status', 'verified'),
        'verification_errors': list(getattr(answer, 'verification_errors', ())),
    }


def remember_api_diagnostic(state, answer):
    diagnostic = answer_api_diagnostic(answer)
    if diagnostic['outcome'] == 'not_requested':
        return
    if diagnostic['attempted'] or not state.get('last_api_diagnostic'):
        state['last_api_diagnostic'] = diagnostic


def render_api_diagnostic(diagnostic):
    """只展示结构化、脱敏状态；不展示原始响应或请求数据。"""
    outcome = diagnostic.get('outcome', 'not_requested')
    reason = diagnostic.get('reason', '')
    if outcome == 'accepted' and diagnostic.get('general_knowledge'):
        st.success('DeepSeek 通用知识回答已生成；该部分未经课件核实，不含课件引用。')
    elif outcome == 'accepted':
        st.success('API已返回且引用校验通过；此条答案来源为DeepSeek课件证据。')
    elif outcome == 'unverified':
        st.warning('API已返回可读答案，但未通过严格逐条校验；已保留为未核验 AI 草稿。' + reason)
    elif outcome == 'unparseable':
        st.warning('API已返回，但 JSON 不可解析或没有可用答案；已回退本地原文摘录。' + reason)
    elif outcome == 'citation_rejected':
        st.warning('API已返回，但模型答案未通过引用校验，已回退本地原文摘录。' + reason)
    elif outcome == 'model_refused':
        st.warning('API已返回资料不足，未生成可采用的模型答案。')
    elif outcome != 'not_requested':
        st.error('上次API结果：' + reason)
    raw_output = diagnostic.get('raw_output')
    if raw_output:
        with st.expander('模型原始输出（诊断，截断/脱敏）', expanded=False):
            st.code(raw_output, language=None, wrap_lines=True)
    if diagnostic.get('quota_consumed'):
        st.caption('本次API尝试已计入每日统计；不自动重试。')
        accounting=diagnostic.get('accounting') or {}
        if accounting.get('cost_status')=='estimated':
            st.caption(f"本次估算费用 ¥{accounting['estimated_cny']:.8f}（不是实际账单）")
        else:
            st.warning('本次费用未知；未当作零费用，预算中保留保护预留。')


def render_answer(answer) -> None:
    verification = getattr(answer, 'verification_status', 'verified')
    if answer.status == STATUS_INSUFFICIENT:
        st.warning("资料不足：当前课件证据不足以支撑可靠回答。")
    elif answer.status == STATUS_ERROR:
        st.error("无法生成回答。")
    elif verification == VERIFICATION_UNVERIFIED:
        if answer.general_knowledge:
            st.success("已生成 AI 通用知识答案；该部分未经课件核实。")
        else:
            st.warning("AI 生成草稿，未经逐条事实核验；不得作为已验证课件依据。")
    elif verification == VERIFICATION_FAILED:
        st.warning("API 调用失败、返回不可解析或没有可用答案；已回退本地原文摘录。")
    elif answer.provider == 'deepseek':
        st.success("已采用 DeepSeek 生成，并通过逐条引用校验的课件答案。")
    elif answer.api_attempted:
        st.warning("已回退本地原文摘录；未采用失败或未通过引用校验的模型答案。")
    else:
        st.success("已基于课件证据生成离线原文摘录。")

    st.caption(
        f"回答模式：{answer.qa_mode_label}｜证据来源：{answer.source_label}｜"
        f"验证状态：{answer.verification_label}｜生成方式：{answer.provider_label}"
    )
    if answer.general_knowledge:
        st.warning("AI 通用知识补充，未经课件核实；本部分不提供 [S#] 或 PDF 页码。")
    context=getattr(answer,'evidence_context',())
    if context or any(not h.strict_eligible for h in getattr(answer,'citations',())):
        st.warning('引用来源未人工复核；自动校验通过不等于教师/人工确认，请核对原课件。')
    compact=compact_exam_answer(answer)
    if compact:
        st.subheader('笔试精简答案')
        st.markdown(compact['summary'])
        for i,point in enumerate(compact['points'],1):
            st.markdown(f'{i}. {point}')
        if compact['keywords']:
            st.caption('关键词（从当前答案提取）')
            st.markdown(' · '.join(f'**{term}**' for term in compact['keywords']))
        st.caption('参考课件（PDF物理页码）')
        for ref,filename,page in compact['sources']:
            st.markdown(f'[{ref}] {filename}｜物理第{page}页')
        if compact['omitted']:
            st.caption(f"另有{compact['omitted']}条要点保留在详细分析中；精简版不是完整论述。")
    else:
        st.info('当前结果未通过核验、证据不足或无法无损提取，不生成笔试标准答案。完整结果与风险保留在下方。')
    with st.expander('详细分析（原始完整答案）',expanded=False):
        st.markdown(answer.answer)
    supplements=[value for key,value in answer_sections(answer.answer).items() if key.startswith('AI补充')]
    with st.expander('AI 补充',expanded=False):
        if supplements:
            st.warning('AI补充不作为已核实课件依据。')
            for supplement in supplements:st.markdown(supplement)
        else:st.caption('本次没有单独的AI补充。')
    with st.expander('来源与校验风险（独立于答题正文）', expanded=True):
        if verification == VERIFICATION_UNVERIFIED:
            st.warning('AI草稿未经核验；真实来源映射只说明资料存在，不证明每个论点得到支持。')
        for issue in getattr(answer, 'verification_errors', ()):
            st.warning(issue)
        for source in getattr(answer, 'evidence_context', ()):
            quality=source.get('quality','')
            st.caption(f"[{source['id']}] {source['filename']}｜物理第{source['page_number']}页｜来源未人工复核；{quality}")
    render_api_diagnostic(answer_api_diagnostic(answer))
    with st.expander('本次检索证据', expanded=False):
        context=getattr(answer,'evidence_context',())
        if not context:
            st.info('本次没有向课件问答模型传入证据；离线或通用回答不冒充课件RAG。')
        for evidence in context:
            st.markdown(f"**[{evidence['id']}] {evidence['filename']}｜物理第{evidence['page_number']}页**")
            st.caption(evidence['quality'])
            st.text(evidence['text'])
        if context:
            st.caption('以上是实际提供给模型的证据，不等于模型每条论述都已验证。请结合验证状态核对。')
    with st.expander("复制答案", expanded=False):
        st.caption("点击文本框右上角复制图标，复制答案及原文引用；也可下载UTF-8文本。")
        st.code(answer.answer, language=None, wrap_lines=True)
        st.download_button("下载答案文本", answer.answer, file_name="工程伦理回答.txt", mime="text/plain", on_click="ignore")
    if answer.usage:
        st.caption(f"本次 API token 用量：{answer.usage}；即使回退离线摘录，已发出的请求仍可能计费。")
    for warning in answer.warnings:
        st.warning(warning)

    with st.expander('课件来源与完整证据',expanded=False):
        if answer.status == STATUS_INSUFFICIENT:
            render_evidence(answer.search.hits[:3], "相关线索（不足以作答，仅供定位）")
        elif answer.status == STATUS_ERROR:
            st.info("本次没有生成可用答案；系统未用通用知识或伪造引用替代失败结果。")
        elif verification == VERIFICATION_UNVERIFIED and not answer.general_knowledge:
            st.info("以下为检索到的课件证据，仅用于人工复核，不是 AI 草稿的已验证引用：")
            render_evidence(answer.search.hits[:8], "检索到的课件证据（未作为已验证依据）")
        elif answer.general_knowledge:
            st.info("本答案来自 DeepSeek 通用知识，不使用课件证据，因此没有 PDF 页码或 [S#] 引用。")
        else:
            render_evidence(answer.citations, "原文证据与 PDF 页码")
            cited={(hit.page.filename,hit.page.page_number) for hit in answer.citations}
            related=[hit for hit in answer.search.hits if (hit.page.filename,hit.page.page_number) not in cited]
            if related:
                with st.expander("其他检索线索（未作为答案引用）"):
                    render_evidence(related,"未引用的相关页面")
    
    with st.expander("检索诊断", expanded=False):
        st.write(answer.search.diagnostics)
        st.write(
            {
                "检索词": list(answer.search.terms),
                "候选池大小": answer.search.pool_size,
                "严格池大小": answer.search.strict_pool_size,
                "扩展池大小": answer.search.expanded_pool_size,
                "低相关过滤": answer.search.dropped_low_relevance,
                "重复正文合并": answer.search.duplicates_merged,
                "证据警告": answer.search.evidence_warning or "无",
                "状态": answer.status,
                "回答模式": answer.qa_mode_label,
                "证据来源": answer.source_label,
                "通用知识": answer.general_knowledge,
                "验证状态": answer.verification_label,
                "校验失败原因": list(answer.verification_errors),
                "模型调用次数": answer.model_calls,
            }
        )
        for hit in answer.search.hits:
            st.write(
                f"S{hit.rank}｜{hit.citation}｜{hit.score_type}排序分 {hit.score:.5f}｜"
                f"覆盖率 {hit.coverage:.0%}｜{hit.review_label}"
            )


def main() -> None:
    st.set_page_config(
        page_title="工程伦理 RAG 复习助手",
        page_icon="📚",
        layout="wide",
    )
    st.markdown(MOBILE_CSS, unsafe_allow_html=True)
    st.title("📚 工程伦理 RAG 复习助手")
    st.caption(
        "本地课件检索 · 严格/扩展双范围 · 回答附 PDF 文件名与物理页码 · "
        "未审核内容会明确标注"
    )

    try:
        settings, corpus, retriever = load_runtime()
    except CorpusError as exc:
        st.error(f"知识库加载失败：{exc}")
        st.stop()

    stats = corpus.stats()

    with st.sidebar:
        st.header("知识库")
        st.markdown(
            f"- 文档：**{stats['documents']}** 份\n"
            f"- 总页数：**{stats['total_pages']}** 页\n"
            f"- 有文本：**{stats['text_pages']}** 页\n"
            f"- 严格合格：**{stats['strict_pages']}** 页\n"
            f"- 未审核：**{stats['unreviewed_pages']}** 页"
        )
        st.caption(
            "严格合格 = A 类 + 已修复 B 类；"
            "“已审核”为助手视觉/结构核对，不等于人工签核。"
        )

        st.divider()
        st.header("回答模式")
        qa_mode = st.radio(
            "回答模式",
            options=(QA_MODE_HYBRID, QA_MODE_RAG, QA_MODE_GENERAL),
            format_func=lambda value: QA_MODE_LABELS.get(value, value),
            index=0,
            captions=(
                "默认：严格课件 → 扩展课件 → DeepSeek 通用知识；来源分开标注。",
                "只用 A 类与已修复 B 类严格合格页；证据不足返回资料不足。",
                "直接调用 DeepSeek 通用知识，不使用课件证据。",
            ),
            label_visibility="collapsed",
        )
        top_k = st.slider("证据页数", min_value=3, max_value=10, value=6, step=1)

        st.divider()
        st.header("回答方式")
        # 仅保存非敏感的会话配置；不改写本地配置文件。
        budget=st.number_input('每日费用预算（人民币元）',min_value=0.0,max_value=10000.0,
                               value=float(settings.daily_budget_cny),step=.5,key='daily_budget_cny')
        prices=settings.prices
        with st.expander('估算价格（元/百万token，可配置）'):
            st.caption(f'当前模型：{settings.deepseek_model}。默认采用2026-11-08官方人民币高峰价快照；不自动应用折扣，实际以账单为准。')
            input_price=st.number_input('输入未命中价格',min_value=.000001,value=float(prices.input),format='%.6f',key='price_input_'+settings.deepseek_model)
            output_price=st.number_input('输出价格',min_value=.000001,value=float(prices.output),format='%.6f',key='price_output_'+settings.deepseek_model)
            hit_price=st.number_input('输入缓存命中价格',min_value=0.0,max_value=float(input_price),value=min(float(prices.cache_hit),float(input_price)),format='%.6f',key='price_hit_'+settings.deepseek_model)
            st.caption('更改价格只影响之后的请求；已记录费用保留请求时单价。预留不是已消费费用。')
        settings=replace(settings,daily_budget_cny=budget,price_input_cny_per_m=input_price,
                         price_output_cny_per_m=output_price,price_cache_hit_cny_per_m=hit_price)
        try:
            stats_api=RequestLimiter(settings.api_state_path).stats(settings)
            ledger_ok=True
            st.caption(f"UTC日调用尝试：{stats_api['attempts']} 次（无次数上限）")
            st.caption(f"已返回token统计：输入 {stats_api['prompt_tokens']} / 输出 {stats_api['completion_tokens']} / 总计 {stats_api['total_tokens']}")
            st.caption(f"已知用量估算 ¥{stats_api['known_estimate_cny']:.8f} / 预算 ¥{budget:.2f}（不是实际账单）")
            st.caption(f"保护预留 ¥{stats_api['protected_cny']:.8f}（在途/未知费用，不是已消费金额）")
            if stats_api['unknown_calls'] or stats_api['pending_calls']:
                st.warning(f"{stats_api['unknown_calls']}次费用未知，{stats_api['pending_calls']}次在途/未结算；token统计可能不完整。历史缺失用量不补零冒充已知。")
        except LimitError as exc:
            st.error(str(exc));ledger_ok=False;stats_api={}
        st.info(next_submission_status(settings,stats_api,ledger_ok=ledger_ok))
        if stats_api.get('budget_blocked'):
            reset=(datetime.now(timezone.utc)+timedelta(days=1)).date()
            st.caption(f'下一统计日：{reset} 00:00 UTC；本地摘录仍可继续。')
        previous=st.session_state.get('last_api_diagnostic')
        if previous:
            with st.expander('上一次API结果',expanded=True):render_api_diagnostic(previous)
        st.warning('费用为token×配置价格的本地估算，不是账单或账户级硬限额；请求失败用量未知时保留预留。')
        st.link_button('核对官方价格','https://api-docs.deepseek.com/zh-cn/quick_start/pricing/')
        # 配置总开关是硬门禁；网页 toggle 只能在其开启时作为本会话许可。
        master_enabled=bool(settings.api_enabled)
        api_available=bool(master_enabled and settings.deepseek_configured and ledger_ok
                           and not stats_api.get('budget_blocked'))
        ai_enabled=st.toggle('AI：DeepSeek RAG（关闭为离线摘录）',value=False,
                             disabled=not api_available,key='ai_enabled')
        if not master_enabled:
            st.caption('配置总开关未开启；仅使用离线摘录。')
        elif not settings.deepseek_configured:
            st.caption('未配置API密钥；仅使用离线摘录。')
        elif stats_api.get('budget_blocked'):
            st.caption('本日预算已暂停API；仍可使用离线摘录。')
        elif ai_enabled:
            st.caption('AI已开启：提交问题会调用DeepSeek；会发送问题与证据文字，不上传PDF。不自动重试。')
        else:
            st.caption('AI已关闭：仅使用离线原文摘录。')
        # 网页开关只在本会话有效；总开关/预算/密钥任一不满足都不能调用。
        effective_ai=bool(api_available and ai_enabled)
        settings=replace(settings,api_enabled=effective_ai)
        provider,allow_api=select_answer_provider(effective_ai)
        if qa_mode == QA_MODE_GENERAL and not effective_ai:
            st.warning('DeepSeek 通用问答需要开启 API 总开关并打开 AI；当前不能调用，也不会用本地知识伪造答案。')
        elif qa_mode == QA_MODE_HYBRID and not effective_ai:
            st.caption('AI未开启：混合模式只使用课件；课件不足时返回资料不足，不生成通用知识。')

        st.divider()
        if st.button("清空当前结果", width="stretch"):
            st.session_state.pop("last_answer", None)
            st.rerun()

        with st.expander("审核类别统计"):
            rows = [
                {
                    "类别": REVIEW_CATEGORY_LABELS.get(category, UNREVIEWED_LABEL),
                    "页数": count,
                }
                for category, count in stats["review_categories"].items()
            ]
            st.dataframe(rows, hide_index=True, width="stretch")

        st.caption("原始 PDF 与 processed_v3 JSON 只读，不会被界面修改。")

    st.caption('在下方输入题目并提交；回答模式、AI开关与预算设置在侧栏。')
    st.subheader('输入考试题目')
    engine = AnswerEngine(retriever, settings=settings)
    with st.form("question_form", clear_on_submit=False):
        question = st.text_area(
            "输入你的问题",
            height=120,
            placeholder="例如：工程风险的技术因素有哪些？",
            key="question_input",
        )
        submitted = st.form_submit_button(
            "检索并回答",
            type="primary",
            width="stretch",
        )

    if submitted:
        if not question.strip():
            st.warning("请输入问题。")
        else:
            with st.spinner("正在检索课件并整理证据…"):
                answer = engine.answer(
                    question,
                    mode=MODE_STRICT,
                    top_k=top_k,
                    provider=provider,
                    allow_api=allow_api,
                    qa_mode=qa_mode,
                )
            st.session_state["last_answer"] = answer
            remember_api_diagnostic(st.session_state, answer)
            # AI开关跨问题保持；只有提交表单才请求，刷新/复制/下载不请求。
            st.rerun()

    last_answer = st.session_state.get("last_answer")
    if last_answer is not None:
        st.divider()
        render_answer(last_answer)
    else:
        st.info("输入问题后点击“检索并回答”。课件答案保留来源文件名和物理页码。")
    with st.expander('示例问题', expanded=False):
        st.markdown('\n'.join(f'- {question}' for question in EXAMPLES))


if __name__ == "__main__":
    main()
