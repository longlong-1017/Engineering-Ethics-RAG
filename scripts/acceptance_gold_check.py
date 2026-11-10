"""逐题核对金标页：PDF 文件名、物理页码、PDF/JSON 原文一致性。只读。"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pymupdf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.corpus import load_corpus
from src.text_utils import compact_text

ROOT = PROJECT_ROOT / "reports/phase2_acceptance"
PDF_DIR = PROJECT_ROOT / "data/pdfs"


def relation(json_text: str, pdf_text: str) -> str:
    j, p = compact_text(json_text), compact_text(pdf_text)
    if j == p:
        return "exact"
    if Counter(j) == Counter(p):
        return "reorder"
    if j and j in p:
        return "json_subset"
    if p and p in j:
        return "pdf_subset"
    return "mismatch"


def main() -> int:
    questions = json.loads((ROOT / "questions.json").read_text(encoding="utf-8"))["questions"]
    corpus = load_corpus()
    page_map = {(page.filename, page.page_number): page for page in corpus.pages}
    docs = {}
    rows = []
    for question in questions:
        for gold in question["gold_pages"]:
            key = (gold["filename"], gold["page_number"])
            page = page_map.get(key)
            path = PDF_DIR / gold["filename"]
            pdf_text = ""
            pdf_pages = None
            error = ""
            if not path.is_file():
                error = "PDF 文件不存在"
            else:
                doc = docs.get(gold["filename"])
                if doc is None:
                    doc = pymupdf.open(path)
                    docs[gold["filename"]] = doc
                pdf_pages = len(doc)
                if 1 <= gold["page_number"] <= len(doc):
                    pdf_text = doc[gold["page_number"] - 1].get_text("text", sort=True)
                else:
                    error = f"PDF 无该页（共 {len(doc)} 页）"
            rel = relation(page.text, pdf_text) if page is not None and pdf_text else "missing"
            if page is None:
                auto = "json_page_missing"
            elif error:
                auto = "pdf_page_missing"
            elif rel == "exact":
                auto = "verified_exact"
            elif rel == "reorder":
                auto = "verified_reorder"
            elif rel in {"json_subset", "pdf_subset"}:
                auto = "partial_text_match"
            else:
                auto = "unverified"
            rows.append(
                {
                    "id": question["id"],
                    "type": question["type"],
                    "question": question["question"],
                    "filename": gold["filename"],
                    "page_number": gold["page_number"],
                    "pdf_pages": pdf_pages,
                    "review_label": page.review_label if page else "",
                    "evidence_status": page.evidence_status if page else "missing",
                    "json_pdf_relation": rel,
                    "auto_verification": auto,
                    "gold_fact_coverage": None,
                    "error": error,
                }
            )
    for doc in docs.values():
        doc.close()

    # 用题目预期事实计算每页覆盖
    for row, question in zip(rows, [q for q in questions for _ in q["gold_pages"]]):
        compact = compact_text(page_map[(row["filename"], row["page_number"])].text)
        matched = sum(
            1
            for alternatives in question["expected_points"]
            if any(compact_text(alt) in compact for alt in alternatives)
        )
        row["gold_fact_coverage"] = matched / len(question["expected_points"])

    out = ROOT / "gold_page_validation.json"
    out.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 金标页 PDF/JSON 自动核对",
        "",
        "`verified_exact`：PDF 文字层与 JSON 去空白后完全一致；`verified_reorder`：非空白字符多重集合一致，顺序经过 B 类修复；其余需人工复核。",
        "",
        "| 编号 | 金标页 | 类别 | PDF页数 | 自动核对 | JSON/PDF | 事实覆盖 | 备注 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['id']} | {row['filename']} p{row['page_number']} | {row['review_label']} | "
            f"{row['pdf_pages']} | {row['auto_verification']} | {row['json_pdf_relation']} | "
            f"{row['gold_fact_coverage']:.0%} | {row['error'] or '无'} |"
        )
    (ROOT / "gold_page_validation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"gold pages: {len(rows)}")
    print("auto:", dict(Counter(row["auto_verification"] for row in rows)))
    print("relation:", dict(Counter(row["json_pdf_relation"] for row in rows)))
    print("status:", dict(Counter(row["evidence_status"] for row in rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
