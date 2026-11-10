"""第二阶段验收：运行 30 题 × 严格/扩展，并做只读证据核对。

不调用任何付费 API；不修改 PDF 或 processed_v3。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(PROJECT_ROOT))

from src.config import PROJECT_ROOT
from src.corpus import Corpus, Page, load_corpus
from src.qa import AnswerEngine
from src.retriever import MODE_EXPANDED, MODE_STRICT, Retriever
from src.text_utils import compact_text, split_sentences


DEFAULT_QUESTIONS = PROJECT_ROOT / "reports/phase2_acceptance/questions.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "reports/phase2_acceptance"
PDF_DIR = PROJECT_ROOT / "data/pdfs"


@dataclass
class PdfText:
    text: str
    page_exists: bool
    error: str = ""


class PdfCache:
    def __init__(self, pdf_dir: Path):
        self.pdf_dir = pdf_dir
        self._documents: dict[str, Any] = {}

    def get(self, filename: str, page_number: int) -> PdfText:
        path = self.pdf_dir / filename
        if not path.is_file():
            return PdfText("", False, "PDF 文件不存在")
        document = self._documents.get(filename)
        if document is None:
            try:
                document = pymupdf.open(path)
            except Exception as exc:  # pragma: no cover - 真实 PDF 防御
                return PdfText("", False, f"PDF 打开失败：{type(exc).__name__}: {exc}")
            self._documents[filename] = document
        if page_number < 1 or page_number > len(document):
            return PdfText("", False, f"PDF 无第 {page_number} 页（共 {len(document)} 页）")
        try:
            return PdfText(document[page_number - 1].get_text("text", sort=True), True)
        except Exception as exc:  # pragma: no cover
            return PdfText("", True, f"页面读取失败：{type(exc).__name__}: {exc}")

    def close(self) -> None:
        for document in self._documents.values():
            document.close()
        self._documents.clear()


def fact_coverage(text: str, expected_points: list[list[str]]) -> tuple[float, list[int]]:
    compact = compact_text(text)
    matched: list[int] = []
    for index, alternatives in enumerate(expected_points):
        if any(compact_text(alternative) and compact_text(alternative) in compact for alternative in alternatives):
            matched.append(index)
    return (len(matched) / len(expected_points) if expected_points else 1.0, matched)


def json_pdf_relation(json_text: str, pdf_text: str) -> str:
    json_compact = compact_text(json_text)
    pdf_compact = compact_text(pdf_text)
    if not json_compact and not pdf_compact:
        return "both_empty"
    if json_compact == pdf_compact:
        return "exact"
    if Counter(json_compact) == Counter(pdf_compact):
        return "reorder"
    if json_compact and json_compact in pdf_compact:
        return "json_subset"
    if pdf_compact and pdf_compact in json_compact:
        return "pdf_subset"
    return "mismatch"


def snippet_present(snippet: str, text: str) -> bool:
    compact_snippet = compact_text(re.sub(r"[…\.]{1,3}$", "", snippet)).replace("...", "")
    compact_text_value = compact_text(text)
    if not compact_snippet:
        return False
    if compact_snippet in compact_text_value:
        return True
    for sentence in split_sentences(snippet):
        sentence_compact = compact_text(sentence)
        if len(sentence_compact) >= 8 and sentence_compact in compact_text_value:
            return True
    return False


def verify_hit(
    hit,
    page_map: dict[tuple[str, int], Page],
    pdf_cache: PdfCache,
) -> dict[str, Any]:
    key = (hit.page.filename, hit.page.page_number)
    page = page_map.get(key)
    pdf = pdf_cache.get(*key)
    if page is None:
        return {
            "key": f"{key[0]}#p{key[1]}",
            "page_status": "missing_json_page",
            "json_pdf_relation": "missing_json_page",
            "snippet_in_json": False,
            "snippet_in_pdf": False,
            "pdf_page_exists": pdf.page_exists,
            "pdf_error": pdf.error,
            "verification": "unverified",
        }
    relation = json_pdf_relation(page.text, pdf.text)
    snippet_in_json = snippet_present(hit.snippet, page.text)
    snippet_in_pdf = snippet_present(hit.snippet, pdf.text)
    if not pdf.page_exists:
        verification = "unverified_pdf_missing"
    elif relation == "exact" and snippet_in_pdf:
        verification = "verified_exact"
    elif relation == "reorder" and snippet_in_json:
        verification = "verified_reorder"
    elif relation in {"json_subset", "pdf_subset"} and (snippet_in_json or snippet_in_pdf):
        verification = "partial_text_match"
    elif snippet_in_json and snippet_in_pdf:
        verification = "verified_snippet"
    else:
        verification = "unverified"
    return {
        "key": f"{key[0]}#p{key[1]}",
        "filename": key[0],
        "page_number": key[1],
        "review_category": page.review_category,
        "evidence_status": page.evidence_status,
        "review_label": page.review_label,
        "page_status": page.page_status,
        "page_status_label": page.page_status_label,
        "page_strict_eligible": page.strict_eligible,
        "json_pdf_relation": relation,
        "snippet_in_json": snippet_in_json,
        "snippet_in_pdf": snippet_in_pdf,
        "pdf_page_exists": pdf.page_exists,
        "pdf_error": pdf.error,
        "verification": verification,
        "snippet": hit.snippet,
        "rank": hit.rank,
        "score": round(hit.score, 4),
        "coverage": round(hit.coverage, 4),
        "matched_terms": list(hit.matched_terms),
        "review_note": page.review_note,
    }


def cited_ranks(answer_text: str) -> list[int]:
    return sorted({int(number) for number in re.findall(r"\[S(\d+)\]", answer_text)})


def make_run(
    question: dict[str, Any],
    mode: str,
    corpus: Corpus,
    retriever: Retriever,
    engine: AnswerEngine,
    pdf_cache: PdfCache,
    page_map: dict[tuple[str, int], Page],
    top_k: int = 6,
) -> dict[str, Any]:
    answer = engine.answer(
        question["question"],
        mode=mode,
        top_k=top_k,
        provider="local",
        allow_api=False,
    )
    expected = question["expected_points"]
    cited = cited_ranks(answer.answer)
    hit_by_rank = {hit.rank: hit for hit in answer.search.hits}
    cited_hits = [hit_by_rank[rank] for rank in cited if rank in hit_by_rank]
    hit_verifications = [
        verify_hit(hit, page_map, pdf_cache) for hit in answer.search.hits
    ]
    cited_verifications = [
        verify_hit(hit, page_map, pdf_cache) for hit in cited_hits
    ]
    gold_keys = {
        (gold["filename"], gold["page_number"]) for gold in question["gold_pages"]
    }
    gold_in_pool_keys = set()
    for gold in question["gold_pages"]:
        page = page_map.get((gold["filename"], gold["page_number"]))
        if page is None:
            continue
        if mode == MODE_STRICT and page.strict_eligible:
            gold_in_pool_keys.add((gold["filename"], gold["page_number"]))
        if mode == MODE_EXPANDED and page.text.strip():
            gold_in_pool_keys.add((gold["filename"], gold["page_number"]))
    gold_ranks = [
        hit.rank
        for hit in answer.search.hits
        if (hit.page.filename, hit.page.page_number) in gold_keys
    ]
    gold_text = "\n".join(
        page_map[(gold["filename"], gold["page_number"])].text
        for gold in question["gold_pages"]
        if (gold["filename"], gold["page_number"]) in page_map
    )
    gold_coverage, gold_matched = fact_coverage(gold_text, expected)
    answer_coverage, answer_matched = fact_coverage(answer.answer, expected)
    cited_text = "\n".join(hit.page.text for hit in cited_hits)
    cited_coverage, cited_matched = fact_coverage(cited_text, expected)
    gold_risks = sorted(
        {
            (page_map[(gold["filename"], gold["page_number"])].evidence_status)
            for gold in question["gold_pages"]
            if (gold["filename"], gold["page_number"]) in page_map
        }
    )
    return {
        "id": question["id"],
        "type": question["type"],
        "question": question["question"],
        "notes": question.get("notes", ""),
        "expected_points": expected,
        "gold_pages": question["gold_pages"],
        "context_pages": question.get("context_pages", []),
        "mode": mode,
        "status": answer.status,
        "provider": answer.provider,
        "answer": answer.answer,
        "warnings": list(answer.warnings),
        "search": answer.search.to_dict(),
        "gold_in_pool": bool(gold_in_pool_keys),
        "gold_pool_keys": sorted(gold_in_pool_keys),
        "gold_ranks": gold_ranks,
        "retrieval_hit_top1": bool(gold_ranks and gold_ranks[0] == 1),
        "retrieval_hit_topk": bool(gold_ranks),
        "gold_fact_coverage": round(gold_coverage, 4),
        "gold_fact_matched": gold_matched,
        "answer_fact_coverage": round(answer_coverage, 4),
        "answer_fact_matched": answer_matched,
        "cited_ranks": cited,
        "cited_fact_coverage": round(cited_coverage, 4),
        "cited_fact_matched": cited_matched,
        "cited_keys": [
            f"{hit.page.filename}#p{hit.page.page_number}" for hit in cited_hits
        ],
        "cited_verifications": cited_verifications,
        "hit_verifications": hit_verifications,
        "gold_risks": gold_risks,
        "has_unreviewed_citation": any(
            verification.get("evidence_status") == "unreviewed"
            for verification in cited_verifications
        ),
        "has_hold_citation": any(
            verification.get("evidence_status") == "reviewed_hold"
            for verification in cited_verifications
        ),
    }


def write_review_packet(results: list[dict[str, Any]], path: Path) -> None:
    lines = [
        "# 第二阶段验收：逐题原始结果（自动生成）",
        "",
        "本文件只展示系统实际输出与自动核对结果，不包含人工评分。",
        "评分标签见 `labels.json`，统计见 `acceptance_report.md`。",
        "",
    ]
    for result in results:
        lines.extend(
            [
                f"## {result['id']} [{result['type']}] {result['question']}",
                "",
                f"- 模式：`{result['mode']}`",
                f"- 状态：`{result['status']}`",
                f"- 严格/扩展池内存在 gold：`{result['gold_in_pool']}`；gold 排名：`{result['gold_ranks'] or '未命中'}`",
                f"- gold 原文事实覆盖：{result['gold_fact_coverage']:.0%}；答案事实覆盖：{result['answer_fact_coverage']:.0%}；引用页事实覆盖：{result['cited_fact_coverage']:.0%}",
                f"- 题目备注：{result['notes']}",
                "",
                "**系统答案：**",
                "",
                "```text",
                result["answer"],
                "```",
                "",
            ]
        )
        if result["warnings"]:
            lines.append("**警告：**")
            lines.extend(f"- {warning}" for warning in result["warnings"])
            lines.append("")
        lines.append("**引用页核对：**")
        if not result["cited_verifications"]:
            lines.append("- 无引用")
        for verification in result["cited_verifications"]:
            lines.append(
                f"- [S{verification['rank']}] {verification['filename']} p{verification['page_number']}｜"
                f"{verification['review_label']}｜{verification['verification']}｜"
                f"JSON/PDF={verification['json_pdf_relation']}｜"
                f"snippet_json={verification['snippet_in_json']}｜snippet_pdf={verification['snippet_in_pdf']}"
            )
        lines.append("")
        lines.append("**Top-k 检索：**")
        for verification in result["hit_verifications"]:
            marker = "★GOLD" if (verification["filename"], verification["page_number"]) in {
                (gold["filename"], gold["page_number"]) for gold in result["gold_pages"]
            } else ""
            lines.append(
                f"- S{verification['rank']} {marker} {verification['filename']} p{verification['page_number']}｜"
                f"{verification['evidence_status']}｜{verification['verification']}｜"
                f"score={verification['score']}｜{verification['snippet'][:100]}"
            )
        lines.extend(["", "---", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def write_csv(results: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "id",
        "type",
        "mode",
        "status",
        "gold_in_pool",
        "gold_ranks",
        "retrieval_hit_top1",
        "retrieval_hit_topk",
        "gold_fact_coverage",
        "answer_fact_coverage",
        "cited_fact_coverage",
        "cited_ranks",
        "cited_keys",
        "gold_risks",
        "warnings",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for result in results:
            row = {field: result.get(field) for field in fields}
            for field in ("gold_ranks", "cited_ranks", "cited_keys", "gold_risks", "warnings"):
                row[field] = json.dumps(row[field], ensure_ascii=False)
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top-k", type=int, default=6)
    args = parser.parse_args()

    payload = json.loads(args.questions.read_text(encoding="utf-8"))
    questions = payload["questions"]
    corpus = load_corpus()
    page_map = {(page.filename, page.page_number): page for page in corpus.pages}
    missing = []
    for question in questions:
        for gold in question["gold_pages"]:
            key = (gold["filename"], gold["page_number"])
            if key not in page_map:
                missing.append(f"{question['id']} -> {key[0]} p{key[1]}")
    if missing:
        raise SystemExit("题库引用了不存在的页面：\n" + "\n".join(missing))

    pdf_cache = PdfCache(PDF_DIR)
    retriever = Retriever(corpus)
    engine = AnswerEngine(retriever)
    results = []
    try:
        for question in questions:
            for mode in (MODE_STRICT, MODE_EXPANDED):
                results.append(
                    make_run(
                        question,
                        mode,
                        corpus,
                        retriever,
                        engine,
                        pdf_cache,
                        page_map,
                        top_k=args.top_k,
                    )
                )
    finally:
        pdf_cache.close()

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "raw_results.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "top_k": args.top_k,
                "question_count": len(questions),
                "run_count": len(results),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_csv(results, args.output / "auto_results.csv")
    write_review_packet(results, args.output / "review_packet.md")

    print(f"题目数：{len(questions)}；运行数：{len(results)}")
    for mode in (MODE_STRICT, MODE_EXPANDED):
        mode_results = [result for result in results if result["mode"] == mode]
        hits = sum(result["retrieval_hit_topk"] for result in mode_results)
        eligible = sum(result["gold_in_pool"] for result in mode_results)
        answered = sum(result["status"] == "ok" for result in mode_results)
        print(
            f"{mode}: 可检索 {eligible}/30，Top-k 命中 {hits}/{eligible or 0}，"
            f"有答案 {answered}/30"
        )
    print(f"报告目录：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
