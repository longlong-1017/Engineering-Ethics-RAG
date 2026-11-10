"""命令行入口：统计、检索和问答。

示例：
    python -m src.cli stats
    python -m src.cli search "工程风险" --mode strict
    python -m src.cli ask "工程风险的技术因素有哪些？" --mode strict
    python -m src.cli ask "..." --provider deepseek --allow-api
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.config import Settings
from src.corpus import CorpusError, format_stats, load_corpus
from src.qa import (
    PROVIDER_AUTO,
    PROVIDER_DEEPSEEK,
    PROVIDER_LOCAL,
    QA_MODE_GENERAL,
    QA_MODE_HYBRID,
    QA_MODE_RAG,
    AnswerEngine,
)
from src.retriever import MODE_EXPANDED, MODE_STRICT, Retriever


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="工程伦理本地 RAG 命令行工具")
    parser.add_argument("--data-dir", type=Path, help="processed_v3 JSON 目录")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("stats", help="显示知识库覆盖与审核统计")

    search_parser = subparsers.add_parser("search", help="仅检索，不生成答案")
    search_parser.add_argument("query", help="检索问题或关键词")
    search_parser.add_argument(
        "--mode",
        choices=(MODE_STRICT, MODE_EXPANDED),
        default=MODE_STRICT,
        help="strict=仅 81 个严格合格页；expanded=590 个有文本页（含未审核）",
    )
    search_parser.add_argument("--top-k", type=int, default=6, help="返回条数")
    search_parser.add_argument("--json", action="store_true", help="输出 JSON")

    ask_parser = subparsers.add_parser("ask", help="检索并生成回答")
    ask_parser.add_argument("query", help="自然语言问题")
    ask_parser.add_argument(
        "--mode",
        choices=(MODE_STRICT, MODE_EXPANDED),
        default=MODE_STRICT,
        help="strict=仅 81 个严格合格页；expanded=590 个有文本页（含未审核）",
    )
    ask_parser.add_argument("--top-k", type=int, default=6, help="证据页数")
    ask_parser.add_argument(
        "--qa-mode",
        choices=(QA_MODE_HYBRID, QA_MODE_RAG, QA_MODE_GENERAL),
        default=QA_MODE_HYBRID,
        help="hybrid=严格→扩展→通用知识；rag=仅严格课件；general=直接通用问答",
    )
    ask_parser.add_argument(
        "--provider",
        choices=(PROVIDER_AUTO, PROVIDER_LOCAL, PROVIDER_DEEPSEEK),
        default=PROVIDER_AUTO,
        help="auto=有密钥且授权时用 DeepSeek，否则离线摘录",
    )
    ask_parser.add_argument(
        "--allow-api",
        action="store_true",
        help="明确允许调用 DeepSeek API（可能产生费用；默认不调用）",
    )
    ask_parser.add_argument("--json", action="store_true", help="输出 JSON")
    return parser


def _print_search(response, as_json: bool) -> None:
    if as_json:
        print(json.dumps(response.to_dict(), ensure_ascii=False, indent=2))
        return
    print(f"查询：{response.query}")
    print(f"范围：{response.mode}（池大小 {response.pool_size}）")
    print(f"检索词：{' / '.join(response.terms) or '（无可检索词）'}")
    print(
        f"结果：{len(response.hits)} 条；低相关过滤 {response.dropped_low_relevance}；"
        f"重复合并 {response.duplicates_merged}"
    )
    if not response.hits:
        print("没有找到匹配页面。")
        return
    for hit in response.hits:
        print(f"\n[S{hit.rank}] {hit.citation}")
        print(f"证据状态：{hit.review_label}")
        print(
            f"评分：{hit.score:.2f}（BM25 {hit.bm25_score:.2f}，覆盖率 {hit.coverage:.0%}，"
            f"短语命中：{'是' if hit.phrase_match else '否'}）"
        )
        if hit.duplicate_count:
            print(f"相同正文的其他来源：{hit.duplicate_count} 处")
        print(f"摘要：{hit.snippet}")


def _print_answer(answer, as_json: bool) -> None:
    if as_json:
        print(json.dumps(answer.to_dict(), ensure_ascii=False, indent=2))
        return
    print(f"状态：{answer.status}")
    print(f"生成方式：{answer.provider_label}")
    if answer.api_outcome not in {'not_requested', 'accepted'}:
        print(f"API状态：{answer.api_outcome}｜{answer.api_reason}")
    if answer.usage:
        print(f"token用量：{answer.usage}")
    if answer.api_accounting:
        accounting = answer.api_accounting
        if accounting.get('cost_status') == 'estimated':
            print(f"费用估算：¥{accounting.get('estimated_cny')}（本地估算，不是账单）")
        else:
            print("费用估算：未知；已保留保护预留，不当作零费用。")
    for warning in answer.warnings:
        print(f"提示：{warning}")
    print("\n" + answer.answer)
    if answer.citations and answer.provider != PROVIDER_LOCAL:
        print("\n--- 引用证据 ---")
        for hit in answer.citations:
            print(f"[S{hit.rank}] {hit.citation}｜{hit.review_label}")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env(data_dir=args.data_dir)
        corpus = load_corpus(settings.data_dir)
    except CorpusError as exc:
        print(f"知识库加载失败：{exc}", file=sys.stderr)
        return 1

    if args.command == "stats":
        print(format_stats(corpus.stats()))
        return 0

    retriever = Retriever(corpus)
    if args.command == "search":
        response = retriever.search(args.query, mode=args.mode, top_k=args.top_k)
        _print_search(response, args.json)
        return 0

    if args.allow_api and args.provider != PROVIDER_LOCAL:
        print(f"费用提示：API可能计费（含超时/失败/回退）；UTC日估算预算{settings.daily_budget_cny}元（非账单），不限制次数，输出上限{settings.max_output_tokens} token；不是金额封顶。总开关仍须开启，不会自动重试。",file=sys.stderr)
    engine = AnswerEngine(retriever, settings=settings)
    answer = engine.answer(
        args.query,
        mode=args.mode,
        top_k=args.top_k,
        provider=args.provider,
        allow_api=args.allow_api,
        qa_mode=args.qa_mode,
    )
    _print_answer(answer, args.json)
    return 0 if not answer.is_error else 1


if __name__ == "__main__":
    raise SystemExit(main())
