"""Streamlit 网页界面：提问、答案、原文证据与 PDF 页码。"""

from __future__ import annotations

import sys
import re
import hashlib
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
    QA_MODE_HYBRID,
    QA_MODE_LOCAL,
    VERIFICATION_FAILED,
    VERIFICATION_UNVERIFIED,
    AnswerEngine,
    STATUS_ERROR,
    STATUS_INSUFFICIENT,
)
from src.retriever import MODE_STRICT, Retriever
from src.text_utils import query_terms
from src.versioned_corpus import (RELEASE, load_versions, load_version_indexes,
                                  combined_corpus, VersionedRetriever, source_pdf)
from src.exam_materials import LocalMaterialsRetriever
from src.choice_solver import ChoiceSolution, solve_choice_raw_text
from src.case_solver import (
    CaseSolution,
    case_answer_markdown,
    parse_case_questions,
    questions_from_editable_lines,
    solve_case,
)
from src.ocr import recognize_image


EXAMPLES = [
    "工程风险的技术因素有哪些？",
    "工程师在利益冲突中应如何应对？",
    "公众安全、健康和福利为什么应优先？",
    "环境工程中的安全与社会公正有什么关系？",
    "责任伦理与法律责任有什么区别？",
    "工程伦理中的功利主义与义务论有什么区别？",
]


@st.cache_resource(show_spinner=False)
def load_runtime(release=RELEASE):
    settings = Settings.from_env()
    old, new = load_versions()
    indexes = load_version_indexes(old, new)
    base = VersionedRetriever(old, new, indexes=indexes)
    try:
        retriever = LocalMaterialsRetriever.load(base)
    except Exception:
        # 教材/题库不可用时仍保留双版本 PPT 检索，不阻断页面。
        retriever = base
    return settings, combined_corpus(old, new), retriever


def reset_release_session(state, release=RELEASE):
    """只清理答案/诊断，不触碰额度、AI开关、远程配置或凭据。"""
    if state.get('corpus_release') != release:
        for key in ('last_answer', 'last_api_diagnostic'):
            state.pop(key, None)
        state['corpus_release'] = release
        return True
    return False



MOBILE_CSS = """<style>
@media (max-width: 768px) {
  [data-testid="stMainBlockContainer"] { padding: 1rem .85rem 2rem; }
  [data-testid="stMain"] h1 { font-size: 1.5rem; }
  [data-testid="stMain"] h2 { font-size: 1.25rem; }
  [data-testid="stMain"] textarea, [data-testid="stMain"] input { font-size: 16px !important; }
  [data-testid="stMain"] button { min-height: 44px; white-space: normal; }
  [data-testid="stMain"] [data-testid="stVerticalBlock"] { min-width: 0; }
  [data-testid="stFileUploader"], [data-testid="stFileUploaderDropzone"] { width: 100% !important; }
  [data-testid="stMain"] [data-testid="stForm"] button { width: 100% !important; }
}
[data-testid="stFileUploader"] { max-width: 100%; }
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
    layers = getattr(answer, 'verification_layers', None) or {}
    pending = (getattr(answer, 'source_review_pending', False)
               and getattr(answer, 'verification_status', '') == 'unverified'
               and not getattr(answer, 'verification_errors', ())
               and layers.get('reference_integrity', {}).get('ok') is True
               and layers.get('claim_support', {}).get('ok') is True)
    if (answer.status!='ok' or (getattr(answer,'verification_status','unverified')!='verified' and not pending)
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
            pdf=source_pdf(hit.page)
            if pdf.is_file():
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
        'source_review_pending': getattr(answer, 'source_review_pending', False),
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
    elif outcome == 'unverified' and diagnostic.get('source_review_pending'):
        st.warning('API已返回；引用与事实校验通过，但新版来源待审核，保留为UNVERIFIED草稿。')
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
        if getattr(answer, 'source_review_pending', False):
            st.warning('新版来源待审核，答案不是 VERIFIED；请核对课件。引用与事实校验不替代来源审核。')
        elif answer.general_knowledge:
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
    context=getattr(answer,'evidence_context',())
    compact=compact_exam_answer(answer)
    if compact:
        st.subheader('笔试精简草稿（新版来源待审核）' if getattr(answer, 'source_review_pending', False) else '笔试精简答案')
        st.markdown(compact['summary'])
        for i,point in enumerate(compact['points'],1):
            st.markdown(f'{i}. {point}')
        if compact['keywords']:
            st.caption('关键词（从当前答案提取）')
            st.markdown(' · '.join(f'**{term}**' for term in compact['keywords']))
        st.caption('参考课件（PDF物理页码）')
        for ref,filename,page in compact['sources']:
            version = next((e.get('version_label', '') for e in context if e['id'] == ref), '')
            st.markdown(f'[{ref}] {version + "｜" if version else ""}{filename}｜物理第{page}页')
        if compact['omitted']:
            st.caption(f"另有{compact['omitted']}条要点保留在详细分析中；精简版不是完整论述。")
    else:
        st.info('当前结果未通过核验、证据不足或无法无损提取，不生成笔试标准答案。完整结果与风险保留在下方。')
    if answer.general_knowledge:
        st.warning("AI 通用知识补充，未经课件核实；本部分不提供 [S#] 或 PDF 页码。")
    if answer.search.diagnostics.get('version_note'):
        st.info(answer.search.diagnostics['version_note'])
    for issue in answer.search.diagnostics.get('conflicts', ()):
        st.warning(issue)
    if context or any(not h.strict_eligible for h in getattr(answer,'citations',())):
        st.warning('引用来源未人工复核；自动校验通过不等于教师/人工确认，请核对原课件。')
    with st.expander('详细分析（原始完整答案）',expanded=False):
        st.markdown(answer.answer)
    supplements=[value for key,value in answer_sections(answer.answer).items() if key.startswith('AI补充')]
    with st.expander('AI 补充',expanded=False):
        if supplements:
            st.warning('AI补充不作为已核实课件依据。')
            for supplement in supplements:st.markdown(supplement)
        else:st.caption('本次没有单独的AI补充。')
    with st.expander('来源与校验风险（独立于答题正文）', expanded=True):
        if verification == VERIFICATION_UNVERIFIED and getattr(answer, 'source_review_pending', False):
            st.warning('引用与事实校验通过；新版来源待审核，不能作为已审核课件结论。')
        elif verification == VERIFICATION_UNVERIFIED:
            st.warning('AI草稿未经核验；真实来源映射只说明资料存在，不证明每个论点得到支持。')
        for issue in getattr(answer, 'verification_errors', ()):
            st.warning(issue)
        for source in getattr(answer, 'evidence_context', ()):
            quality=source.get('quality','')
            st.caption(f"[{source['id']}] {source.get('version_label','')}｜{source['filename']}｜物理第{source['page_number']}页｜来源未人工复核；{quality}")
    render_api_diagnostic(answer_api_diagnostic(answer))
    with st.expander('本次检索证据', expanded=False):
        context=getattr(answer,'evidence_context',())
        if not context:
            st.info('本次没有向课件问答模型传入证据；离线或通用回答不冒充课件RAG。')
        for evidence in context:
            st.markdown(f"**[{evidence['id']}] {evidence.get('version_label','')}｜{evidence['filename']}｜物理第{evidence['page_number']}页**")
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
            if answer.search.hits:
                st.info("本答案包含 AI 通用补充；以下仅为本地检索到的部分材料，未作为完整依据。")
                render_evidence(answer.search.hits[:5], "本地部分材料（未作为已验证依据）")
            else:
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


def render_choice_solution(solution: ChoiceSolution) -> None:
    st.subheader("💡 选择题解答结果")
    qtype = getattr(solution, 'question_type', '自动')
    st.caption(f"题型：{qtype}")
    if getattr(solution, 'uncertainty_reason', ''):
        st.warning("题型不确定：" + solution.uncertainty_reason)
    if solution.verified:
        st.success(f"已匹配学习通题库已核实标准答案（{solution.source_detail}）")
    elif "待核实" in solution.source:
        st.warning("⚠️ 题库中该题答案标记为待核实，未采用学生作答；此处答案由课件证据与 DeepSeek 综合推断。")
    elif solution.answer:
        st.info(f"AI 推断答案：{solution.source_detail}")
    else:
        st.warning("未生成确定答案。请参考解析与课件线索。")

    with st.container(border=True):
        if getattr(solution, 'question_type', '') == "不确定" and solution.answer:
            st.markdown(f"### 建议答案：:orange[{solution.answer}]")
        elif solution.answer:
            st.markdown(f"### 答案：:green[{solution.answer}]")
        else:
            st.markdown("### 建议答案：:orange[待推断]")
        badge_icon = "🟢" if solution.verified else ("⚠️" if getattr(solution, 'question_type', '') == "不确定" else ("🟡" if "待核实" in solution.source else "🤖"))
        st.markdown(f"**来源**：{badge_icon} {solution.source}")
        st.caption(solution.source_detail)

        st.divider()
        st.markdown("**【解析与依据】**")
        st.markdown(solution.analysis)

        if getattr(solution, 'option_analysis', None):
            with st.expander("逐项判断", expanded=False):
                for letter, reason in sorted(solution.option_analysis.items()):
                    st.markdown(f"- **{letter}**：{reason}")

        if solution.warning:
            st.caption(f"提示：{solution.warning}")
        if getattr(solution, 'diagnostic', None):
            with st.expander("选择题 AI 诊断（脱敏）", expanded=False):
                diag = solution.diagnostic
                st.write({
                    "错误类型": diag.get("error_type") or "无",
                    "模型": diag.get("model") or "未知",
                })
                if diag.get("raw_preview"):
                    st.caption("模型原始响应预览（截断/脱敏）")
                    st.code(diag["raw_preview"], language=None, wrap_lines=True)

    if solution.evidence_context:
        with st.expander("📚 参考课件与题库来源证据", expanded=False):
            for e in solution.evidence_context:
                st.markdown(f"**[{e['id']}] {e.get('version_label', '')}｜{e['filename']}｜物理第{e['page_number']}页**")
                if e.get('quality'):
                    st.caption(f"页面状态：{e['quality']}")
                st.text(e['text'])


def _clear_case_state() -> None:
    """只清空案例分析输入/上传/OCR/答案，不影响其他模块。"""
    for key in ("case_text", "case_questions_text"):
        if key in st.session_state:
            st.session_state[key] = ""
    st.session_state.pop("last_case_solution", None)
    st.session_state.pop("case_uploaded_hashes", None)
    st.session_state.pop("case_ocr_cache", None)
    st.session_state["case_questions_dirty"] = False
    st.session_state["case_uploader_epoch"] = st.session_state.get("case_uploader_epoch", 0) + 1


def _mark_case_questions_dirty() -> None:
    st.session_state["case_questions_dirty"] = True
    st.session_state.pop("last_case_solution", None)


def _refresh_case_questions() -> None:
    parsed = parse_case_questions(st.session_state.get("case_text", ""))
    st.session_state["case_questions_text"] = "\n".join(q.text for q in parsed.questions)
    st.session_state["case_questions_dirty"] = False
    st.session_state.pop("last_case_solution", None)


def process_case_uploads(uploaded_files, state, *, recognize=None):
    """按上传顺序 OCR 多张案例截图；失败不覆盖其他已识别内容。"""
    if not uploaded_files:
        return 0, []
    hashes = list(state.get("case_uploaded_hashes", []))
    texts: list[str] = []
    errors: list[str] = []
    recognizer = recognize or recognize_image
    for index, uploaded in enumerate(uploaded_files, 1):
        name = str(getattr(uploaded, "name", "") or f"截图{index}")
        suffix = Path(name).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg"}:
            errors.append(f"{name}：格式不支持")
            continue
        try:
            raw = uploaded.getvalue()
        except Exception:
            errors.append(f"{name}：无法读取")
            continue
        if not raw:
            errors.append(f"{name}：图片为空")
            continue
        signature = hashlib.sha256(raw).hexdigest()
        if signature in hashes:
            continue
        hashes.append(signature)
        try:
            result = recognizer(raw)
        except Exception as exc:
            errors.append(f"{name}：OCR 异常（{type(exc).__name__}）")
            continue
        if getattr(result, "status", "error") == "ok" and str(getattr(result, "text", "")).strip():
            texts.append(str(result.text).strip())
        else:
            errors.append(f"{name}：{getattr(result, 'error', '未识别到文字')}")
    state["case_uploaded_hashes"] = hashes
    if texts:
        existing = str(state.get("case_text", "")).strip()
        merged = "\n\n".join(([existing] if existing else []) + texts)
        state["case_text"] = merged
        state.pop("last_case_solution", None)
    return len(texts), errors


def _clear_qa_state() -> None:
    """清空简答题输入/上传/OCR/上次答案；不改变回答模式或额度。"""
    if "question_input" in st.session_state:
        st.session_state["question_input"] = ""
    st.session_state.pop("last_answer", None)
    st.session_state.pop("last_api_diagnostic", None)
    st.session_state.pop("qa_uploaded_sig", None)
    st.session_state.pop("qa_ocr_notice", None)
    # 新的 uploader key 允许清空后重新上传同一张图片并再次识别。
    st.session_state["qa_uploader_epoch"] = st.session_state.get("qa_uploader_epoch", 0) + 1


def process_qa_upload(uploaded_file, state, *, recognize=None):
    """处理简答题截图：只做 OCR 回填，不提交、不调用 DeepSeek。

    返回 (status, message)；status 为 success / error / duplicate / none。
    """
    if uploaded_file is None:
        state.pop("qa_uploaded_sig", None)
        return "none", ""
    name = str(getattr(uploaded_file, "name", "") or "")
    suffix = Path(name).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg"}:
        return "error", "图片格式不支持，请上传 PNG、JPG 或 JPEG。"
    try:
        raw = uploaded_file.getvalue()
    except Exception:
        return "error", "无法读取图片内容，请重新上传或手动输入。"
    if not raw:
        return "error", "图片为空，请重新上传或手动输入。"
    signature = hashlib.sha256(raw).hexdigest()
    if state.get("qa_uploaded_sig") == signature:
        return "duplicate", ""
    state["qa_uploaded_sig"] = signature
    recognizer = recognize or recognize_image
    try:
        result = recognizer(raw)
    except Exception as exc:
        return "error", f"截图识别失败：{exc}。可手动输入题目。"
    if getattr(result, "status", "error") == "ok" and str(getattr(result, "text", "")).strip():
        state["question_input"] = result.text.strip()
        state.pop("last_answer", None)
        state.pop("last_api_diagnostic", None)
        return "success", "题目截图识别完成，文字已填入下方输入框；请核对后点击“检索并回答”。"
    return "error", f"截图识别失败：{getattr(result, 'error', '未识别到有效文字')}。可手动输入题目。"


def render_case_solution(solution: CaseSolution) -> None:
    if solution.status == "ok":
        st.success(f"已按 {len(solution.questions)} 个设问生成案例答案。")
        st.caption("以下为 AI 生成的分析作答，未经人工逐条核验；PPT 引用仅说明来源，请核对原文。")
    elif solution.status == "incomplete":
        st.warning("案例答案不完整：请查看下方完整性检查，不要直接当作完整答案。")
    else:
        st.error("案例分析未能生成可用答案；案例和检索证据已保留。")
    if getattr(solution, "excluded_evidence", ()):
        with st.expander("证据准入诊断（未进入模型上下文）", expanded=False):
            for item in solution.excluded_evidence:
                st.caption(
                    f"设问{item.get('question', '?')}｜{item.get('filename', '')}｜"
                    f"第{item.get('page', '?')}页｜{item.get('reason', '')}"
                )
    if solution.errors or solution.warnings:
        with st.expander("完整性与生成风险", expanded=True):
            for error in solution.errors:
                st.warning(error)
            for warning in solution.warnings:
                st.warning(warning)
    if solution.answers:
        st.subheader("案例分析考试作答")
        by_index = {a.index: a for a in solution.answers}
        by_ref = solution.evidence_by_ref()
        for question in solution.questions:
            answer = by_index.get(question.number)
            st.markdown(f"### 设问{question.number}：{question.text}")
            if answer is None:
                st.warning("本地完整性检查：该设问没有对应答案，请勿直接使用。")
                continue
            if getattr(answer, "points", ()):
                for point_index, point in enumerate(answer.points, 1):
                    st.markdown(f"**（{point_index}）{point.title}。** {point.analysis}")
                    if point.evidence_ids:
                        st.caption("要点引用：" + "、".join(f"[S{ref}]" for ref in point.evidence_ids))
                    else:
                        st.caption("模型通用知识补充（无直接课件引用）")
            else:
                st.markdown(answer.answer)
            if answer.citations:
                st.caption("引用：" + "、".join(f"[S{ref}]" for ref in answer.citations))
            elif answer.insufficient:
                st.caption("模型标记：证据不足/需补充。")
            if getattr(answer, "fact_flags", ()):
                for flag in answer.fact_flags:
                    st.warning(flag)
        with st.expander("参考课件与证据", expanded=False):
            if not solution.evidence:
                st.info("没有检索到本地课件证据；答案中的通用知识部分不能当作课件依据。")
            for item in solution.evidence:
                kind_label = {"theory": "理论依据", "similar_case": "类似案例（仅类比）",
                              "background": "背景补充"}.get(item.kind, item.kind)
                st.markdown(f"**[S{item.ref}] {item.hit.citation}｜{item.hit.review_label}｜{kind_label}**")
                st.caption(f"关联设问：{'、'.join(map(str, item.questions))}")
                if len(getattr(item, "sources", ())) > 1:
                    st.caption("合并来源：" + "；".join(
                        f"{h.page.filename} 第{h.page.page_number}页" for h in item.sources[1:]
                    ))
                if getattr(item, "score_breakdown", None):
                    st.caption("可解释评分：" + "｜".join(
                        f"{k}={v}" for k, v in item.score_breakdown.items()
                    ))
                st.text(item.text)
        with st.expander("案例、设问与模型诊断", expanded=False):
            st.caption("案例原文")
            st.text(solution.case_text)
            st.caption("设问顺序")
            for question in solution.questions:
                st.write(f"{question.number}. {question.text}")
            for answer in solution.answers:
                st.caption(f"设问{answer.index} 的事实边界")
                if answer.known_facts_used:
                    st.write("已知事实：" + "；".join(answer.known_facts_used))
                if answer.inferences:
                    st.write("合理推断：" + "；".join(answer.inferences))
                if answer.unknowns:
                    st.write("需进一步核实：" + "；".join(answer.unknowns))
                if answer.fact_flags:
                    st.warning("；".join(answer.fact_flags))
            if solution.raw_model_output:
                st.caption("模型原始输出（截断）")
                st.code(solution.raw_model_output, language=None, wrap_lines=True)
            if solution.usage:
                st.caption(f"API token 用量：{solution.usage}")
            if getattr(solution, "api_http_status", None):
                st.caption(f"HTTP 状态：{solution.api_http_status}")
            if getattr(solution, "api_outcome", ""):
                st.caption(f"API 结果类型：{solution.api_outcome}")
        full = case_answer_markdown(solution)
        with st.expander("复制完整案例分析答案", expanded=False):
            st.code(full, language=None, wrap_lines=True)
            st.download_button("下载案例分析答案", full, file_name="工程伦理案例分析.txt",
                               mime="text/plain", on_click="ignore")
    else:
        if solution.evidence:
            with st.expander("本次检索证据（未生成答案）", expanded=True):
                for item in solution.evidence:
                    kind_label = {"theory": "理论依据", "similar_case": "类似案例（仅类比）",
                                  "background": "背景补充"}.get(item.kind, item.kind)
                    st.markdown(f"**[S{item.ref}] {item.hit.citation}｜{item.hit.review_label}｜{kind_label}**")
                    if len(getattr(item, "sources", ())) > 1:
                        st.caption("合并来源：" + "；".join(
                            f"{h.page.filename} 第{h.page.page_number}页" for h in item.sources[1:]
                        ))
                    st.text(item.text)
        if solution.raw_model_output:
            with st.expander("模型原始输出（诊断，截断）", expanded=False):
                st.code(solution.raw_model_output, language=None, wrap_lines=True)
        if solution.api_outcome:
            st.caption(f"API 结果类型：{solution.api_outcome}")
        if solution.usage:
            st.caption(f"API token 用量：{solution.usage}")
        if getattr(solution, "api_http_status", None):
            st.caption(f"HTTP 状态：{solution.api_http_status}")


def render_case_tab(retriever, settings, allow_api: bool) -> None:
    st.caption("上传多张案例截图或粘贴文字；先确认设问，再一次提交生成全部答案。OCR 不自动提交。")
    for key, default in (("case_uploader_epoch", 0), ("case_uploaded_hashes", []),
                         ("case_questions_dirty", False), ("case_questions_text", ""), ("case_text", "")):
        st.session_state.setdefault(key, default)
    epoch = st.session_state.get("case_uploader_epoch", 0)
    files = st.file_uploader(
        "上传案例截图（可多张，按顺序）",
        type=["png", "jpg", "jpeg"],
        accept_multiple_files=True,
        key=f"case_file_uploader_{epoch}",
        help="按截图顺序 OCR，只填入案例文本，不会自动提交或调用 DeepSeek。",
    )
    new_count, ocr_errors = (0, [])
    if files:
        with st.spinner("正在按顺序识别案例截图…"):
            new_count, ocr_errors = process_case_uploads(files, st.session_state)
    if new_count:
        st.success(f"已识别并合并 {new_count} 张截图；请核对文字和设问。")
    for error in ocr_errors:
        st.warning(f"截图识别提示：{error}；已保留其他已识别内容。")

    case_text = st.text_area(
        "案例文字（可修改、补充；支持多张截图合并）",
        height=240,
        key="case_text",
        placeholder="粘贴案例背景、事件经过和设问；也可上传多张截图后核对。",
    )
    parsed = parse_case_questions(case_text) if case_text.strip() else None
    # 新截图/首次进入时只更新未被用户编辑的设问；手动编辑后不静默覆盖。
    if (not st.session_state.get("case_questions_text", "").strip()
            and not st.session_state.get("case_questions_dirty", False)
            and parsed and parsed.questions):
        st.session_state["case_questions_text"] = "\n".join(q.text for q in parsed.questions)
        st.session_state["case_questions_dirty"] = False
    elif new_count and not st.session_state.get("case_questions_dirty", False) and parsed and parsed.questions:
        st.session_state["case_questions_text"] = "\n".join(q.text for q in parsed.questions)
        st.session_state["case_questions_dirty"] = False
    questions_text = st.text_area(
        "识别到的设问（每行一个；可修改、增加、删除、拆分或合并）",
        height=150,
        key="case_questions_text",
        on_change=_mark_case_questions_dirty,
    )
    questions = questions_from_editable_lines(questions_text)
    st.caption(f"当前设问数量：{len(questions)}")
    if parsed and parsed.warnings:
        for warning in parsed.warnings:
            st.warning(warning)
    if parsed and parsed.uncertain:
        st.warning("自动识别可能不完整，请确认每个设问后提交。")
    if new_count and st.session_state.get("case_questions_dirty", False):
        st.info("已有手动编辑的设问，新增截图未覆盖设问；如需要可点击下方“重新识别设问”。")
    st.button("重新识别设问", type="secondary", use_container_width=True,
              key="btn_reparse_case", on_click=_refresh_case_questions)
    submitted = st.button("提交案例分析", type="primary", use_container_width=True,
                          key="btn_solve_case")
    st.button("清空案例", type="secondary", use_container_width=True,
              key="btn_clear_case", on_click=_clear_case_state)
    if submitted:
        if not case_text.strip():
            st.warning("请先输入案例或上传截图。")
        elif not questions:
            st.warning("未识别到设问，请在上方每行填写一个设问后再提交。")
        else:
            with st.spinner("正在逐问检索 PPT，并生成全部设问答案…"):
                solution = solve_case(
                    case_text, questions,
                    retriever=retriever, settings=settings, allow_api=allow_api,
                )
            st.session_state["last_case_solution"] = solution
            st.rerun()
    last_solution = st.session_state.get("last_case_solution")
    if last_solution is not None:
        st.divider()
        render_case_solution(last_solution)


def _clear_choice_state() -> None:
    """「清空」按钮的 on_click 回调：在组件实例化之前清理所有相关状态。"""
    st.session_state["choice_unified_text_area"] = ""
    st.session_state.pop("last_choice_solution", None)
    st.session_state.pop("last_uploaded_file_sig", None)
    # 递增 epoch，使 file_uploader key 变化，Streamlit 将其视为全新组件
    st.session_state["choice_uploader_epoch"] = (
        st.session_state.get("choice_uploader_epoch", 0) + 1
    )


def render_choice_tab(retriever, settings, allow_api: bool) -> None:
    st.caption("上传题目截图或直接输入题目文字；优先匹配题库已核实答案，未命中时检索课件并调用 DeepSeek 推断。")

    # 确保各 session_state 键存在（首次进入或清空后）
    if "choice_unified_text_area" not in st.session_state:
        st.session_state["choice_unified_text_area"] = ""
    if "choice_uploader_epoch" not in st.session_state:
        st.session_state["choice_uploader_epoch"] = 0

    # 1. 上传入口：用 epoch 作为 key 后缀，清空时 epoch 递增即可重置组件
    epoch = st.session_state["choice_uploader_epoch"]
    up_file = st.file_uploader(
        "📁 上传题目截图",
        type=["png", "jpg", "jpeg"],
        key=f"choice_file_uploader_{epoch}",
    )

    # 处理图片上传与自动 OCR 回填
    if up_file is not None:
        file_bytes = up_file.getvalue()
        file_sig = hashlib.sha256(file_bytes).hexdigest()
        if st.session_state.get("last_uploaded_file_sig") != file_sig:
            st.session_state["last_uploaded_file_sig"] = file_sig
            with st.spinner("正在使用本地 Vision OCR 识别截图文字…"):
                ocr_res = recognize_image(file_bytes)
                if ocr_res.status == "ok" and ocr_res.text.strip():
                    st.session_state["choice_unified_text_area"] = ocr_res.text
                    st.success("✅ 题目识别完成，文字已自动填入下方文本框。请核对并按需修改。")
                else:
                    st.warning(f"⚠️ 图片文字识别提示：{ocr_res.error or '未识别到有效文字'}。请在下方直接输入。")
    else:
        st.session_state.pop("last_uploaded_file_sig", None)

    # 2. 题型：默认自动判断；明确题型由用户/题干优先。
    question_type = st.selectbox(
        "题型",
        options=("自动判断", "单选", "多选"),
        index=0,
        key="choice_question_type",
        help="默认自动判断；若题干已标注单选/多选，会自动遵循题干。",
    )

    # 3. 唯一的可编辑文本框
    raw_input = st.text_area(
        "题目文字（可直接粘贴或修改上方识别出的文字，需包含题干和选项）",
        height=140,
        placeholder="例如：\n处理工程与人关系的基本原则是：\nA. 社会公正\nB. 人道主义\nC. 人与自然和谐发展\nD. 人与环境和谐相处",
        key="choice_unified_text_area",
    )

    # 4. 按钮行：「搜索并解答」+「清空」并排，on_click 在渲染前修改状态
    search_clicked = st.button(
        "🚀 搜索并解答", type="primary", use_container_width=True,
        key="btn_solve_choice_unified",
    )
    st.button(
        "🗑️ 清空", type="secondary", use_container_width=True,
        key="btn_clear_choice",
        on_click=_clear_choice_state,
    )

    if search_clicked:
        text_to_solve = raw_input.strip()
        if not text_to_solve:
            st.warning("请输入或上传题目内容。")
        else:
            with st.spinner("正在检索题库与课件并分析答案…"):
                solution = solve_choice_raw_text(
                    raw_text=text_to_solve,
                    question_type=question_type,
                    retriever=retriever,
                    settings=settings,
                    allow_api=allow_api,
                )
            st.session_state["last_choice_solution"] = solution
            st.rerun()

    # 4. 答案展示区域
    last_solution = st.session_state.get("last_choice_solution")
    if last_solution is not None:
        st.divider()
        render_choice_solution(last_solution)

def main() -> None:
    st.set_page_config(
        page_title="工程伦理 RAG 复习助手",
        page_icon="📚",
        layout="wide",
    )
    st.markdown(MOBILE_CSS, unsafe_allow_html=True)
    if reset_release_session(st.session_state):
        # 只失效本项目知识库运行时，不重置额度或其他应用缓存。
        getattr(load_runtime, 'clear', lambda: None)()
    st.title("📚 工程伦理 RAG 复习助手")
    st.caption(
        "本地 PPT/教材/题库检索 · 混合/本地两种模式 · 回答附来源与物理页码 · "
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
            options=(QA_MODE_HYBRID, QA_MODE_LOCAL),
            format_func=lambda value: (
                "混合模式（默认）" if value == QA_MODE_HYBRID else "本地模式（仅检索）"
            ),
            index=0,
            captions=(
                "先检索本地材料；有依据时交给 DeepSeek 组织，材料不足时允许通用补充。",
                "只检索本地知识库；不调用 DeepSeek，展示证据、来源文件与物理页码。",
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
        if qa_mode == QA_MODE_LOCAL:
            effective_ai = False
        settings=replace(settings,api_enabled=effective_ai)
        provider,allow_api=select_answer_provider(effective_ai)
        if qa_mode == QA_MODE_LOCAL:
            st.caption('本地模式：仅检索本地知识库，不调用 DeepSeek。')
        elif not effective_ai:
            st.caption('AI未开启：混合模式只使用本地材料；材料不足时不做模型补充。')

        st.divider()
        with st.expander("审核类别统计"):
            rows = [
                {
                    "类别": REVIEW_CATEGORY_LABELS.get(category, UNREVIEWED_LABEL),
                    "页数": count,
                }
                for category, count in stats["review_categories"].items()
            ]
            st.dataframe(rows, hide_index=True, width="stretch")

        st.caption("旧版607页/新版193页分别检索；新版全部待审核。两套PDF和处理结果均只读。")

    from contextlib import nullcontext
    if hasattr(st, 'tabs'):
        tab_qa, tab_choice, tab_case = st.tabs(["📝 简答题问答", "🔘 选择题答题", "🧩 案例分析题"])
        with tab_choice:
            st.caption('选择题固定使用混合模式：本地题库/课件优先，材料不足时由 DeepSeek 独立推理。')
            render_choice_tab(retriever, settings, allow_api)
        with tab_case:
            st.caption('案例分析题：默认混合模式，逐问检索老师 PPT；一次提交最多一次 DeepSeek 调用。')
            render_case_tab(retriever, settings, allow_api)
        qa_container = tab_qa
    else:
        qa_container = nullcontext()

    with qa_container:
        st.caption('输入或上传题目，确认文字后点击“检索并回答”；回答模式、AI开关与预算设置在侧栏。')
        st.subheader('输入考试题目')
        engine = AnswerEngine(retriever, settings=settings)
        if "qa_uploader_epoch" not in st.session_state:
            st.session_state["qa_uploader_epoch"] = 0
        qa_epoch = st.session_state["qa_uploader_epoch"]
        if hasattr(st, "file_uploader"):
            qa_file = st.file_uploader(
                "上传题目截图（可选，PNG/JPG/JPEG）",
                type=["png", "jpg", "jpeg"],
                key=f"qa_file_uploader_{qa_epoch}",
                help="只做本地 OCR 文字提取，不会自动提交或调用 DeepSeek。",
            )
        else:
            qa_file = None
        if qa_file is not None:
            with st.spinner("正在识别题目截图…"):
                qa_upload_status, qa_upload_message = process_qa_upload(qa_file, st.session_state)
        else:
            qa_upload_status, qa_upload_message = process_qa_upload(qa_file, st.session_state)
        if qa_upload_status == "success":
            st.success(qa_upload_message)
        elif qa_upload_status == "error":
            st.warning(qa_upload_message)
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
        st.button(
            "清空题目",
            type="secondary",
            use_container_width=True,
            key="btn_clear_qa",
            on_click=_clear_qa_state,
        )

        if submitted:
            if not question.strip():
                st.warning("请输入问题。")
            else:
                with st.spinner("正在检索本地材料并生成答案…"):
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
