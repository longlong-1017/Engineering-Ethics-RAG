"""加载 processed_v3 页面并区分严格合格页、扩展页与未审核页。

本模块只读 data/processed_v3 下的 JSON，不修改、不覆盖任何原始数据。
严格合格页的唯一口径：A 类，或已应用定向修复的 B 类。其他页面一律不标为已验证。
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from src.config import DEFAULT_DATA_DIR


class CorpusError(RuntimeError):
    """知识库目录、JSON 或页面元数据不可用时抛出。"""


REVIEW_CATEGORY_LABELS = {
    "A": "A｜已审核：核心文字与顺序完整",
    "B": "B｜已审核：阅读顺序异常",
    "C": "C｜已审核：图片文字未提取，内容不完整",
    "D": "D｜已审核：非核心配图或结束页",
    "E": "E｜已审核：可见性/内容无法确认",
}
UNREVIEWED_LABEL = "未审核｜不能作为已验证依据"

PAGE_STATUS_LABELS = {
    "text": "有文本",
    "blank": "空白页",
    "suspected_scan": "疑似扫描页",
    "non_text": "无文本但有矢量内容",
    "error": "页面读取错误",
    "visibility_quarantined": "可见性隔离",
}


def _as_clean_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


@dataclass(frozen=True)
class Page:
    """一页课件及其审核状态。"""

    document_id: str
    filename: str
    page_number: int
    text: str
    page_status: str = "unknown"
    review_category: str | None = None
    repair_status: str | None = None
    repair_applied: bool = False
    review_note: str = ""
    review_basis: str = ""
    warnings: tuple[str, ...] = ()
    source_file: str = ""
    dataset_version: str = "old"
    versioned_source: bool = False

    @property
    def version_label(self) -> str:
        if self.dataset_version == "exam_2026":
            return "新版·当前考试"
        if self.dataset_version == "textbook":
            return "教材"
        if self.dataset_version == "quiz":
            return "题库"
        return "旧版·补充"

    @property
    def reviewed(self) -> bool:
        return self.review_category in REVIEW_CATEGORY_LABELS

    @property
    def strict_eligible(self) -> bool:
        """A 类或已修复 B 类，且有可检索文本。"""
        return bool(self.text.strip()) and self.evidence_status == "strict"

    @property
    def evidence_status(self) -> str:
        if not self.text.strip():
            return "no_text"
        if self.review_category == "A":
            return "strict"
        if self.review_category == "B" and self.repair_applied:
            return "strict"
        if self.reviewed:
            return "reviewed_hold"
        return "unreviewed"

    @property
    def strict_label(self) -> str:
        if self.evidence_status == "strict":
            if self.review_category == "A":
                return "严格合格｜A 类已审核"
            return "严格合格｜B 类已修复"
        return self.review_label

    @property
    def review_label(self) -> str:
        if not self.reviewed:
            return UNREVIEWED_LABEL
        base = REVIEW_CATEGORY_LABELS[self.review_category or ""]
        if self.review_category == "B":
            if self.repair_applied:
                return "B｜已审核：阅读顺序已修复"
            return "B｜已审核：顺序异常且未修复"
        return base

    @property
    def page_status_label(self) -> str:
        return PAGE_STATUS_LABELS.get(self.page_status, self.page_status or "未知")

    @property
    def location(self) -> str:
        """面向用户的位置说明：PDF 文件名 + 物理页码。"""
        return f"{self.filename} 第 {self.page_number} 页"

    @property
    def citation(self) -> str:
        prefix = f"【{self.version_label}】" if self.versioned_source else ""
        return f"{prefix}《{self.filename}》第 {self.page_number} 页"

    @property
    def document_stem(self) -> str:
        return Path(self.filename).stem

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "dataset_version": self.dataset_version,
            "version_label": self.version_label,
            "filename": self.filename,
            "page_number": self.page_number,
            "text": self.text,
            "page_status": self.page_status,
            "review_category": self.review_category,
            "repair_status": self.repair_status,
            "repair_applied": self.repair_applied,
            "review_note": self.review_note,
            "review_basis": self.review_basis,
            "warnings": list(self.warnings),
            "source_file": self.source_file,
            "strict_eligible": self.strict_eligible,
            "evidence_status": self.evidence_status,
            "review_label": self.review_label,
            "strict_label": self.strict_label,
            "citation": self.citation,
        }


@dataclass(frozen=True)
class DocumentInfo:
    filename: str
    document_id: str
    page_count: int
    status: str
    source_file: str
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class Corpus:
    pages: tuple[Page, ...]
    documents: tuple[DocumentInfo, ...]
    source_files: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total_pages(self) -> int:
        return len(self.pages)

    @property
    def text_pages(self) -> tuple[Page, ...]:
        return tuple(page for page in self.pages if page.text.strip())

    @property
    def strict_pages(self) -> tuple[Page, ...]:
        return tuple(page for page in self.pages if page.strict_eligible)

    @property
    def expanded_pages(self) -> tuple[Page, ...]:
        return self.text_pages

    @property
    def reviewed_pages(self) -> tuple[Page, ...]:
        return tuple(page for page in self.pages if page.reviewed)

    @property
    def unreviewed_pages(self) -> tuple[Page, ...]:
        return tuple(page for page in self.pages if not page.reviewed)

    def review_counts(self) -> dict[str, int]:
        counts = Counter(
            page.review_category if page.review_category else "未审核"
            for page in self.pages
        )
        return dict(sorted(counts.items()))

    def stats(self) -> dict[str, Any]:
        return {
            "documents": len(self.documents),
            "total_pages": self.total_pages,
            "text_pages": len(self.text_pages),
            "strict_pages": len(self.strict_pages),
            "expanded_pages": len(self.expanded_pages),
            "reviewed_pages": len(self.reviewed_pages),
            "unreviewed_pages": len(self.unreviewed_pages),
            "review_categories": self.review_counts(),
        }

    def document(self, filename: str) -> DocumentInfo | None:
        for document in self.documents:
            if document.filename == filename:
                return document
        return None


def _parse_review(raw_page: dict[str, Any]) -> dict[str, Any]:
    review = raw_page.get("high_risk_review")
    if not isinstance(review, dict):
        return {
            "category": None,
            "repair_applied": False,
            "note": "",
            "basis": "",
        }
    category = _as_clean_string(review.get("category")).upper()
    if category not in REVIEW_CATEGORY_LABELS:
        category = None
    return {
        "category": category,
        "repair_applied": review.get("repair_applied") is True,
        "note": _as_clean_string(review.get("note")),
        "basis": _as_clean_string(review.get("basis")),
    }


def _load_document(path: Path) -> tuple[DocumentInfo, list[Page]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorpusError(f"无法读取 JSON：{path.name}：{type(exc).__name__}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CorpusError(f"JSON 顶层必须是对象：{path.name}")
    raw_pages = payload.get("pages")
    if not isinstance(raw_pages, list):
        raise CorpusError(f"JSON 缺少 pages 列表：{path.name}")

    filename = _as_clean_string(payload.get("filename")) or path.stem
    document_id = _as_clean_string(payload.get("document_id"))
    document = DocumentInfo(
        filename=filename,
        document_id=document_id,
        page_count=int(payload.get("page_count") or len(raw_pages)),
        status=_as_clean_string(payload.get("status")) or "unknown",
        source_file=path.name,
        warnings=tuple(str(item) for item in payload.get("warnings") or []),
        errors=tuple(str(item) for item in payload.get("errors") or []),
    )

    pages: list[Page] = []
    seen_numbers: set[int] = set()
    for index, raw_page in enumerate(raw_pages):
        if not isinstance(raw_page, dict):
            raise CorpusError(f"页面记录必须是对象：{path.name} 第 {index + 1} 条")
        try:
            page_number = int(raw_page.get("page_number"))
        except (TypeError, ValueError) as exc:
            raise CorpusError(f"页面缺少有效 page_number：{path.name} 第 {index + 1} 条") from exc
        if page_number <= 0:
            raise CorpusError(f"page_number 必须从 1 开始：{path.name} 第 {index + 1} 条")
        if page_number in seen_numbers:
            raise CorpusError(f"同一文档出现重复页码：{filename} 第 {page_number} 页")
        seen_numbers.add(page_number)

        text = raw_page.get("text")
        if not isinstance(text, str):
            text = ""
        review = _parse_review(raw_page)
        warnings = raw_page.get("warnings")
        pages.append(
            Page(
                document_id=_as_clean_string(raw_page.get("document_id")) or document_id,
                filename=_as_clean_string(raw_page.get("filename")) or filename,
                page_number=page_number,
                text=text,
                page_status=_as_clean_string(raw_page.get("status")) or "unknown",
                review_category=review["category"],
                repair_status=_as_clean_string(raw_page.get("repair_status")) or None,
                repair_applied=review["repair_applied"],
                review_note=review["note"],
                review_basis=review["basis"],
                warnings=tuple(str(item) for item in warnings or []),
                source_file=path.name,
            )
        )
    pages.sort(key=lambda page: page.page_number)
    return document, pages


def load_corpus(
    data_dir: Path | str | None = None,
    *,
    source_files: Iterable[Path] | None = None,
) -> Corpus:
    """加载 processed_v3。目录为空、JSON 损坏或页码异常时抛出 CorpusError。"""
    if source_files is None:
        directory = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
        if not directory.is_dir():
            raise CorpusError(f"知识库目录不存在：{directory}")
        files = sorted(directory.glob("*.json"))
    else:
        files = sorted(Path(path) for path in source_files)
    if not files:
        raise CorpusError(f"知识库目录中没有 JSON 文件：{Path(data_dir) if data_dir else DEFAULT_DATA_DIR}")

    documents: list[DocumentInfo] = []
    pages: list[Page] = []
    for path in files:
        if not path.is_file():
            raise CorpusError(f"知识库文件不存在：{path}")
        document, document_pages = _load_document(path)
        documents.append(document)
        pages.extend(document_pages)
    if not pages:
        raise CorpusError("知识库没有任何页面记录")

    identifiers = [(page.filename, page.page_number) for page in pages]
    if len(identifiers) != len(set(identifiers)):
        raise CorpusError("不同 JSON 中出现重复的文件名与页码组合")

    pages.sort(key=lambda page: (page.filename, page.page_number))
    documents.sort(key=lambda document: document.filename)
    return Corpus(
        pages=tuple(pages),
        documents=tuple(documents),
        source_files=tuple(path.name for path in files),
    )


def format_stats(stats: dict[str, Any]) -> str:
    """把统计结果格式化为 CLI 文本。"""
    lines = [
        "===== 工程伦理知识库覆盖情况 =====",
        f"文档数：{stats['documents']}",
        f"总页数：{stats['total_pages']}",
        f"有文本页面：{stats['text_pages']}",
        f"严格检索页面：{stats['strict_pages']}（A 类 + 已修复 B 类）",
        f"扩展检索页面：{stats['expanded_pages']}（全部有文本页面，含未审核）",
        f"已审核页面：{stats['reviewed_pages']}",
        f"未审核页面：{stats['unreviewed_pages']}",
        "",
        "===== 页面审核类别 =====",
    ]
    for category, count in stats["review_categories"].items():
        label = REVIEW_CATEGORY_LABELS.get(category, UNREVIEWED_LABEL)
        lines.append(f"{label}: {count}")
    return "\n".join(lines)
