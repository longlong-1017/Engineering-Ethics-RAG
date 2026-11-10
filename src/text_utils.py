"""中文文本规范化、分词与句子切分。

检索使用 jieba 的搜索模式分词；未安装 jieba 时退化为中文二元组，
保证项目在最小依赖下仍可运行。
"""

from __future__ import annotations

import logging
import re
import unicodedata
from functools import lru_cache

try:  # jieba 为推荐依赖；缺失时使用内置退化分词
    import jieba

    jieba.setLogLevel(logging.WARNING)
except ImportError:  # pragma: no cover - 仅在缺少可选依赖时触发
    jieba = None


_CJK_RANGE = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_CJK_RE = re.compile(f"[{_CJK_RANGE}]")
_TOKEN_RE = re.compile(f"[{_CJK_RANGE}]+|[a-z0-9]+", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(f"[^0-9a-z{_CJK_RANGE}]+", re.IGNORECASE)
# 只过滤问句和语法功能词，不过滤工程伦理领域词。
STOPWORDS = frozenset(
    """
    的 了 吗 呢 吧 啊 呀 哦 是 有 在 和 与 及 或 而 但 也 都 就 又 还 被 把
    对 从 到 于 为 以 之 其 这 那 这个 那个 这些 那些 一个 一种 一些 什么
    怎么 怎样 如何 为什么 为何 哪些 哪个 多少 是否 能否 可否 请问 请 简述
    简要 说明 解释 介绍 概述 分析 论述 谈谈 评价 关于 以及 其中 可以 能够
    需要 应该 应当 可能 一般 主要 相关 方面 问题 内容 课程 课件 老师 我们
    你 我 他 她 它 他们 她们 它们 中 上 下 内 外 时 者 所 等 更 最 很 非常
    中应 中如 时应 时如 并可 并应 若 则 即 且 因 由 让 使 给 跟 同 并 很
    """.split()
)


def normalize_text(text: str) -> str:
    """NFKC 规范化、统一大小写并压缩空白。"""
    if not isinstance(text, str):
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("\u3000", " ").replace("\xa0", " ")
    normalized = normalized.casefold()
    return _SPACE_RE.sub(" ", normalized).strip()


def compact_text(text: str) -> str:
    """去掉空白和标点，仅保留中文、拉丁字母与数字，用于短语匹配与去重。"""
    return _NON_WORD_RE.sub("", normalize_text(text))


def contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _fallback_tokens(text: str) -> list[str]:
    """无 jieba 时的退化分词：拉丁词 + 中文二元组。"""
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(text):
        piece = match.group(0)
        if _CJK_RE.search(piece):
            if len(piece) == 1:
                tokens.append(piece)
            else:
                tokens.extend(piece[index : index + 2] for index in range(len(piece) - 1))
        else:
            tokens.append(piece)
    return tokens


@lru_cache(maxsize=4096)
def tokenize(text: str, for_query: bool = False) -> tuple[str, ...]:
    """把文本切成可检索词项。

    - 使用 jieba 搜索模式，保留长词及其子词，提升中文召回；
    - 过滤纯标点、空白、单字功能词；
    - for_query=True 时额外过滤疑问词和口语化提问词。
    """
    normalized = normalize_text(text)
    if not normalized:
        return ()

    raw_tokens = (
        list(jieba.cut_for_search(normalized)) if jieba is not None else _fallback_tokens(normalized)
    )
    tokens: list[str] = []
    for raw in raw_tokens:
        piece = raw.strip()
        if not piece:
            continue
        for token in _TOKEN_RE.findall(piece):
            token = token.casefold()
            if not token:
                continue
            if _CJK_RE.search(token):
                if len(token) < 2:
                    continue
            elif len(token) < 2 and not token.isdigit():
                continue
            if token in STOPWORDS:
                continue
            tokens.append(token)

    if for_query:
        # 去掉重复词项，保留首次出现顺序。
        tokens = list(dict.fromkeys(tokens))
    return tuple(tokens)


def query_terms(question: str) -> tuple[str, ...]:
    """提取问题中的检索词；若过滤后为空则退回原始分词结果。"""
    terms = tokenize(question, for_query=True)
    if terms:
        return terms
    return tuple(dict.fromkeys(tokenize(question, for_query=False)))


_QUESTION_FILLERS = tuple(
    sorted(
        {
            "什么是",
            "是什么",
            "为什么",
            "怎么样",
            "怎么",
            "怎样",
            "如何",
            "有哪些",
            "哪些",
            "哪个",
            "多少",
            "是否",
            "能否",
            "请问",
            "简述",
            "简要",
            "说明",
            "解释",
            "介绍",
            "概述",
            "论述",
            "谈谈",
            "关于",
            "以及",
            "区别",
            "可以",
            "能够",
            "需要",
            "应该",
            "应当",
            "中应",
            "中如",
            "时应",
            "时如",
            "的",
            "与",
            "和",
            "及",
            "或",
            "在",
            "是",
            "吗",
            "呢",
        },
        key=len,
        reverse=True,
    )
)


def query_phrases(question: str) -> tuple[str, ...]:
    """从自然语言问题中提取可用于精确短语匹配的候选片段。

    例如“什么是工程伦理？”→“工程伦理”；“责任伦理与法律责任的区别”→
    “责任伦理”“法律责任”。这些片段只用于短语加分，不替代分词。
    """
    normalized = normalize_text(question)
    if not normalized:
        return ()
    if not contains_cjk(normalized):
        pieces = [piece for piece in re.split(r"[^0-9a-z]+", normalized) if len(piece) >= 2]
        return tuple(dict.fromkeys(pieces))

    text = _NON_WORD_RE.sub("|", normalized)
    for filler in _QUESTION_FILLERS:
        text = text.replace(filler, "|")
    phrases: list[str] = []
    for piece in text.split("|"):
        piece = piece.strip()
        if len(piece) < 2:
            continue
        phrases.append(piece)
        # 较长片段补充 4 字滑动窗口，兼顾“工程伦理概念”这类组合。
        if len(piece) >= 6:
            phrases.extend(piece[index : index + 4] for index in range(len(piece) - 3))
    return tuple(dict.fromkeys(phrases))[:16]


_DEFINITION_QUESTION_RE = re.compile(r"什么是|何为|何谓|是什么|的定义|的概念|的含义|的内涵")


def is_definition_question(question: str) -> bool:
    text = normalize_text(question)
    # “是什么”也常用于列举、案例字段和原因，不能一律要求“X是指”的定义句。
    if re.search(r"哪些|哪[一二三四五六七八九十0-9]*[种类项层]|[两二三四五六七八九十0-9]+种|方式|思路|原因|动机|时间|地点|后果|用途|结果|参数|多少|如何|怎么|为什么|应怎样", text):
        return False
    return bool(_DEFINITION_QUESTION_RE.search(text) or re.search(r"指什么[？?]?$",text))


def has_direct_definition(question: str, text: str) -> bool:
    """检查页面是否直接定义问题中的核心概念。

    只接受“工程伦理是……”“工程伦理，即……”这类紧邻结构；
    “工程伦理规范是指……”不会被误判为对“工程伦理”的定义。
    """
    if not is_definition_question(question):
        return False
    phrases = [
        compact_phrase
        for phrase in query_phrases(question)
        if len(compact_phrase := compact_text(phrase)) >= 4
    ]
    if not phrases:
        return False
    for sentence in [*split_sentences(text), *text.splitlines()]:
        compact_sentence = compact_text(sentence)
        for compact_phrase in phrases:
            # 句首、“……的工程伦理是……”或“所谓工程伦理是……”。
            # 不匹配“制药工程伦理是……”，避免把限定领域当成一般定义。
            pattern = re.compile(
                r"(?:^|的|所谓)"
                + re.escape(compact_phrase)
                + r"(?:的)?(?:概念|定义|含义|内涵)?(?:是指|指的是|是|即|就是|定义为)"
            )
            if pattern.search(compact_sentence):
                return True
    return False


_BLOCK_START_RE = re.compile(
    r"^\s*(?:[0-9０-９]+(?:[、)）]|[.．](?![0-9０-９]))|[一二三四五六七八九十]+[、.．)）]|"
    r"[•·▪●○◆◇\-—]|第[一二三四五六七八九十]+[章节讲]|"
    r"[（(][0-9一二三四五六七八九十]+[)）])"
)
_SENTENCE_END_RE = re.compile(r"[。！？!?]+")


def _looks_like_heading(line: str) -> bool:
    return (
        bool(_BLOCK_START_RE.match(line))
        and len(compact_text(line)) < 30
        and not any(mark in line for mark in "，,。！？；;：:")
    )


def looks_like_block_start(text: str) -> bool:
    """判断一行是否像编号项、项目符号或章节标题的开头。"""
    return bool(_BLOCK_START_RE.match(text or ""))


_OUTLINE_MARKERS = ("课程目录", "本章目录", "课程内容", "教学内容", "主要内容", "目录")


def is_outline_page(text: str) -> bool:
    """识别目录/提纲页，避免把章节列表当成具体答案。"""
    compact = compact_text(text)
    if any(marker in compact[:120] for marker in _OUTLINE_MARKERS):
        return True
    section_numbers = len(re.findall(r"[0-9]+\.[0-9]+", text or ""))
    numbered_items = len(re.findall(r"[1-9][、.]", text or ""))
    # 编号数量不能区分目录与实质清单：含解释句/长段落的列表不是目录。
    paragraphs = join_wrapped_lines(text)
    substantive = any(re.search(r"是指|包括|比如|例如|由于|因此|导致|必须|应当|原则：|原则:",p) for p in paragraphs)
    return (section_numbers >= 3 or numbered_items >= 4) and len(compact) < 420 and not substantive


def join_wrapped_lines(text: str) -> list[str]:
    """合并 PDF 自动换行，保留标题、编号项和空行形成的段落边界。

    PDF 文本通常在句子中间插入换行。直接按换行切句会把一句完整定义拆成
    多个碎片，因此这里先识别编号项、项目符号和句末标点，再决定是否合并。
    """
    if not text:
        return []
    lines = [
        _SPACE_RE.sub(" ", line).strip()
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    paragraphs: list[str] = []
    buffer = ""
    for line in lines:
        if not line:
            # PDF 中常见“每行之间夹空行”的排版；空行本身不作为硬分段，
            # 是否分段由上一行句末标点和下一行编号/项目符号决定。
            continue
        if not buffer:
            if _looks_like_heading(line):
                paragraphs.append(line)
                continue
            buffer = line
            continue
        if _looks_like_heading(line):
            paragraphs.append(buffer)
            paragraphs.append(line)
            buffer = ""
            continue
        starts_block = bool(_BLOCK_START_RE.match(line))
        previous_ends = buffer.endswith(("。", "！", "？", "!", "?", "；", ";", "：", ":"))
        if starts_block or previous_ends:
            paragraphs.append(buffer)
            buffer = line
            continue
        if _CJK_RE.search(buffer[-1:]) or _CJK_RE.search(line[:1]):
            buffer += line
        else:
            buffer += " " + line
    if buffer:
        paragraphs.append(buffer)
    return paragraphs


def split_sentences(text: str) -> list[str]:
    """按 PDF 段落和中文句末标点切句，保留句末标点。

    不按分号切分，避免把“①拒绝；②放弃；③离职……”这类完整列举拆碎。
    """
    sentences: list[str] = []
    for paragraph in join_wrapped_lines(text):
        start = 0
        for match in _SENTENCE_END_RE.finditer(paragraph):
            sentence = paragraph[start : match.end()].strip()
            if sentence:
                sentences.append(sentence)
            start = match.end()
        tail = paragraph[start:].strip()
        if tail:
            sentences.append(tail)
    return sentences


def shorten(text: str, limit: int = 360) -> str:
    """压缩空白并截断到指定长度，保留省略号。"""
    flat = _SPACE_RE.sub(" ", text or "").strip()
    if len(flat) <= limit:
        return flat
    return flat[: max(0, limit - 1)].rstrip() + "…"
