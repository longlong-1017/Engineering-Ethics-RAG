"""根据验收原始结果、人工标签和 PDF/JSON 原文计算指标并生成报告表格。

只读 raw_results.json、labels.json、questions.json 和 corpus；输出 Markdown/CSV/JSON。
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.corpus import load_corpus
from src.text_utils import compact_text

ROOT = PROJECT_ROOT / "reports/phase2_acceptance"
QUESTIONS = ROOT / "questions.json"
RAW = ROOT / "raw_results.json"
LABELS = ROOT / "labels.json"

FAILURE_LABELS = {
    "none": "无",
    "retrieval_failure": "检索失败",
    "text_extraction_error": "文本提取错误",
    "insufficient_evidence": "证据不足",
    "qa_logic_error": "问答逻辑错误",
    "risk_labeling_error": "风险标注错误",
}
VERDICT_LABELS = {
    "correct": "正确（严格证据）",
    "correct_pending_manual": "正确（待人工复核）",
    "partial": "部分正确",
    "partial_pending_manual": "部分正确（待人工复核）",
    "incorrect": "错误",
    "incorrect_pending_manual": "错误（待人工复核）",
    "insufficient_correct": "资料不足（正确）",
    "insufficient_wrong": "资料不足（误判）",
}
EVIDENCE_LABELS = {
    "supported_strict": "严格证据支持",
    "supported_risk": "非严格证据支持（待复核）",
    "unsupported": "证据不支持",
    "none": "无（未作答）",
}
STATUS_LABELS = {"ok": "有答案", "insufficient": "资料不足", "error": "错误"}


def fact_coverage(text: str, expected: list[list[str]]) -> float:
    compact = compact_text(text)
    matched = 0
    for alternatives in expected:
        if any(compact_text(alt) and compact_text(alt) in compact for alt in alternatives):
            matched += 1
    return matched / len(expected) if expected else 1.0


def pct(value: float) -> str:
    return "N/A" if value is None else f"{value * 100:.1f}%"


def main() -> int:
    questions = {item["id"]: item for item in json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]}
    raw_payload = json.loads(RAW.read_text(encoding="utf-8"))
    labels_payload = json.loads(LABELS.read_text(encoding="utf-8"))
    labels = {(item["id"], item["mode"]): item for item in labels_payload["labels"]}
    corpus = load_corpus()
    page_map = {(page.filename, page.page_number): page for page in corpus.pages}

    enriched: list[dict[str, Any]] = []
    citation_rows: list[dict[str, Any]] = []
    risk_rows: list[dict[str, Any]] = []
    for result in raw_payload["results"]:
        label = labels.get((result["id"], result["mode"]))
        if label is None:
            raise SystemExit(f"缺少标签：{result['id']} {result['mode']}")
        question = questions[result["id"]]
        expected = question["expected_points"]
        gold_in_pool = result["gold_in_pool"]
        gold_cov = result["gold_fact_coverage"]
        should_answer = bool(gold_in_pool and gold_cov >= 0.5)
        verdict = label["answer_verdict"]
        status = result["status"]
        false_insufficient = should_answer and verdict == "insufficient_wrong"
        false_sufficient = (not should_answer) and status == "ok"
        if status == "ok":
            answer_rate = "answered"
        else:
            answer_rate = "insufficient"

        citations = []
        for verification in result["cited_verifications"]:
            key = (verification["filename"], verification["page_number"])
            page = page_map.get(key)
            page_text = page.text if page else ""
            content_cov = fact_coverage(page_text, expected)
            location_ok = verification["verification"] in {
                "verified_exact",
                "verified_reorder",
                "verified_snippet",
            }
            content_ok = content_cov >= 0.5
            support = location_ok and content_ok
            risk = page.evidence_status if page else "missing"
            risk_type = ""
            if page is not None and not page.strict_eligible:
                risk_type = page.review_category if page.review_category else "未审核"
            citation = {
                **verification,
                "content_coverage": round(content_cov, 4),
                "content_ok": content_ok,
                "location_ok": location_ok,
                "support": support,
                "risk_type": risk_type,
                "review_category": verification.get("review_category"),
                "order_review": verification["verification"] == "verified_reorder"
                and verification.get("review_category") == "B",
                "page_text": page_text,
            }
            citations.append(citation)
            row = {
                "id": result["id"],
                "type": result["type"],
                "question": result["question"],
                "mode": result["mode"],
                "citation_rank": verification["rank"],
                "filename": verification["filename"],
                "page_number": verification["page_number"],
                "review_label": verification["review_label"],
                "verification": verification["verification"],
                "json_pdf_relation": verification["json_pdf_relation"],
                "content_coverage": round(content_cov, 4),
                "location_ok": location_ok,
                "content_ok": content_ok,
                "support": support,
                "risk_type": risk_type,
                "review_category": verification.get("review_category"),
                "order_review": verification["verification"] == "verified_reorder"
                and verification.get("review_category") == "B",
                "snippet": verification["snippet"],
                "review_note": verification.get("review_note", ""),
            }
            citation_rows.append(row)
            if risk_type:
                risk_rows.append(row)
        answer_support = [citation for citation in citations if citation["support"]]
        strict_support = [citation for citation in answer_support if citation["risk_type"] == ""]
        risk_support = [citation for citation in answer_support if citation["risk_type"]]
        b_order_review = any(citation["order_review"] for citation in citations)
        manual_review_effective = bool(label["manual_review"] or risk_support or b_order_review)
        if strict_support:
            evidence_verdict = "supported_strict"
        elif risk_support:
            evidence_verdict = "supported_risk"
        elif citations:
            evidence_verdict = "unsupported"
        else:
            evidence_verdict = "none"
        enriched.append(
            {
                "id": result["id"],
                "type": result["type"],
                "question": result["question"],
                "mode": result["mode"],
                "status": status,
                "should_answer": should_answer,
                "gold_in_pool": gold_in_pool,
                "gold_fact_coverage": gold_cov,
                "gold_ranks": result["gold_ranks"],
                "retrieval_hit_top1": result["retrieval_hit_top1"],
                "retrieval_hit_topk": result["retrieval_hit_topk"],
                "answer_fact_coverage": result["answer_fact_coverage"],
                "cited_fact_coverage": result["cited_fact_coverage"],
                "answer_verdict": verdict,
                "failure_type": label["failure_type"],
                "evidence_verdict": evidence_verdict,
                "manual_review": label["manual_review"],
                "manual_review_effective": manual_review_effective,
                "b_order_review": b_order_review,
                "notes": label["notes"],
                "false_insufficient": false_insufficient,
                "false_sufficient": false_sufficient,
                "citations": citations,
                "citation_count": len(citations),
                "strict_support_count": len(strict_support),
                "risk_support_count": len(risk_support),
                "unsupported_citation_count": sum(1 for c in citations if not c["support"]),
                "warnings": result["warnings"],
            }
        )

    def mode_metrics(mode: str) -> dict[str, Any]:
        rows = [row for row in enriched if row["mode"] == mode]
        eligible = [row for row in rows if row["gold_in_pool"]]
        no_gold = [row for row in rows if not row["gold_in_pool"]]
        answered = [row for row in rows if row["status"] == "ok"]
        citations = [citation for row in rows for citation in row["citations"]]
        supporting_citations = [citation for citation in citations if citation["support"]]
        strict_supporting_citations = [
            citation for citation in supporting_citations if citation["risk_type"] == ""
        ]
        risk_supporting_citations = [
            citation for citation in supporting_citations if citation["risk_type"]
        ]
        correct = sum(row["answer_verdict"] == "correct" for row in rows)
        correct_pending = sum(row["answer_verdict"] == "correct_pending_manual" for row in rows)
        partial = sum(row["answer_verdict"] in {"partial", "partial_pending_manual"} for row in rows)
        incorrect = sum(row["answer_verdict"] in {"incorrect", "incorrect_pending_manual"} for row in rows)
        insuff_correct = sum(row["answer_verdict"] == "insufficient_correct" for row in rows)
        insuff_wrong = sum(row["answer_verdict"] == "insufficient_wrong" for row in rows)
        false_insufficient = sum(row["false_insufficient"] for row in rows)
        false_sufficient = sum(row["false_sufficient"] for row in rows)
        failure_counts = Counter(row["failure_type"] for row in rows)
        strict_support_answers = sum(row["evidence_verdict"] == "supported_strict" for row in answered)
        risk_support_answers = sum(row["evidence_verdict"] == "supported_risk" for row in answered)
        unsupported_answers = sum(row["evidence_verdict"] == "unsupported" for row in answered)
        return {
            "mode": mode,
            "questions": len(rows),
            "gold_in_pool": len(eligible),
            "no_gold_in_pool": len(no_gold),
            "retrieval_hit_topk": sum(row["retrieval_hit_topk"] for row in eligible),
            "retrieval_hit_top1": sum(row["retrieval_hit_top1"] for row in eligible),
            "retrieval_hit_rate": (
                sum(row["retrieval_hit_topk"] for row in eligible) / len(eligible)
                if eligible
                else None
            ),
            "retrieval_top1_rate": (
                sum(row["retrieval_hit_top1"] for row in eligible) / len(eligible)
                if eligible
                else None
            ),
            "answered": len(answered),
            "insufficient": len(rows) - len(answered),
            "correct": correct,
            "correct_pending_manual": correct_pending,
            "partial": partial,
            "incorrect": incorrect,
            "insufficient_correct": insuff_correct,
            "insufficient_wrong": insuff_wrong,
            "answer_correct_rate": (correct + correct_pending) / len(rows),
            "strict_correct_rate": correct / len(rows),
            "partial_rate": partial / len(rows),
            "incorrect_rate": incorrect / len(rows),
            "insufficient_rate": (insuff_correct + insuff_wrong) / len(rows),
            "false_insufficient": false_insufficient,
            "false_insufficient_rate": false_insufficient / len(eligible) if eligible else None,
            "false_sufficient": false_sufficient,
            "false_sufficient_rate": false_sufficient / len(no_gold) if no_gold else None,
            "combined_insufficient_error_rate": (false_insufficient + false_sufficient) / len(rows),
            "citation_count": len(citations),
            "b_order_review_citations": sum(
                1 for citation in citations if citation["order_review"]
            ),
            "answers_with_b_order_review": sum(
                1 for row in answered if row["b_order_review"]
            ),
            "citation_location_ok": sum(citation["location_ok"] for citation in citations),
            "citation_location_accuracy": (
                sum(citation["location_ok"] for citation in citations) / len(citations)
                if citations
                else None
            ),
            "citation_content_ok": sum(citation["content_ok"] for citation in citations),
            "citation_content_support_rate": (
                sum(citation["content_ok"] for citation in citations) / len(citations)
                if citations
                else None
            ),
            "supporting_citations": len(supporting_citations),
            "strict_supporting_citations": len(strict_supporting_citations),
            "risk_supporting_citations": len(risk_supporting_citations),
            "strict_evidence_share": (
                len(strict_supporting_citations) / len(citations) if citations else None
            ),
            "risk_evidence_share": (
                len(risk_supporting_citations) / len(citations) if citations else None
            ),
            "answer_support_rate": (
                (strict_support_answers + risk_support_answers) / len(answered)
                if answered
                else None
            ),
            "strict_support_answer_rate": strict_support_answers / len(answered) if answered else None,
            "risk_support_answer_rate": risk_support_answers / len(answered) if answered else None,
            "unsupported_answer_rate": unsupported_answers / len(answered) if answered else None,
            "failure_counts": dict(failure_counts),
        }

    metrics = {
        "dataset": {
            "questions": len(questions),
            "runs": len(enriched),
            "types": dict(Counter(item["type"] for item in questions.values())),
            "documents_covered": len({gold["filename"] for item in questions.values() for gold in item["gold_pages"]}),
        },
        "definitions": {
            "retrieval_hit_rate": "Top-k 命中金标页的题数 / 该模式池内含金标页的题数；金标页不在池内记 N/A，不算失败。",
            "answer_correct_rate": "答案完全正确或正确但证据待复核的题数 / 30；不把资料不足算作回答正确。",
            "strict_correct_rate": "仅计严格证据支持且答案正确的题数 / 30。",
            "false_insufficient": "池内含金标页且 gold 原文事实覆盖>=50%，系统却返回资料不足的题数。",
            "false_insufficient_rate": "false_insufficient / 该模式池内有金标页的题数。",
            "false_sufficient": "池内无金标页，系统却给出答案的题数。",
            "false_sufficient_rate": "false_sufficient / 该模式池内无金标页的题数；无此类题时 N/A。",
            "combined_insufficient_error_rate": "(false_insufficient + false_sufficient) / 30。",
            "citation_location_accuracy": "引用页中 PDF 文件名/物理页码存在且片段能在 JSON 或 PDF 文字层定位的比例。",
            "citation_content_support_rate": "引用页正文覆盖该题 >=50% 预期事实组的比例。",
            "answer_support_rate": "有答案的题中，至少一条引用页同时满足定位正确且内容覆盖>=50% 的比例。",
            "strict_support_answer_rate": "有答案的题中，至少一条严格页同时满足定位正确且内容覆盖>=50% 的比例。",
            "risk_support_answer_rate": "有答案的题中，仅由非严格页（未审核/C/D/E）提供支持的比例；这些答案必须待人工复核。",
            "unsupported_answer_rate": "有答案的题中，没有任何引用页同时满足定位正确且内容覆盖>=50% 的比例。",
        },
        "modes": {mode: mode_metrics(mode) for mode in ("strict", "expanded")},
    }
    all_topk_risk = [
        verification
        for result in raw_payload["results"]
        for verification in result["hit_verifications"]
        if verification["evidence_status"] != "strict"
    ]
    metrics["risk_summary"] = {
        "cited_risk_pages": len(risk_rows),
        "cited_risk_by_category": dict(Counter(row["risk_type"] for row in risk_rows)),
        "all_topk_risk_hits": len(all_topk_risk),
        "all_topk_risk_by_category": dict(
            Counter(
                verification.get("review_category") or "未审核"
                for verification in all_topk_risk
            )
        ),
        "all_topk_risk_by_status": dict(
            Counter(verification["evidence_status"] for verification in all_topk_risk)
        ),
    }
    (ROOT / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 逐题/逐模式明细 CSV
    with (ROOT / "per_run_results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "id", "type", "question", "mode", "status", "should_answer", "gold_in_pool",
            "gold_ranks", "retrieval_hit_topk", "retrieval_hit_top1", "answer_verdict",
            "evidence_verdict", "failure_type", "manual_review", "false_insufficient",
            "false_sufficient", "answer_fact_coverage", "citation_count",
            "manual_review_effective", "b_order_review", "notes",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in enriched:
            writer.writerow({key: json.dumps(row[key], ensure_ascii=False) if isinstance(row[key], list) else row[key] for key in fieldnames})

    with (ROOT / "citations.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "id", "type", "question", "mode", "citation_rank", "filename", "page_number",
            "review_label", "verification", "json_pdf_relation", "content_coverage",
            "location_ok", "content_ok", "support", "risk_type", "review_category", "order_review", "snippet", "review_note",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(citation_rows)

    # 逐题结果表（30 行，严格/扩展并列）
    by_question: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in enriched:
        by_question[row["id"]][row["mode"]] = row
    lines = [
        "# 第二阶段验收：逐题结果表",
        "",
        "口径：`Top-k` 指该题在该模式下前 6 条检索结果；`检索` 列的 `N/A` 表示金标页不在该模式池内，不能算检索失败。",
        "`判定` 为人工逐题判读；`待复核` 表示引用页属于未审核/C/D/E 或 B 类未修复/重排页，不能自动视为可靠。",
        "",
        "| 编号 | 类型 | 问题 | 严格：检索 | 严格：状态 | 严格：判定 | 严格：证据 | 严格：失败 | 扩展：检索 | 扩展：状态 | 扩展：判定 | 扩展：证据 | 扩展：失败 | 待复核 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for question in questions.values():
        strict = by_question[question["id"]]["strict"]
        expanded = by_question[question["id"]]["expanded"]

        def retrieval_cell(row):
            if not row["gold_in_pool"]:
                return "N/A"
            if row["retrieval_hit_top1"]:
                return "Top1"
            if row["retrieval_hit_topk"]:
                return f"Top-{max(row['gold_ranks'])}"
            return "未命中"

        manual = "是" if (
            strict["manual_review_effective"] or expanded["manual_review_effective"]
        ) else "否"
        lines.append(
            "| {qid} | {qtype} | {question} | {sr} | {ss} | {sv} | {se} | {sf} | {er} | {es} | {ev} | {ee} | {ef} | {manual} |".format(
                qid=question["id"],
                qtype=question["type"],
                question=question["question"].replace("|", "\\|"),
                sr=retrieval_cell(strict),
                ss=STATUS_LABELS.get(strict["status"], strict["status"]),
                sv=VERDICT_LABELS.get(strict["answer_verdict"], strict["answer_verdict"]),
                se=EVIDENCE_LABELS.get(strict["evidence_verdict"], strict["evidence_verdict"]),
                sf=FAILURE_LABELS.get(strict["failure_type"], strict["failure_type"]),
                er=retrieval_cell(expanded),
                es=STATUS_LABELS.get(expanded["status"], expanded["status"]),
                ev=VERDICT_LABELS.get(expanded["answer_verdict"], expanded["answer_verdict"]),
                ee=EVIDENCE_LABELS.get(expanded["evidence_verdict"], expanded["evidence_verdict"]),
                ef=FAILURE_LABELS.get(expanded["failure_type"], expanded["failure_type"]),
                manual=manual,
            )
        )
    (ROOT / "逐题结果表.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 失败题目说明
    failure_lines = [
        "# 第二阶段验收：失败题目与原因",
        "",
        "只列 `failure_type != none` 的运行。判定口径见 `acceptance_report.md`。",
        "",
        "| 编号 | 模式 | 问题 | 判定 | 失败类型 | 证据判定 | 人工说明 |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in enriched:
        if row["failure_type"] == "none":
            continue
        failure_lines.append(
            f"| {row['id']} | {row['mode']} | {row['question'].replace('|', '\\|')} | "
            f"{VERDICT_LABELS.get(row['answer_verdict'], row['answer_verdict'])} | "
            f"{FAILURE_LABELS.get(row['failure_type'], row['failure_type'])} | "
            f"{EVIDENCE_LABELS.get(row['evidence_verdict'], row['evidence_verdict'])} | "
            f"{row['notes']} |"
        )
    (ROOT / "failure_analysis.md").write_text("\n".join(failure_lines) + "\n", encoding="utf-8")

    # 证据风险登记表
    risk_lines = [
        "# 第二阶段验收：证据风险登记（非严格引用页）",
        "",
        "只登记答案实际引用、且不属于严格合格页的页面。`待人工复核` 表示即使文字层自动匹配，也不能视为已验证。",
        "",
        "| 编号 | 模式 | 引用页 | 类别/状态 | 自动核对 | 内容覆盖 | 支持 | 风险备注 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in risk_rows:
        risk_lines.append(
            f"| {row['id']} | {row['mode']} | [S{row['citation_rank']}] {row['filename']} p{row['page_number']} | "
            f"{row['review_label']} | {row['verification']} | {row['content_coverage']:.0%} | "
            f"{'是' if row['support'] else '否'} | {row['review_note'] or '无'} |"
        )
    if not risk_rows:
        risk_lines.append("| - | - | - | - | - | - | - | 本组未引用非严格页 |")
    (ROOT / "evidence_risk_register.md").write_text("\n".join(risk_lines) + "\n", encoding="utf-8")

    print(json.dumps({mode: {
        "retrieval_hit_rate": metrics["modes"][mode]["retrieval_hit_rate"],
        "answer_correct_rate": metrics["modes"][mode]["answer_correct_rate"],
        "false_insufficient": metrics["modes"][mode]["false_insufficient"],
        "false_sufficient": metrics["modes"][mode]["false_sufficient"],
        "combined_insufficient_error_rate": metrics["modes"][mode]["combined_insufficient_error_rate"],
        "citation_location_accuracy": metrics["modes"][mode]["citation_location_accuracy"],
        "strict_support_answer_rate": metrics["modes"][mode]["strict_support_answer_rate"],
        "risk_support_answer_rate": metrics["modes"][mode]["risk_support_answer_rate"],
    } for mode in ("strict", "expanded")}, ensure_ascii=False, indent=2))
    print(f"输出：{ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
