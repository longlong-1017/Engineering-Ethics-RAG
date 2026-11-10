"""模型答案引用校验：允许准确归纳，但每条事实结论必须能由所引证据支持。

校验目标（不调用外部模型）：
1. 只允许使用提示词里实际给出的 [S#]；
2. 每条实质性结论必须有引用，不能有未引用的新增事实；
3. 引用页必须与结论有实质词项/数字重合，不能用无关来源凑引用；
4. 数字必须在所引证据中精确出现；
5. 多页引用时，每一页都必须对结论有贡献。

这是保守的词法校验，不声称具备通用语义蕴含能力；无法通过时由调用方回退。
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Iterable, Sequence

from src.text_utils import compact_text, query_terms


CITATION_RE = re.compile(r"\[S(\d+)\]", re.IGNORECASE)
CITATION_GROUP_RE = re.compile(r"(?:\[S\d+\])+", re.IGNORECASE)
GROUPED_CITATION_RE = re.compile(
    r"\[\s*S\d+(?:\s*[,，、]\s*S\d+)+\s*\]", re.IGNORECASE
)
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?%?")
LIST_PREFIX_RE = re.compile(
    r"^\s*(?:[①-⑩]|[-*•●▪]|(?:[0-9０-９]+|[一二三四五六七八九十]+)[.、)）]|"
    r"[（(](?:[0-9０-９]+|[一二三四五六七八九十]+)[)）])\s*"
)
ASSERTION_RE = re.compile(
    r"是|为|包括|包含|分为|构成|导致|造成|使得|应当|必须|需要|可以|不能|"
    r"具有|属于|表现|表明|说明|提出|认为|主要|有|会|将|应|须"
)
FACT_RE = re.compile(
    r"造成|导致|使得|引发|发生|存在|失灵|老化|爆炸|死亡|受伤|坍塌|"
    r"包括|分为|具有|属于|表明|说明|证明|增加|减少|提高|降低|"
    r"死亡|遇难|殉职|受伤|泄漏|污染|破裂|失效|故障|拒绝|放弃|披露|离职|不参与"
)
# 列表前缀：编号、项目符号、圈号。用于区分“引导语/标题”和“事实条目”。
LIST_MARKER_RE = re.compile(
    r"^\s*(?:[①-⑩]|[-*•●▪]|(?:[0-9０-９]+|[一二三四五六七八九十]+)[.、)）]|"
    r"[（(](?:[0-9０-９]+|[一二三四五六七八九十]+)[)）])"
)
# 引导语结尾：如“包括：”“包括以下三类：”“如下：”。
GUIDE_END_RE = re.compile(
    r"(?:包括|包含|分为|如下|以下|主要有|分别是|表现在|体现在|列举如下|简述如下|概述如下)"
    r"(?:以下)?(?:[0-9０-９一二三四五六七八九十两]+(?:类|种|层|个|方面|项|点))?\s*[：:。]?$"
)
# 只剥离“依据课件/根据资料/综上所述”等非事实性连接前缀；
# 不把“依据/根据”加入全局停用词，避免把“依据合同……”等真实事实放行。
CONNECTIVE_PREFIX_RE = re.compile(
    r"^(?:(?:依据|根据|按照)"
    r"(?:课件|资料|证据|原文|上述|题目|材料|检索结果|课件原文|课件资料|上述资料|上述内容|以上资料|以上内容)?"
    r"|简明答案|结论|总结|分析|论述|答案|要点|案例(?:分析)?"
    r"|第[0-9０-９一二三四五六七八九十]+条"
    r"|综上(?:所述)?|总之|因此|所以|由此可见|可见|据此"
    r"|参考(?:依据|来源|资料)?|资料来源|来源|出处|注|说明|证据|引用|以上(?:内容|结论)?)"
    r"(?=[，,：:、\s]|$)[，,：:、\s]*"
)
POINTER_TERMS = frozenset(
    "以上 上述 如下 下面 以下 三点 两点 几点 内容 答案 结论 证据 引用 来源 出处 依据 资料 课件 原文".split()
)
# 归纳时常见的结构性/泛化词，不作为“未知实体”拒绝。
TERM_ALIASES = {
    "科技": ("科学", "技术"),
    "失效": ("失灵", "失调"),
    "故障": ("失灵",),
    "损坏": ("损害", "破坏"),
    "公开透明": ("公开", "披露"),
    "分配资源": ("分配社会资源", "资源分配"),
}
GENERIC_TERMS = frozenset(
    """
    根据 证据 课件 原文 答案 结论 总结 综上 因此 所以 同时 此外 另外 其中
    主要 重要 包括 包含 分为 构成 方面 方式 方法 过程 情况 内容 问题 影响
    结果 后果 原因 因素 作用 表现 体现 说明 表明 提出 认为 需要 应当 必须
    可以 能够 具有 属于 相关 具体 一般 首先 其次 最后 以及 并且 但是 然而
    因为 由于 所以 因此 造成 带来 导致 引发 出现 产生 总体 这样 这个 这种
    该类 该类问题 上述 如下 以下 相互 关联 联系 关系 首要 重要 方面
    发生 位于 该页 本页 复核 审核 未审核 换言之 简言之 一方面 另一方面 从而 进而 总体而言
    """.split()
)


# 仅剥离来源元数据，不删除“审核制度/审计责任”等课程事实。
INTERNAL_STATUS_RE = re.compile(
    r'[（(]?\s*(?:(?:该页|本页|此页|该来源|本来源|来源)\s*)?'
    r'(?:尚未(?:经过)?人工(?:逐条)?复核|未人工复核|未通过严格审核|未审核|未经核验|未核验)'
    r'(?:\s*[，,、；;]?\s*(?:(?:仍|尚)?(?:需要|需|待)复核|不关联\s*PDF\s*页码))*\s*[）)]?'
    r'|(?:该页|本页|此页)\s*(?:已经|已)?审核[，,、；;\s]*(?:(?:需要|需|待)复核)?'
    r'|[（(]\s*(?:需要|需|待)复核\s*[）)]'
)


def strip_internal_status(text: str) -> str:
    text = INTERNAL_STATUS_RE.sub('', text)
    return re.sub(r'[，,；;]{2,}', '，', text).strip(' ，,；;。')


@dataclass(frozen=True)
class ClaimCheck:
    text: str
    refs: tuple[int, ...]
    supported: bool
    coverage: float
    numbers_ok: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ClaimSupport:
    ok: bool
    coverage: float
    numbers_ok: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CitationValidation:
    ok: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    citations: tuple[int, ...]
    claims: tuple[ClaimCheck, ...]
    normalized_content: str

    @property
    def reason(self) -> str:
        return "；".join(self.errors[:6])


def normalize_citation_syntax(content: str) -> str:
    """把常见引用写法规范为稳定的 [S1]。"""
    # 不对全文做 NFKC：NFKC 会把 ① 变成 1，破坏列表标记；
    # 数字与词项比较时再按需规范化。
    text = content or ""
    text = (
        text.replace("【", "[")
        .replace("】", "]")
        .replace("〔", "[")
        .replace("〕", "]")
        .replace("（", "(")
        .replace("）", ")")
    )
    text = re.sub(r"\(\s*S\s*(\d+)\s*\)", r"[S\1]", text, flags=re.IGNORECASE)
    text = GROUPED_CITATION_RE.sub(
        lambda match: "".join(
            f"[S{number}]" for number in re.findall(r"S(\d+)", match.group(0), re.IGNORECASE)
        ),
        text,
    )
    return CITATION_RE.sub(lambda match: f"[S{int(match.group(1))}]", text)


def _clean_claim(text: str) -> str:
    text = re.sub(r"\*\*|__|`", "", text)
    text = LIST_PREFIX_RE.sub("", text)
    text = CITATION_RE.sub("", text)
    return text.strip(" \t\r\n　")


def _is_guide(text: str) -> bool:
    """判断是否为“包括：”“如下三类：”或名词性标题，而不是独立事实。"""
    stripped = text.strip()
    if not stripped:
        return False
    if GUIDE_END_RE.search(stripped):
        return True
    if stripped.endswith(("：", ":")):
        body = stripped[:-1].strip()
        if (
            body
            and not NUMBER_RE.search(body)
            and not FACT_RE.search(body)
            and not ASSERTION_RE.search(body)
            and (
                body in {"答案", "结论", "总结", "说明", "分析", "概述"}
                or re.search(
                    r"(因素|时间|地点|后果|参数|原则|方式|问题|方面|内容|背景|"
                    r"原因|结果|用途|动机|定义|概念|特点|类型|目标|意义|结构|"
                    r"过程|方法|措施|责任|风险)$",
                    body,
                )
            )
        ):
            return True
    return False


def _is_structural(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped.startswith("#"):
        return True
    if _is_guide(stripped):
        return True
    compact = compact_text(stripped)
    if len(compact) <= 14 and not NUMBER_RE.search(stripped) and not ASSERTION_RE.search(stripped) and not FACT_RE.search(stripped):
        return True
    if (
        compact.startswith(("根据课件", "根据证据", "以下", "答案", "结论", "总结", "说明"))
        and len(compact) <= 40
        and (stripped.endswith(("：", ":")) or not ASSERTION_RE.search(stripped))
    ):
        return True
    return False


def _strip_connectives(text: str) -> str:
    core = text.strip()
    for _ in range(4):
        stripped = CONNECTIVE_PREFIX_RE.sub("", core, count=1).strip()
        if stripped == core:
            break
        core = stripped
    return core.strip(" \t\r\n　，,。；;：:")


def _is_citation_pointer(text: str) -> bool:
    """判断“依据：[S1]”“综上所述”等非事实性引用指针。"""
    core = _strip_connectives(text)
    if not core:
        return True
    terms = _terms(core)
    numbers = _numbers(core)
    if not terms and not numbers:
        return True
    if terms and all(term in POINTER_TERMS for term in terms):
        return True
    return False


def _summary_supported(claim: str, evidence_text: str) -> bool:
    """允许“简明结论”总结句：必须由后文已引用的证据整体支持，不新增数字/实体。"""
    compact_claim = compact_text(claim)
    if len(compact_claim) > 90 or not evidence_text:
        return False
    numbers = _numbers(claim)
    if not all(_number_in(number, evidence_text) for number in numbers):
        return False
    terms = _terms(claim)
    if not terms:
        return False
    coverage = _coverage(terms, evidence_text)
    if coverage < 0.65:
        return False
    compact_evidence = compact_text(evidence_text)
    unknown = [
        term for term in terms
        if not _term_supported(term, compact_evidence) and term not in GENERIC_TERMS
    ]
    if len(unknown) > 2:
        return False
    if any(term in DANGER_QUALIFIERS for term in unknown):
        return False
    return True


SUMMARY_MARKER_RE = re.compile(
    r"^\s*(?:简明答案|结论|总结|分析|论述|答案|要点|案例(?:分析)?|"
    r"第[0-9０-９一二三四五六七八九十]+条|"
    r"综上(?:所述)?|总之|因此|所以|可见|由此可见)"
)
SUMMARY_RELATION_RE = re.compile(r"关系|关联|联系|影响|作用|总体|主要|包括")


def _is_summary_marker(claim: str) -> bool:
    return bool(SUMMARY_MARKER_RE.match(claim.strip()))


def _summary_pending(claim: str, evidence_text: str) -> bool:
    """无单独引用的总结句：只允许无新增数字/实体/限定词的保守总结。"""
    if not evidence_text:
        return False
    if len(compact_text(claim)) > 180:
        return False
    numbers = _numbers(claim)
    if numbers and not all(_number_in(number, evidence_text) for number in numbers):
        return False
    terms = _terms(claim)
    if not terms:
        return True
    compact_evidence = compact_text(evidence_text)
    unknown = [
        term for term in terms
        if not _term_supported(term, compact_evidence) and term not in GENERIC_TERMS
    ]
    if any(term in DANGER_QUALIFIERS for term in unknown):
        return False
    # 新的专名/实体通常 >=3 字；短连接/概括词可以待核实。
    if any(len(term) >= 3 for term in unknown):
        return False
    if len(unknown) > 8:
        return False
    return True


def _segments(content: str) -> Iterable[tuple[str, bool]]:
    # 一段/一个 bullet 作为一个整体，再按引用组拆成若干结论；
    # 这样“多句归纳 + 末尾 [S1]”不会被误判为无引用。
    for block in re.split(r"\n+", content):
        block = block.strip()
        if not block:
            continue
        heading = block.startswith("#")
        block = re.sub(r"^#{1,6}\s*", "", block).strip()
        if block:
            yield block, heading


def _numbers(text: str) -> list[str]:
    return NUMBER_RE.findall(unicodedata.normalize("NFKC", text or ""))


def _number_in(number: str, text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text or "")
    return bool(re.search(rf"(?<![\d.]){re.escape(number)}(?![\d.])", normalized))


_COUNT_TERM_RE = re.compile(r"^[一二三四五六七八九十两0-9]+(?:类|种|层|个|方面|项)$")


def _terms(text: str) -> tuple[str, ...]:
    return tuple(
        term
        for term in query_terms(text)
        if len(term) >= 2
        and term not in GENERIC_TERMS
        and not _COUNT_TERM_RE.match(term)
    )


def _loose(text: str) -> str:
    return compact_text(text).replace("的", "")


def _term_supported(term: str, compact_evidence: str) -> bool:
    compact_term = compact_text(term)
    if compact_term in compact_evidence:
        return True
    # 中文常见“的”字省略/插入，如“事故隐患”与“事故的隐患”。
    if _loose(term) in compact_evidence.replace("的", ""):
        return True
    return any(
        compact_text(alias) in compact_evidence or _loose(alias) in compact_evidence.replace("的", "")
        for alias in TERM_ALIASES.get(term, ())
    )


def _coverage(terms: Sequence[str], evidence_text: str) -> float:
    compact = compact_text(evidence_text)
    if not terms:
        return 1.0
    total = sum(max(1, len(term)) ** 2 for term in terms)
    matched = sum(
        max(1, len(term)) ** 2 for term in terms if _term_supported(term, compact)
    )
    return matched / total if total else 1.0


CONTRIBUTION_STOP = frozenset({"工程", "风险", "伦理", "事故", "事件", "问题", "因素", "包括", "方面"})
# 会改变结论真值的限定词：证据没有就不能由模型添加。
DANGER_QUALIFIERS = frozenset(
    "公开 所有 全部 任何 允许 禁止 无需 免费 永久 绝对 一定 完全 唯一 从不 必然 "
    "冲突 无关 对立 相反 决定 证明 出售 购买 泄露 隐瞒 伪造 篡改 忽略".split()
)


def _ref_contributes(terms: Sequence[str], numbers: Sequence[str], evidence_text: str) -> bool:
    compact = compact_text(evidence_text)
    specific = [
        term
        for term in terms
        if len(term) >= 2
        and term not in GENERIC_TERMS
        and term not in CONTRIBUTION_STOP
    ]
    candidates = specific or list(terms)
    if any(_term_supported(term, compact) for term in candidates):
        return True
    return any(_number_in(number, evidence_text) for number in numbers)


def assess_claim_support_legacy(
    claim: str,
    evidence_texts: Sequence[str],
    question: str = "",
    *,
    require_each_ref: bool = False,
    strict_unknown: bool = False,
) -> ClaimSupport:
    """结构化输出的单条事实校验；不解析自由文本中的引用位置。"""
    claim = strip_internal_status(claim)
    texts = [text for text in evidence_texts if text]
    if not texts:
        return ClaimSupport(False, 0.0, False, ("没有可用的所引证据正文",))
    evidence_text = "\n".join(texts)
    claim_numbers = _numbers(claim)
    numbers_ok = all(_number_in(number, evidence_text) for number in claim_numbers)
    reasons: list[str] = []
    if not numbers_ok:
        reasons.append("数字未在所引证据出现：" + "、".join(claim_numbers))
    terms = _terms(claim)
    if not terms and not claim_numbers:
        return ClaimSupport(not reasons, 1.0, numbers_ok, tuple(reasons))
    coverage = _coverage(terms, evidence_text)
    if coverage < 0.65:
        reasons.append(f"结论与所引证据的关键词覆盖不足（{coverage:.0%}）")
    compact_evidence = compact_text(evidence_text)
    question_compact = compact_text(question)
    unknown = [
        term for term in terms
        if not _term_supported(term, compact_evidence)
        and compact_text(term) not in question_compact
        and term not in GENERIC_TERMS
    ]
    long_unknown = [term for term in unknown if len(term) >= 3]
    danger = [term for term in terms if term in DANGER_QUALIFIERS and term in unknown]
    if strict_unknown and unknown:
        reasons.append(
            "论述包含所引证据未支持的词："
            + "、".join(unknown[:6])
        )
    elif coverage < 0.65 or long_unknown or danger:
        reasons.append(
            "结论包含所引证据未支持的关键词："
            + "、".join((danger + long_unknown or unknown)[:4])
        )
    if require_each_ref:
        for text in texts:
            if not _ref_contributes(terms, claim_numbers, text):
                reasons.append("存在与结论无实质重合的引用页")
                break
    return ClaimSupport(
        ok=not reasons, coverage=coverage, numbers_ok=numbers_ok,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _claim_items(segment: str) -> list[tuple[str, tuple[int, ...], bool]]:
    """把一段文本拆成（结论正文，引用编号，是否列表条目）列表。

    引用组附着在前一条结论上；引用组后面的新文本视为新的、尚未引用的结论。
    行首引用会附着到后续文本。
    """
    matches = list(CITATION_GROUP_RE.finditer(segment))
    if not matches:
        raw = segment.strip()
        return [(_clean_claim(segment), (), bool(LIST_MARKER_RE.match(raw)))]
    items: list[tuple[str, tuple[int, ...], bool]] = []
    pending: list[int] = []
    cursor = 0
    for match in matches:
        raw = segment[cursor:match.start()]
        text = _clean_claim(raw)
        refs = tuple(int(number) for number in CITATION_RE.findall(match.group(0)))
        if text:
            items.append((text, tuple(pending) + refs, bool(LIST_MARKER_RE.match(raw.strip()))))
            pending = []
        else:
            pending.extend(refs)
        cursor = match.end()
    raw_tail = segment[cursor:]
    tail = _clean_claim(raw_tail)
    if tail:
        items.append((tail, tuple(pending), bool(LIST_MARKER_RE.match(raw_tail.strip()))))
    return items


def validate_citations(
    question: str,
    content: str,
    evidence: Sequence[tuple[Any, str]],
) -> CitationValidation:
    """校验模型回答；evidence 为 (hit, 原文片段) 序列，hit.rank 是允许编号。"""
    normalized = normalize_citation_syntax(content)
    allowed = {int(hit.rank): text for hit, text in evidence}
    question_compact = compact_text(question)
    errors: list[str] = []
    checks: list[ClaimCheck] = []
    warnings: list[str] = []
    used: set[int] = set()
    saw_claim = False

    if not allowed:
        return CitationValidation(
            False, ("没有可用的证据块",), (), (), (), normalized
        )

    units: list[tuple[str, tuple[int, ...], bool, bool]] = []
    for segment, heading in _segments(normalized):
        for claim, refs, list_item in _claim_items(segment):
            if claim:
                units.append((claim, refs, list_item, heading))

    cited_claim_count = sum(
        1 for _, refs, _, _ in units if any(ref in allowed for ref in refs)
    )
    cited_evidence_text = "\n".join(
        allowed[ref]
        for ref in sorted({ref for _, refs, _, _ in units for ref in refs if ref in allowed})
    )
    seen_substantive = False
    claim_index = 0
    for claim, refs, list_item, heading in units:
            claim_index += 1
            # 去掉“结论：”“依据课件/综上所述”等结构前缀后再判断；
            # 只有剥离后仍含真实事实的句子才进入证据匹配。
            core = _strip_connectives(claim)
            if _is_citation_pointer(claim):
                continue
            if not refs:
                # 引导语/标题可无引用；列表条目和独立事实必须引用。
                if heading or _is_guide(core) or (
                    claim_index == 1 and not list_item and _is_structural(core)
                ):
                    continue
                # 允许开头一句“简明结论”，但必须由后文至少两条已引用结论整体支持；
                # 不新增数字/实体，也不在答案里伪造引用。
                if (
                    not seen_substantive
                    and cited_claim_count >= 2
                    and _summary_supported(core or claim, cited_evidence_text)
                ):
                    seen_substantive = True
                    saw_claim = True
                    checks.append(
                        ClaimCheck(
                            text=core or claim, refs=(), supported=True,
                            coverage=_coverage(_terms(core or claim), cited_evidence_text),
                            numbers_ok=True, reasons=("总结句由后文引用证据支持",),
                        )
                    )
                    continue
                # 普通总结句如果确实没有新增数字/实体，可标记待核实而不是整篇拒绝；
                # 不补引用，也不把它当作已核实事实。
                labeled_summary = _is_summary_marker(claim)
                first_summary = (
                    claim_index == 1
                    and not list_item
                    and bool(SUMMARY_RELATION_RE.search(claim))
                    and cited_claim_count >= 2
                )
                if (
                    cited_claim_count >= 1
                    and (labeled_summary or first_summary)
                    and _summary_pending(core or claim, cited_evidence_text)
                ):
                    seen_substantive = True
                    warning = f"总结句未单独标注引用，待核实：{(core or claim)[:80]}"
                    warnings.append(warning)
                    checks.append(
                        ClaimCheck(
                            text=core or claim, refs=(), supported=False,
                            coverage=_coverage(_terms(core or claim), cited_evidence_text),
                            numbers_ok=True, reasons=("待核实：无单独引用",),
                        )
                    )
                    continue
                seen_substantive = True
                errors.append(f"第 {claim_index} 条结论缺少 [S#] 引用：{claim[:40]}")
                checks.append(ClaimCheck(claim, (), False, 0.0, True, ("缺少引用",)))
                continue
            seen_substantive = True
            claim = core or claim
            saw_claim = True
            claim_errors: list[str] = []
            invalid_refs = sorted({ref for ref in refs if ref not in allowed})
            if invalid_refs:
                claim_errors.append(
                    "引用了不存在的证据编号：" + "、".join(f"S{ref}" for ref in invalid_refs)
                )
            valid_refs = tuple(ref for ref in refs if ref in allowed)
            used.update(valid_refs)
            if not valid_refs:
                errors.extend(claim_errors)
                checks.append(ClaimCheck(claim, refs, False, 0.0, True, tuple(claim_errors)))
                continue

            claim_numbers = _numbers(claim)
            numbers_ok = all(
                _number_in(number, "\n".join(allowed[ref] for ref in valid_refs))
                for number in claim_numbers
            )
            if not numbers_ok:
                claim_errors.append(
                    "数字未在所引证据出现：" + "、".join(claim_numbers)
                )

            claim_terms = _terms(claim)
            if claim_terms or claim_numbers:
                evidence_text = "\n".join(allowed[ref] for ref in valid_refs)
                coverage = _coverage(claim_terms, evidence_text)
                if coverage < 0.55:
                    claim_errors.append(f"结论与所引证据的关键词覆盖不足（{coverage:.0%}）")
                compact_evidence = compact_text(evidence_text)
                unknown = [
                    term
                    for term in claim_terms
                    if not _term_supported(term, compact_evidence)
                    and compact_text(term) not in question_compact
                    and term not in GENERIC_TERMS
                ]
                # 允许同义改写引入少量普通词；低覆盖、未知长实体或新增限定词则拒绝。
                long_unknown = [term for term in unknown if len(term) >= 3]
                danger = [term for term in claim_terms if term in DANGER_QUALIFIERS and term in unknown]
                if coverage < 0.65 or long_unknown or danger:
                    claim_errors.append(
                        "结论包含所引证据未支持的关键词："
                        + "、".join((danger + long_unknown or unknown)[:4])
                    )
                for ref in valid_refs:
                    if not _ref_contributes(claim_terms, claim_numbers, allowed[ref]):
                        claim_errors.append(f"引用 S{ref} 与该条结论无实质重合")
            else:
                coverage = 1.0

            checks.append(
                ClaimCheck(
                    text=claim,
                    refs=refs,
                    supported=not claim_errors,
                    coverage=coverage,
                    numbers_ok=numbers_ok,
                    reasons=tuple(claim_errors),
                )
            )
            errors.extend(claim_errors)

    if not saw_claim:
        errors.append("答案未包含任何可核验的 [S#] 引用")
    citations = tuple(sorted(used))
    return CitationValidation(
        ok=not errors,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
        citations=citations,
        claims=tuple(checks),
        normalized_content=normalized,
    )


# 仅规范语言表达；不删除数字、否定事实或专业术语。
FUNCTION_PHRASES = ('不仅', '还要', '关注', '二者之间', '与此同时', '总体而言', '换言之', '不能仅', '不能只', '不同于')
PARAPHRASES = {'不能忽略':'重视', '公众健康':'公众安全与健康', '公平':'公正', '设备老化':'零部件老化',
              '系统故障':'系统失灵', '非线性效应':'非线性作用', '履行责任':'承担责任'}
PROTECTED_TERMS = ('化学工程', '危险源')


def normalize_claim_language(text):
    text = strip_internal_status(text)
    for phrase in FUNCTION_PHRASES:
        text=text.replace(phrase, '')
    for phrase, replacement in PARAPHRASES.items():
        text=text.replace(phrase, replacement)
    return text


def assess_claim_support(claim, evidence_texts, question='', *, require_each_ref=False, strict_unknown=False):
    normalized=normalize_claim_language(claim)
    evidence=[normalize_claim_language(t) for t in evidence_texts]
    result=assess_claim_support_legacy(normalized,evidence,normalize_claim_language(question),
                                     require_each_ref=require_each_ref,strict_unknown=strict_unknown)
    reasons=list(result.reasons)
    # 不能因专业名词恰在用户问题中出现，就免除其证据支持要求。
    union='\n'.join(evidence_texts)
    for term in PROTECTED_TERMS:
        if term in claim and term not in union:
            reasons.append('具体术语没有所引证据支持：'+term)
    # 不能仅凭“不能”二字拒绝；只检查明显颠倒已给出的因果谓词。
    for negative,positive in (('不会导致','导致'),('不会引发','引发'),('不能造成','造成')):
        if negative in claim and positive in union and negative not in union:
            reasons.append('因果否定与所引证据可能相反：'+negative)
    return ClaimSupport(not reasons,result.coverage,result.numbers_ok,tuple(dict.fromkeys(reasons)))
