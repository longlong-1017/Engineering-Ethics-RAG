"""结构化考试答案：JSON 解析、结构与事实校验、统一渲染。

模型只负责给出 summary / points / conclusion，引用通过每条的 citations 数组表达；
Python 负责验证、渲染 [S#] 和真实 PDF 文件名/页码。这样不再依赖模型自由文本中
[S#] 的位置来判断某条结论是否带引用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any, Mapping, Sequence

from src.citations import assess_claim_support, assess_claim_support_legacy, strip_internal_status
from src.retriever import Hit
from src.text_utils import compact_text


CITATION_TOKEN_RE = re.compile(r"^[\[【(（]?\s*[Ss]\s*(\d+)\s*[\]】)）]?$")
INLINE_CITATION_RE = re.compile(r"[\[【(（]\s*S\s*(\d+)\s*[\]】)）]", re.IGNORECASE)
PAGE_OR_PDF_RE = re.compile(r"\.pdf|第\s*[0-9０-９一二三四五六七八九十百]+\s*页|《[^》]*\.pdf》", re.IGNORECASE)


@dataclass(frozen=True)
class StructuredPoint:
    content: str
    refs: tuple[int, ...]
    kind: str = "courseware"
    basis: str = ""


@dataclass(frozen=True)
class StructuredAnswer:
    summary: str
    points: tuple[StructuredPoint, ...]
    conclusion: str
    insufficient: bool
    supplements: tuple[str, ...] = ()


@dataclass(frozen=True)
class StructuredValidation:
    ok: bool
    answer: StructuredAnswer | None
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    citations: tuple[int, ...]
    layers: dict = field(default_factory=dict)


def _extract_json_object(content: str) -> str:
    text = (content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("未找到 JSON 对象")
    return text[start:end + 1]


def _inline_citation_refs(text: str) -> list[int]:
    return [int(match.group(1)) for match in INLINE_CITATION_RE.finditer(text)]


def _strip_inline_citations(text: str) -> tuple[str, bool]:
    cleaned = INLINE_CITATION_RE.sub("", text)
    return cleaned.strip(), cleaned != text


def _normalize_citations(value: Any, allowed: set[int]) -> tuple[tuple[int, ...], list[str]]:
    errors: list[str] = []
    if not isinstance(value, list):
        return (), ["citations 必须是数组"]
    refs: list[int] = []
    for raw in value:
        match = CITATION_TOKEN_RE.match(str(raw).strip())
        if not match:
            errors.append(f"非法引用编号：{raw!r}")
            continue
        ref = int(match.group(1))
        if ref not in allowed:
            errors.append(f"引用了不存在的证据编号：S{ref}")
            continue
        if ref not in refs:
            refs.append(ref)
    if not refs and not errors:
        errors.append("该条论述没有 citations")
    return tuple(refs), errors


def parse_structured_answer(content: str, allowed_refs: Sequence[int]) -> StructuredValidation:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        raw = json.loads(_extract_json_object(content))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return StructuredValidation(False, None, (f"JSON 解析失败：{exc}",), (), ())
    if not isinstance(raw, dict):
        return StructuredValidation(False, None, ("JSON 根节点必须是对象",), (), ())
    for key in ("summary", "points", "conclusion", "insufficient"):
        if key not in raw:
            errors.append(f"缺少字段：{key}")
    if errors:
        return StructuredValidation(False, None, tuple(errors), tuple(warnings), ())
    summary = raw.get("summary")
    conclusion = raw.get("conclusion")
    points_raw = raw.get("points")
    insufficient = raw.get("insufficient")
    if not isinstance(summary, str) or not isinstance(conclusion, str):
        errors.append("summary 和 conclusion 必须是字符串")
    if not isinstance(insufficient, bool):
        errors.append("insufficient 必须是布尔值")
    if not isinstance(points_raw, list):
        errors.append("points 必须是数组")
    if errors:
        return StructuredValidation(False, None, tuple(errors), tuple(warnings), ())

    summary = strip_internal_status(summary)
    conclusion = strip_internal_status(conclusion)
    allowed = set(int(ref) for ref in allowed_refs)
    summary_refs = _inline_citation_refs(summary)
    summary, changed = _strip_inline_citations(summary)
    if changed:
        invalid = sorted({ref for ref in summary_refs if ref not in allowed})
        if invalid:
            errors.append("summary 内联引用了不存在的证据编号：" + "、".join(f"S{ref}" for ref in invalid))
        warnings.append("已移除 summary 中的内联 [S#]；引用应由 points.citations 表达。")
    conclusion_refs = _inline_citation_refs(conclusion)
    conclusion, changed = _strip_inline_citations(conclusion)
    if changed:
        invalid = sorted({ref for ref in conclusion_refs if ref not in allowed})
        if invalid:
            errors.append("conclusion 内联引用了不存在的证据编号：" + "、".join(f"S{ref}" for ref in invalid))
        warnings.append("已移除 conclusion 中的内联 [S#]；引用应由 points.citations 表达。")
    for label, text in (("summary", summary), ("conclusion", conclusion)):
        if PAGE_OR_PDF_RE.search(text):
            errors.append(f"{label} 不得包含模型自行生成的 PDF 文件名或页码")

    points: list[StructuredPoint] = []
    if not insufficient:
        if not points_raw:
            errors.append("insufficient=false 时 points 不能为空")
        for index, item in enumerate(points_raw, 1):
            if not isinstance(item, dict):
                errors.append(f"第 {index} 条论述必须是对象")
                continue
            point_content = item.get("content")
            if not isinstance(point_content, str) or not point_content.strip():
                errors.append(f"第 {index} 条论述缺少 content")
                continue
            point_content = strip_internal_status(point_content)
            if not compact_text(point_content):
                warnings.append(f"已移除第 {index} 条内部审核提示")
                continue
            inline_refs_before = _inline_citation_refs(point_content)
            point_content, changed = _strip_inline_citations(point_content)
            if changed:
                invalid = sorted({ref for ref in inline_refs_before if ref not in allowed})
                if invalid:
                    errors.append(
                        f"第 {index} 条 content 内联引用了不存在的证据编号："
                        + "、".join(f"S{ref}" for ref in invalid)
                    )
                warnings.append(f"已移除第 {index} 条 content 中的内联 [S#]。")
            if PAGE_OR_PDF_RE.search(point_content):
                errors.append(f"第 {index} 条 content 不得包含 PDF 文件名或页码")
            refs, ref_errors = _normalize_citations(item.get("citations"), allowed)
            errors.extend(f"第 {index} 条：{error}" for error in ref_errors)
            kind=item.get('kind','courseware')
            basis=item.get('basis','')
            if kind not in ('courseware','analysis') or not isinstance(basis,str):
                errors.append(f'第 {index} 条：kind/basis无效')
                kind='courseware';basis=''
            points.append(StructuredPoint(point_content, refs,kind,basis))
    else:
        points = []

    supplements_raw = raw.get('supplements', [])
    supplements = []
    if not isinstance(supplements_raw, list):
        errors.append('supplements 必须为字符串数组')
    else:
        for text in supplements_raw:
            if not isinstance(text, str) or not text.strip():
                errors.append('AI补充必须为非空字符串')
            elif INLINE_CITATION_RE.search(text) or PAGE_OR_PDF_RE.search(text) or re.search(r'依据课件|根据课件|课件指出', text):
                errors.append('AI补充不得伪造课件引用、文件名或页码')
            else:
                supplements.append(strip_internal_status(text))
    answer = StructuredAnswer(summary=summary, points=tuple(points), conclusion=conclusion,
                              insufficient=insufficient, supplements=tuple(supplements))
    usable = bool(compact_text(summary) or points or compact_text(conclusion))
    if errors and not usable:
        return StructuredValidation(False, None, tuple(dict.fromkeys(errors)), tuple(warnings), ())
    citations = tuple(sorted({ref for point in points for ref in point.refs}))
    return StructuredValidation(
        not errors, answer, tuple(dict.fromkeys(errors)),
        tuple(dict.fromkeys(warnings)), citations,
    )


def validate_structured_answer(
    answer: StructuredAnswer,
    question: str,
    evidence_map: Mapping[int, tuple[Hit, str]],
    *, policy: str = "core",
) -> StructuredValidation:
    errors: list[str] = []
    warnings: list[str] = []
    if policy not in ("core","legacy"):
        raise ValueError("未知校验策略")
    checker=assess_claim_support_legacy if policy=="legacy" else assess_claim_support
    if answer.insufficient:
        return StructuredValidation(True, answer, (), (), ())

    used_texts: list[str] = []
    supported_points=[]
    integrity=[]
    source_review={}
    for ref,(hit,text) in evidence_map.items():
        page=hit.page
        if (not page.filename or not isinstance(page.page_number,int) or isinstance(page.page_number,bool)
                or page.page_number<1 or getattr(hit,'rank',ref)!=ref
                or not compact_text(text) or compact_text(text) not in compact_text(page.text)):
            integrity.append(f'S{ref}来源文件、物理页码或证据正文无法映射')
        source_review[ref]={'filename':page.filename,'page_number':page.page_number,
                          'strict_eligible':page.strict_eligible,'category':page.review_category}
    errors.extend(integrity)
    for index, point in enumerate(answer.points, 1):
        point_texts = [evidence_map[ref][1] for ref in point.refs if ref in evidence_map]
        if len(point_texts) != len(point.refs):
            integrity.append(f"第 {index} 条：引用编号没有对应的证据正文")
            errors.append(integrity[-1])
            continue
        used_texts.extend(point_texts)
        if not point.refs:
            integrity.append(f'第 {index} 条：缺少引用编号')
            errors.append(integrity[-1])
            continue
        if point.kind=='analysis':
            # 推论必须先交代能在所引材料中定位的概念依据，不冒充原文事实。
            support=checker(point.basis,point_texts,require_each_ref=True)
            if not point.basis.strip() or not re.search(r'建议|可考虑|应|宜|需要',point.content):
                errors.append(f'第 {index} 条：案例分析需提供依据及建议性表达')
            if re.search(r'已经|已造成|证实|研究表明|确实|必然|一定',point.content):
                errors.append(f'第 {index} 条：案例推论不能断言未经证实的具体事实')
            from src.citations import _numbers, _number_in, PROTECTED_TERMS
            if any(not _number_in(n,'\n'.join(point_texts)) for n in _numbers(point.content)):
                errors.append(f'第 {index} 条：案例分析含无依据数字')
            for term in PROTECTED_TERMS:
                if term in point.content and term not in '\n'.join(point_texts):
                    errors.append(f'第 {index} 条：案例分析包含无依据具体术语：{term}')
        else:
            support=checker(point.content,point_texts,question,require_each_ref=True,strict_unknown=False)
        if not support.ok:
            errors.extend(f'第 {index} 条：{reason}' for reason in support.reasons)
        elif point.kind=='courseware':
            supported_points.append(point.content)

    union_text = "\n".join(used_texts if policy=="legacy" else supported_points)
    for label, text in (("summary", answer.summary), ("conclusion", answer.conclusion)):
        if not compact_text(text):
            continue
        support = checker(text, [union_text] if union_text else [], question)
        if not support.ok:
            errors.extend(f"{label}：{reason}" for reason in support.reasons)

    citations = tuple(sorted({ref for point in answer.points for ref in point.refs}))
    return StructuredValidation(
        ok=not errors, answer=answer, errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(warnings), citations=citations,
        layers={'reference_integrity':{'ok':not integrity,'errors':integrity},
                'claim_support':{'ok':not [e for e in errors if e not in integrity],'errors':[e for e in errors if e not in integrity]},
                'source_review':source_review},
    )


def _draft_text(text: str) -> str:
    """草稿展示层移除模型自造文件名/页码，避免被误认为已验证引用。"""
    return re.sub(r"《[^》]*\.pdf》|\.pdf|第\s*[0-9０-９一二三四五六七八九十百]+\s*页",
                  "[已移除模型自造引用/页码]", text, flags=re.IGNORECASE)


def render_unverified_draft(answer: StructuredAnswer, errors: Sequence[str], evidence_map=None) -> str:
    """真实来源可以映射，但映射存在不代表论点已验证。失败原因由页面单独展示。"""
    evidence_map = evidence_map or {}
    lines = ['【简明答案】', _draft_text(answer.summary), '', '【分点论述】']
    for index, point in enumerate(answer.points, 1):
        refs = ' '.join(f'[S{ref}]' for ref in point.refs if ref in evidence_map)
        lines.append(f"{index}. {'【基于课件的案例分析】' if point.kind=='analysis' else ''}{_draft_text(point.content)} {refs}".rstrip())
    lines.extend(['', '【总结】', _draft_text(answer.conclusion)])
    if answer.supplements:
        lines.extend(['', '【AI补充（未经课件核实）】', *map(_draft_text, answer.supplements)])
    lines.extend(['', '【参考课件】'])
    refs = sorted({ref for p in answer.points for ref in p.refs if ref in evidence_map})
    for ref in refs:
        lines.append(f'- [S{ref}] {evidence_map[ref][0].citation}')
    if not refs:
        lines.append('- 无可映射的引用；请查看独立风险提示。')
    return '\n'.join(lines)


def render_structured_answer(
    answer: StructuredAnswer,
    evidence_map: Mapping[int, tuple[Hit, str]],
) -> str:
    if answer.insufficient:
        summary = answer.summary.strip() or "现有课件证据不足以回答该问题。"
        return "\n".join([
            "【简明答案】",
            f"资料不足：{summary}",
            "",
            "【参考依据】",
            "- 无可用课件引用（未生成 [S#] 或 PDF 页码）",
        ])
    lines = ["【简明答案】", answer.summary.strip() or "（模型未提供简明结论）", "", "【分点论述】"]
    for index, point in enumerate(answer.points, 1):
        refs = " ".join(f"[S{ref}]" for ref in point.refs)
        lines.append(f"{index}. {'【基于课件的案例分析】' if point.kind=='analysis' else ''}{point.content.strip()} {refs}")
    lines.extend(["", "【总结】", answer.conclusion.strip() or "（无额外总结）", "", "【参考依据】"])
    if answer.supplements:
        # 放在总结之后、参考课件之前，与有引用的课件论述隔离。
        lines[-1:] = ['【AI补充（未经课件核实，不作为课件依据）】', *answer.supplements, '', '【参考依据】']
    lines.append('【参考课件】')
    seen: list[int] = []
    for point in answer.points:
        for ref in point.refs:
            if ref not in seen:
                seen.append(ref)
    if not seen:
        lines.append("- 无可用课件引用")
    for ref in seen:
        hit = evidence_map[ref][0]
        lines.append(f"- [S{ref}] {hit.citation}")
    return "\n".join(lines)
