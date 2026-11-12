"""选择题答题核心模块：题库匹配、选项重排映射、RAG检索与DeepSeek推理。

核心原则：
1. 本地题库优先：精确匹配题干与选项；选项顺序改变时正确映射答案字母。
2. 答案安全守卫：仅已核实且非NULL答案可作为标准答案；待核实题目严禁以历史作答冒充标准答案。
3. RAG + DeepSeek推理：题库未命中或待核实时，检索课件并调用模型推断，明确标注来源。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Sequence

from src.quiz_bank import DEFAULT_DB, query_questions
from src.deepseek_client import DeepSeekClient, DeepSeekError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParsedChoiceQuestion:
    stem: str
    options: dict[str, str]
    question_type: str  # '自动' / '单选' / '多选'
    raw_text: str = ""
    reverse: bool = False


@dataclass(frozen=True)
class ChoiceSolution:
    answer: str | None
    source: str
    source_detail: str
    analysis: str
    verified: bool
    evidence_context: list[dict[str, Any]] = field(default_factory=list)
    confidence: str = "high"
    warning: str = ""
    bank_id: str | None = None
    mapped_from_bank: bool = False
    question_type: str = "自动"
    option_analysis: dict[str, str] = field(default_factory=dict)
    uncertainty_reason: str = ""
    diagnostic: dict[str, Any] = field(default_factory=dict)


def normalize_text(text: str) -> str:
    """去除首尾空白、标点和换行，用于模糊比对。"""
    if not text:
        return ""
    # 去除常见中英文标点与空白
    return re.sub(r'[\s\u3000\.,!?:;，。！？：；、\(\)（）\[\]【】_—\-]+', '', text).strip()


def parse_choice_text(raw_text: str) -> ParsedChoiceQuestion:
    """从原始题目文本中自动解析题干、选项和题型。"""
    raw_text = raw_text.strip()
    if not raw_text:
        return ParsedChoiceQuestion(stem="", options={}, question_type="自动", raw_text="")

    # 1. 题型识别：没有明确标注时必须是“自动”，不能预设单选。
    question_type = "自动"
    if re.search(r'[\[\［【\(\（]\s*多选\s*[\]\］】\)\）]|多选题|多项选择题', raw_text):
        question_type = "多选"
    elif re.search(r'[\[\［【\(\（]\s*单选\s*[\]\］】\)\）]|单选题|单项选择题', raw_text):
        question_type = "单选"
    reverse = bool(re.search(r'不正确|不包括|不属于|错误的是|不恰当|不正确|有误|错误', raw_text))

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    options: dict[str, str] = {}
    stem_lines: list[str] = []
    current_opt_key: str | None = None
    opt_pattern = re.compile(r'^([A-Ha-h])[\.、:：\s\)\）]\s*(.*)$')
    inline_opt_pattern = re.compile(r'(?:^|[\s：:，,])([A-Ha-h])[\.、:：\s\)\）]\s*')

    in_options = False
    for line in lines:
        match = opt_pattern.match(line)
        if match:
            in_options = True
            current_opt_key = match.group(1).upper()
            options[current_opt_key] = match.group(2).strip()
        elif in_options and current_opt_key:
            inline_matches = list(inline_opt_pattern.finditer(line))
            if inline_matches:
                parts = inline_opt_pattern.split(line)
                if parts[0].strip() and current_opt_key:
                    options[current_opt_key] += " " + parts[0].strip()
                for i in range(1, len(parts), 2):
                    current_opt_key = parts[i].upper()
                    options[current_opt_key] = parts[i+1].strip() if i+1 < len(parts) else ""
            else:
                options[current_opt_key] += "\n" + line
        else:
            inline_matches = list(inline_opt_pattern.finditer(line))
            if len(inline_matches) >= 2:
                in_options = True
                parts = inline_opt_pattern.split(line)
                if parts[0].strip():
                    stem_lines.append(parts[0].strip())
                for i in range(1, len(parts), 2):
                    current_opt_key = parts[i].upper()
                    options[current_opt_key] = parts[i+1].strip() if i+1 < len(parts) else ""
            else:
                stem_lines.append(line)

    raw_stem = "\n".join(stem_lines).strip()
    # 清理题干开头的题号及题型标记，如 "1. [单选] "，"第1题："，"13.［多选］"
    cleaned_stem = re.sub(r'^(?:第?\d+[题\.\、\s]*\s*)?(?:[\[\［【\(\（](?:单选|多选|判断)[\]\］】\)\）])?\s*', '', raw_stem)

    return ParsedChoiceQuestion(
        stem=cleaned_stem,
        options=options,
        question_type=question_type,
        raw_text=raw_text,
        reverse=reverse,
    )


def match_quiz_bank(
    stem: str,
    options: dict[str, str],
    question_type: str,
    bank_questions: Sequence[dict[str, Any]],
    similarity_threshold: float = 0.85,
) -> dict[str, Any]:
    """在本地题库中匹配题目，并处理选项乱序时的答案映射。

    返回:
        {
            "matched": bool,
            "bank_question": dict | None,
            "mapped_answer": str | None,
            "is_verified": bool,
            "option_mapping": dict[str, str],  # bank_letter -> user_letter
            "score": float,
            "warning": str
        }
    """
    norm_user_stem = normalize_text(stem)
    if not norm_user_stem:
        return {"matched": False, "bank_question": None, "mapped_answer": None,
                "is_verified": False, "option_mapping": {}, "score": 0.0, "warning": "题干为空"}

    norm_user_options = {k.upper(): normalize_text(v) for k, v in options.items()}

    best_match = None
    best_score = 0.0
    best_mapping: dict[str, str] = {}

    for q in bank_questions:
        norm_bank_stem = normalize_text(q.get('question', ''))
        stem_is_exact = (norm_user_stem == norm_bank_stem)
        # 题型不符且非完全相同时跳过；若题干完全一致则优先采纳题库真实题目
        if question_type in ("单选", "多选") and q.get('type') != question_type and not stem_is_exact:
            continue

        # 计算题干相似度
        if stem_is_exact:
            stem_score = 1.0
        else:
            matcher = SequenceMatcher(None, norm_user_stem, norm_bank_stem, autojunk=False)
            stem_score = matcher.ratio()

        if stem_score < 0.75:
            continue

        # 选项匹配与映射：计算题库选项对应用户的哪个选项
        bank_opts = q.get('options', {})
        norm_bank_options = {k.upper(): normalize_text(v) for k, v in bank_opts.items()}

        bank_to_user: dict[str, str] = {}
        matched_opts = 0
        total_bank_opts = len(norm_bank_options)

        for b_key, b_text in norm_bank_options.items():
            for u_key, u_text in norm_user_options.items():
                if not b_text or not u_text:
                    continue
                if b_text == u_text or SequenceMatcher(None, b_text, u_text, autojunk=False).ratio() >= 0.90:
                    bank_to_user[b_key] = u_key
                    matched_opts += 1
                    break

        # 选项匹配率
        opts_score = matched_opts / max(total_bank_opts, 1)
        # 综合分数：题干 70% + 选项 30%
        overall_score = stem_score * 0.7 + opts_score * 0.3

        if overall_score > best_score:
            best_score = overall_score
            best_match = q
            best_mapping = bank_to_user

    if not best_match or best_score < similarity_threshold:
        return {"matched": False, "bank_question": None, "mapped_answer": None,
                "is_verified": False, "option_mapping": {}, "score": best_score, "warning": "未找到高置信度匹配题目"}

    # 检查待核实保护状态
    is_verified = (best_match.get('verification_status') == 'source_reported_confirmed'
                   and best_match.get('correct_answer') is not None)

    bank_raw_answer = best_match.get('correct_answer')
    mapped_answer = None

    if is_verified and bank_raw_answer:
        # 重构答案字母
        mapped_letters = []
        for char in bank_raw_answer.upper():
            if char in best_mapping:
                mapped_letters.append(best_mapping[char])
            else:
                # 选项未完全映射，安全起见不乱猜
                is_verified = False
                break
        if is_verified:
            mapped_answer = "".join(sorted(mapped_letters))

    warning = ""
    if not is_verified:
        if best_match.get('verification_status') == 'pending' or bank_raw_answer is None:
            warning = f"题目（ID: {best_match['id']}）在题库中处于待核实状态，答案为NULL，不可使用历史作答作为标准答案。"
        else:
            warning = "题库选项与用户选项未能完全对应，无法直接映射标准答案。"

    return {
        "matched": True,
        "bank_question": best_match,
        "mapped_answer": mapped_answer,
        "is_verified": is_verified,
        "option_mapping": best_mapping,
        "score": best_score,
        "warning": warning,
    }


_CHOICE_SYSTEM_PROMPT = """你是研究生《工程伦理》课程选择题答题助手。请结合给出的工程伦理课件证据，逐项判断每个选项，再综合确定答案。

必须只输出一个 JSON 对象，不要 Markdown 代码块、前言或后记：
{
  "question_type": "single | multiple | uncertain",
  "selected_options": ["A", "C"],
  "option_analysis": {
    "A": "该项正确/错误的理由",
    "B": "该项正确/错误的理由"
  },
  "explanation": "简短解析",
  "uncertainty_reason": "题型或证据不确定的原因；没有则为空字符串"
}

规则：
1. 先逐项判断所有选项；option_analysis 必须覆盖题目实际存在的每一个选项，不得遗漏。
2. 题型未标注时不要预设单选；只有一个正确选项才返回 single，多个正确选项返回 multiple，无法判断返回 uncertain。
3. 如果题干明确标注单选，selected_options 必须恰好一个；明确多选时可以多个。
4. 特别处理“不正确的是”“不包括”“错误的是”等反向题：先按反向要求判断。
5. selected_options 只能包含题目实际存在的选项字母；不得编造缺失选项。
6. 证据不足或题型歧义时返回 uncertain，并在 uncertainty_reason 说明；不要为了给答案强行认定单选。
7. 只使用实际提供的证据编号；不要输出 PDF 文件名、页码或不存在的 [S#]。
"""



class ChoiceResponseError(ValueError):
    """模型选择题结构化响应不合法；调用方必须安全回退，不能默认 A/单选。"""

    def __init__(self, message: str, *, code: str = "schema"):
        super().__init__(message)
        self.code = code


def _normalize_choice_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"single", "单选", "单选题"}:
        return "单选"
    if text in {"multiple", "multi", "多选", "多选题"}:
        return "多选"
    if text in {"uncertain", "unknown", "不确定", "自动", "auto", ""}:
        return "不确定" if text in {"uncertain", "unknown", "不确定"} else "自动"
    raise ChoiceResponseError(f"未知题型：{value!r}")


def _diagnostic_preview(content: str, settings: Any = None, limit: int = 800) -> str:
    """脱敏诊断预览；绝不记录 API Key。"""
    text = (content or "")[:limit]
    key = getattr(settings, "deepseek_api_key", None) if settings is not None else None
    if key:
        text = text.replace(str(key), "[REDACTED]")
    return text


def _clean_model_json(content: str) -> dict[str, Any]:
    text = (content or "").strip()
    if not text:
        raise ChoiceResponseError("API 返回空内容", code="empty_content")
    # 兼容 ```json ... ``` 以及模型在 JSON 前后添加少量说明。
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*```$', '', text)
    start = text.find('{')
    end = text.rfind('}')
    if start < 0 or end <= start:
        raise ChoiceResponseError("API 未返回 JSON 对象", code="json_not_found")
    try:
        parsed = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ChoiceResponseError(f"JSON 解析失败：{exc.msg}", code="json_parse") from exc
    if not isinstance(parsed, dict):
        raise ChoiceResponseError("JSON 根节点必须是对象", code="json_root")
    return parsed


def _selected_letters(value: Any, actual: set[str]) -> list[str]:
    if isinstance(value, str):
        # 接受 "A"、"AC"、"A,C" 等常见写法；只提取实际存在的单字母。
        raws = re.findall(r"[A-Ha-h]", value)
    elif isinstance(value, list):
        raws = value
    else:
        raise ChoiceResponseError("selected_options 必须是数组或选项字符串", code="selected_type")
    selected: list[str] = []
    for raw in raws:
        if isinstance(raw, dict):
            raw = raw.get("option") or raw.get("letter") or raw.get("key") or ""
        if not isinstance(raw, str):
            raise ChoiceResponseError(f"非法选项值：{raw!r}", code="selected_value")
        # 支持 "A."、"A、"、"A：..."，但只取实际选项字母。
        match = re.match(r"\s*([A-Ha-h])(?:[.、:：\s)]|$)", raw)
        letter = (match.group(1) if match else raw.strip()[:1]).upper()
        if letter not in actual:
            raise ChoiceResponseError(f"选项不存在：{raw!r}", code="selected_missing")
        if letter not in selected:
            selected.append(letter)
    if not selected:
        raise ChoiceResponseError("selected_options 为空", code="selected_empty")
    return selected


def _analysis_reason(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, bool):
        return "该项正确。" if value else "该项错误。"
    if isinstance(value, dict):
        for key in ("reason", "analysis", "explanation", "判断", "理由"):
            if isinstance(value.get(key), str) and value[key].strip():
                return value[key].strip()
        if isinstance(value.get("is_correct"), bool):
            return "该项正确。" if value["is_correct"] else "该项错误。"
    return None


def _normalize_option_analysis(raw: Any, actual: set[str], options: dict[str, str]) -> tuple[dict[str, str], bool]:
    """兼容 dict / list-of-objects / 以选项正文为 key；返回(分析, 是否完整)。"""
    if raw is None:
        return {}, False
    result: dict[str, str] = {}
    text_to_letter: dict[str, str] = {}
    for letter, text in options.items():
        normalized = normalize_text(text)
        if normalized:
            text_to_letter[normalized] = letter.upper()

    def letter_from(raw_key: Any) -> str:
        key = str(raw_key or "").strip()
        letter = key.upper()
        if letter in actual:
            return letter
        match = re.match(r"^\s*([A-Ha-h])(?:[.、:：\s)）]|选项|项|$)", key)
        if match and match.group(1).upper() in actual:
            return match.group(1).upper()
        normalized = normalize_text(key)
        matches = [value for text, value in text_to_letter.items() if normalized and (normalized == text or normalized in text)]
        if len(set(matches)) == 1:
            return matches[0]
        raise ChoiceResponseError(f"option_analysis 包含不存在的选项：{raw_key!r}", code="analysis_option")

    if isinstance(raw, dict):
        for key, value in raw.items():
            letter = letter_from(key)
            reason = _analysis_reason(value)
            if reason is None:
                raise ChoiceResponseError(f"选项 {letter} 缺少判断理由", code="analysis_reason")
            result[letter] = reason
    elif isinstance(raw, list):
        for index, item in enumerate(raw):
            if isinstance(item, str):
                if index >= len(actual):
                    raise ChoiceResponseError("option_analysis 数量超过选项数", code="analysis_type")
                letter = sorted(actual)[index]
                reason = item.strip()
                if not reason:
                    raise ChoiceResponseError(f"选项 {letter} 缺少判断理由", code="analysis_reason")
                result[letter] = reason
                continue
            if not isinstance(item, dict):
                raise ChoiceResponseError("option_analysis 数组元素必须是对象或字符串", code="analysis_type")
            raw_letter = item.get("option") or item.get("letter") or item.get("key")
            if raw_letter is None and index < len(actual):
                raw_letter = sorted(actual)[index]
            letter = letter_from(raw_letter)
            reason = _analysis_reason(item)
            if reason is None:
                raise ChoiceResponseError(f"选项 {letter} 缺少判断理由", code="analysis_reason")
            result[letter] = reason
    else:
        raise ChoiceResponseError("option_analysis 必须是对象或数组", code="analysis_type")
    return result, set(result) == actual


def _parse_model_choice(
    content: str,
    options: dict[str, str],
    explicit_type: str,
) -> dict[str, Any]:
    """兼容真实模型常见 JSON 变体；结构错误与选项错误分别带 code。"""
    parsed = _clean_model_json(content)
    actual = {str(key).upper() for key in options}
    raw_selected = parsed.get("selected_options")
    if raw_selected is None:
        raw_selected = parsed.get("answer")
    if raw_selected is None:
        raise ChoiceResponseError("缺少 selected_options/answer 字段", code="selected_missing_field")
    selected = _selected_letters(raw_selected, actual)

    has_new_fields = any(key in parsed for key in ("question_type", "option_analysis", "selected_options"))
    if has_new_fields:
        raw_type = _normalize_choice_type(parsed.get("question_type"))
    else:
        raw_type = "自动"
        if parsed.get("insufficient_evidence"):
            raw_type = "不确定"

    analysis_raw = parsed.get("option_analysis")
    option_analysis, analysis_complete = _normalize_option_analysis(analysis_raw, actual, options)
    explanation = str(parsed.get("explanation") or parsed.get("analysis") or "").strip()
    uncertainty_reason = str(parsed.get("uncertainty_reason") or "").strip()
    if not analysis_complete:
        missing = sorted(actual - set(option_analysis))
        for letter in missing:
            option_analysis[letter] = "模型未提供该项逐项判断。"
        note = "逐项分析不完整：" + ("、".join(missing) if missing else "模型未提供 option_analysis")
        uncertainty_reason = (uncertainty_reason + "；" if uncertainty_reason else "") + note
        if explicit_type == "自动":
            raw_type = "不确定"

    if explicit_type in ("单选", "多选"):
        question_type = explicit_type
    elif raw_type == "不确定":
        question_type = "不确定"
    elif len(selected) > 1:
        question_type = "多选"
    else:
        question_type = "单选"

    if question_type == "单选" and len(selected) != 1:
        raise ChoiceResponseError("单选题必须恰好一个正确选项", code="explicit_single")
    if question_type == "不确定" and not uncertainty_reason:
        uncertainty_reason = "模型无法确定题型或答案"
    if question_type != "不确定" and not selected:
        raise ChoiceResponseError("selected_options 不能为空", code="selected_empty")

    return {
        "question_type": question_type,
        "selected": "".join(sorted(selected)),
        "option_analysis": option_analysis,
        "explanation": explanation or "模型未提供解析。",
        "uncertainty_reason": uncertainty_reason,
        "analysis_complete": analysis_complete,
    }


def solve_choice_question(
    stem: str,
    options: dict[str, str],
    question_type: str = "自动",
    *,
    bank_db: Path | str = DEFAULT_DB,
    retriever: Any = None,
    settings: Any = None,
    allow_api: bool = False,
    client: DeepSeekClient | None = None,
) -> ChoiceSolution:
    """解答选择题：本地题库 -> RAG检索 -> DeepSeek推理。"""
    if question_type in (None, "", "auto", "AUTO", "自动判断"):
        question_type = "自动"
    if question_type not in ("自动", "单选", "多选"):
        return ChoiceSolution(
            answer=None, source="输入检查", source_detail="未知题型",
            analysis="题型只能是自动判断、单选或多选。", verified=False,
            confidence="low", warning=f"未知题型：{question_type}",
            question_type="自动",
        )
    stem = stem.strip()
    if not stem:
        return ChoiceSolution(
            answer=None, source="输入检查", source_detail="题干为空",
            analysis="请输入完整的题干文字。", verified=False, confidence="low",
            warning="题干不能为空"
        )
    if len(options) < 2:
        return ChoiceSolution(
            answer=None, source="输入检查", source_detail="选项不足",
            analysis="选择题至少需要两个有效选项，无法进行可靠推断。", verified=False, confidence="low",
            warning="至少需要输入两个选项"
        )

    # 第一步：查询本地 SQLite 题库
    bank_match = None
    try:
        bank_questions = query_questions(bank_db)
        match_res = match_quiz_bank(stem, options, question_type, bank_questions)
        if match_res["matched"]:
            bank_match = match_res
            if match_res["is_verified"] and match_res["mapped_answer"]:
                bq = match_res["bank_question"]
                mapped_ans = match_res["mapped_answer"]
                reordered = any(b != u for b, u in match_res["option_mapping"].items())
                reorder_note = "（选项顺序已按题库标准映射重排）" if reordered else ""

                analysis_lines = [
                    f"【题库已核实标准答案】{mapped_ans} {reorder_note}",
                    f"题目出处：第 {bq['chapter']} 章第 {bq['number']} 题（题库ID: {bq['id']}）",
                    "选项对照：",
                ]
                for b_key, u_key in sorted(match_res["option_mapping"].items()):
                    star = " ★正确选项" if b_key in (bq['correct_answer'] or "") else ""
                    analysis_lines.append(f"  - 选项 {u_key}：{options.get(u_key, '')}{star}")

                pdf_pages = []
                for s in bq.get('pdf_sources', []):
                    pdf_pages.append(dict(
                        id=f"题库来源-{bq['id']}",
                        filename=s.get('pdf_filename', ''),
                        page_number=s.get('answer_page', 1),
                        version_label="学习通题库",
                        quality="题库原始PDF速查页",
                        text=f"学习通题库第 {bq['chapter']} 章第 {bq['number']} 题已核实答案",
                    ))

                explicit = question_type if question_type in ("单选", "多选") else "自动"
                bank_type = bq.get('type') if bq.get('type') in ("单选", "多选") else "自动"
                # 题干明确题型优先；与题库冲突时不拿题库答案强行覆盖。
                if explicit != "自动" and bank_type != "自动" and explicit != bank_type:
                    pass
                elif explicit == "单选" and len(mapped_ans) != 1:
                    pass
                elif bank_type == "单选" and len(mapped_ans) != 1:
                    pass
                else:
                    return ChoiceSolution(
                        answer=mapped_ans,
                        source="学习通题库",
                        source_detail=f"学习通章节测试题库（第{bq['chapter']}章第{bq['number']}题 · 已核实）",
                        analysis="\n".join(analysis_lines),
                        verified=True,
                        evidence_context=pdf_pages,
                        confidence="high",
                        bank_id=bq['id'],
                        mapped_from_bank=True,
                        question_type=bank_type if explicit == "自动" else explicit,
                    )
    except Exception as exc:
        # 题库未初始化或读取错误，记录告警但不阻塞后续检索
        pass

    # 第二步：检索课件知识库 (RAG)
    # 只用题干核心概念检索；选项只在模型提示中作为“待判断候选”，
    # 不让干扰项关键词进入检索 query 影响证据召回。
    search_query = stem.strip()
    evidence_hits = []
    evidence_blocks = []
    if retriever is not None:
        try:
            search_res = retriever.search(search_query, mode="expanded", top_k=5)
            for h in getattr(search_res, 'hits', []):
                evidence_hits.append({
                    "id": f"S{h.rank}",
                    "filename": h.page.filename,
                    "page_number": h.page.page_number,
                    "text": h.snippet,
                    "version_label": getattr(h.page, 'version_label', '课件'),
                    "quality": h.page.page_status_label,
                })
                evidence_blocks.append(f"[S{h.rank}] {h.page.filename} 第{h.page.page_number}页：{h.snippet}")
        except Exception:
            evidence_hits = []

    # 第三步：调用 DeepSeek
    is_pending_in_bank = (bank_match and bank_match.get("matched") and not bank_match.get("is_verified"))
    pending_prompt_note = ""
    if is_pending_in_bank:
        bq = bank_match["bank_question"]
        pending_prompt_note = (
            f"注意：此题在题库中状态为【待核实】（ID: {bq['id']}，原题答案为NULL），"
            f"原历史参考作答为 {bq.get('history', [{}])[0].get('user_answer', '无')}，不得轻信历史作答，必须基于课件严格推理论证。"
        )

    # 准备调用模型
    if allow_api and settings and settings.api_enabled and settings.deepseek_configured:
        client = client or DeepSeekClient(settings=settings)
        formatted_options = "\n".join(f"{k}. {v}" for k, v in sorted(options.items()))
        type_label = question_type if question_type != "自动" else "自动判断（不要预设单选）"
        user_prompt_lines = [
            f"题目类型：{type_label}",
            f"题干：{stem}",
            "选项列表：",
            formatted_options,
        ]
        if re.search(r'不正确|不包括|不属于|错误的是|不恰当|不正确|有误|错误', stem):
            user_prompt_lines.append(
                "注意：这是反向选择题，请按“不正确/不包括/错误”的要求逐项判断。"
            )
        if pending_prompt_note:
            user_prompt_lines.append(pending_prompt_note)

        if evidence_blocks:
            user_prompt_lines.append("\n相关课件检索证据如下：")
            user_prompt_lines.append("\n\n".join(evidence_blocks))
        else:
            user_prompt_lines.append("\n未检索到直接相关的课件证据，请基于工程伦理通用学术知识进行专业推断。")

        user_prompt_lines.append("\n请直接返回规定的 JSON 对象：")

        messages = [
            {"role": "system", "content": _CHOICE_SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(user_prompt_lines)},
        ]

        explicit_type = question_type if question_type in ("单选", "多选") else "自动"
        raw_content = ""
        last_model = None
        try:
            chat_result = client.chat(messages, temperature=0.1, max_tokens=700, allow_api=True)
            raw_content = chat_result.content
            last_model = chat_result.model
            result = _parse_model_choice(chat_result.content, options, explicit_type)
            selected = result["selected"]
            result_type = result["question_type"]
            option_analysis = result["option_analysis"]
            explanation = result["explanation"]
            uncertainty_reason = result["uncertainty_reason"]
            analysis_complete = result.get("analysis_complete", True)

            if is_pending_in_bank:
                source_type = "学习通待核实题目（课件检索 + AI推断）"
                source_detail = f"题库待核实题（ID: {bank_match['bank_question']['id']}）· 经课件与DeepSeek综合论证"
            elif result_type == "不确定":
                source_type = "DeepSeek推断（题型不确定）"
                source_detail = "题型或证据存在歧义；以下为建议答案，需人工复核。"
            elif evidence_blocks:
                source_type = "PPT课件检索 + DeepSeek推断"
                source_detail = "基于课件检索材料与逐项判断综合推断"
            else:
                source_type = "DeepSeek通用知识推断"
                source_detail = "课件未提供直接依据，基于工程伦理通用规范推断"

            analysis_lines = [explanation]
            if option_analysis:
                analysis_lines.append("逐项判断：")
                for letter in sorted(option_analysis):
                    analysis_lines.append(f"- {letter}：{option_analysis[letter]}")

            warning = "AI推断答案未经人工核验，请参考解析与课件证据复核。"
            if is_pending_in_bank:
                warning = "本题题库答案未公开；此处答案为AI推断结果，未采用历史学生作答。"
            if result_type == "不确定":
                warning = "题型不确定：" + (uncertainty_reason or "证据或题型存在歧义") + "；以下为建议答案，请人工复核。"
            elif not analysis_complete:
                warning += " 逐项分析不完整，请人工复核所有选项。"

            return ChoiceSolution(
                answer=selected,
                source=source_type,
                source_detail=source_detail,
                analysis="\n".join(analysis_lines),
                verified=False,
                evidence_context=evidence_hits,
                confidence="low" if result_type == "不确定" else "medium",
                warning=warning,
                bank_id=bank_match['bank_question']['id'] if is_pending_in_bank else None,
                question_type=result_type,
                option_analysis=option_analysis,
                uncertainty_reason=uncertainty_reason,
                diagnostic={
                    "error_type": None,
                    "model": chat_result.model,
                    "raw_preview": _diagnostic_preview(raw_content, settings),
                },
            )
        except ChoiceResponseError as exc:
            logger.warning("choice_response_invalid type=%s", exc.code)
            return ChoiceSolution(
                answer=None,
                source="课件离线检索（AI响应无效）",
                source_detail=f"模型响应校验失败：{exc.code}",
                analysis="模型没有返回可校验的选择题答案；未默认选 A，也未强制按单选处理。请结合下方证据自行判断。",
                verified=False,
                evidence_context=evidence_hits,
                confidence="low",
                warning=f"AI响应校验失败（{exc.code}）：{exc}",
                question_type=explicit_type,
                diagnostic={
                    "error_type": exc.code,
                    "model": last_model or getattr(settings, "deepseek_model", None),
                    "raw_preview": _diagnostic_preview(raw_content, settings),
                },
            )
        except DeepSeekError as exc:
            logger.warning("choice_api_error type=%s", exc.code)
            return ChoiceSolution(
                answer=None,
                source="课件离线检索（API未成功）",
                source_detail=f"DeepSeek API 调用失败：{exc.code}",
                analysis="模型调用未能生成答案，但已检索到相关课件片段，请结合下方证据自行判断。",
                verified=False,
                evidence_context=evidence_hits,
                confidence="low",
                warning=f"API推断失败（{exc.code}）：{exc}",
                question_type=explicit_type,
                diagnostic={
                    "error_type": exc.code,
                    "model": getattr(settings, "deepseek_model", None),
                    "raw_preview": _diagnostic_preview(raw_content, settings),
                },
            )

    # 未开启 API 或未配置
    reason_note = "未开启 AI 推理开关或未配置 API 密钥。"
    if is_pending_in_bank:
        reason_note = f"匹配到题库待核实题目（ID: {bank_match['bank_question']['id']}），但当前未开启AI，无法进行模型推理。"

    return ChoiceSolution(
        answer=None,
        source="课件离线检索",
        source_detail="离线模式检索到相关课件线索",
        analysis=f"{reason_note} 请开启侧边栏 AI 开关获取智能答案推断，或参考下方课件证据解答。",
        verified=False,
        evidence_context=evidence_hits,
        confidence="low",
        warning=reason_note,
        bank_id=bank_match['bank_question']['id'] if is_pending_in_bank else None,
    )


def solve_choice_raw_text(
    raw_text: str,
    *,
    question_type: str | None = None,
    bank_db: Path | str = DEFAULT_DB,
    retriever: Any = None,
    settings: Any = None,
    allow_api: bool = False,
    client: DeepSeekClient | None = None,
) -> ChoiceSolution:
    """直接基于原始题目文本（包含题干和选项）进行选择题解答。"""
    raw_text = (raw_text or "").strip()
    if not raw_text:
        return ChoiceSolution(
            answer=None, source="输入检查", source_detail="未输入内容",
            analysis="请输入或拍摄题目内容（包含题干和选项）。", verified=False, confidence="low",
            warning="题目内容为空"
        )
    parsed = parse_choice_text(raw_text)
    if not parsed.stem.strip():
        return ChoiceSolution(
            answer=None, source="输入检查", source_detail="题干为空",
            analysis="未能识别或提取到有效题干文字，请检查题目文字格式。", verified=False, confidence="low",
            warning="题干内容为空"
        )
    if len(parsed.options) < 2:
        return ChoiceSolution(
            answer=None, source="输入检查", source_detail="选项不足",
            analysis="未识别到至少两个有效选项（例如：A. ... B. ...），无法进行选择题解答，请补充选项。", verified=False, confidence="low",
            warning="至少需要两个选项"
        )
    selected_type = question_type or parsed.question_type
    if selected_type in ("自动", "自动判断", None, ""):
        selected_type = parsed.question_type
    return solve_choice_question(
        stem=parsed.stem,
        options=parsed.options,
        question_type=selected_type,
        bank_db=bank_db,
        retriever=retriever,
        settings=settings,
        allow_api=allow_api,
        client=client,
    )
