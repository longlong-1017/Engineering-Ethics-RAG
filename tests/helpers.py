"""测试用的合成语料工具。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.corpus import Corpus, Page


def make_page(
    text: str,
    *,
    category: str | None = None,
    repaired: bool = False,
    filename: str = "课件.pdf",
    page_number: int = 1,
    doc_id: str = "doc-1",
    page_status: str = "text",
    note: str = "",
) -> Page:
    return Page(
        document_id=doc_id,
        filename=filename,
        page_number=page_number,
        text=text,
        page_status=page_status,
        review_category=category,
        repair_applied=repaired,
        review_note=note,
        review_basis="test",
        source_file=f"{filename}.json",
    )


def make_corpus(*pages: Page) -> Corpus:
    return Corpus(pages=tuple(pages), documents=(), source_files=())


def write_document(
    directory: Path,
    filename: str,
    records: list[dict[str, Any]],
    *,
    doc_id: str = "doc-1",
    page_count: int | None = None,
) -> Path:
    payload = {
        "schema_version": 3,
        "filename": filename,
        "document_id": doc_id,
        "page_count": page_count if page_count is not None else len(records),
        "status": "ok",
        "warnings": [],
        "errors": [],
        "pages": records,
    }
    path = directory / f"{Path(filename).stem}_{doc_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def record(
    page_number: int,
    text: str,
    *,
    category: str | None = None,
    repaired: bool = False,
    filename: str = "课件.pdf",
    doc_id: str = "doc-1",
    page_status: str = "text",
) -> dict[str, Any]:
    reviewed: dict[str, Any] = {}
    if category is not None:
        reviewed = {
            "category": category,
            "note": f"测试分类 {category}",
            "basis": "test",
            "repair_applied": repaired,
        }
    return {
        "document_id": doc_id,
        "filename": filename,
        "page_number": page_number,
        "text": text,
        "status": page_status,
        "warnings": [],
        "high_risk_review": reviewed,
    }


def structured_answer(
    summary: str,
    points: list[tuple[str, list[str]]] | None = None,
    *,
    conclusion: str = "",
    insufficient: bool = False,
) -> str:
    """测试用结构化 JSON 答案，模拟 DeepSeek 的约定输出。"""
    payload = {
        "summary": summary,
        "points": [
            {"content": content, "citations": list(refs)}
            for content, refs in (points or [])
        ],
        "conclusion": conclusion,
        "insufficient": insufficient,
    }
    return json.dumps(payload, ensure_ascii=False)
