"""第四阶段考试问答的本地材料适配层。

只读复用现有教材/题库/双版本 PPT 检索：
- PPT 仍由 VersionedRetriever 提供严格/扩展范围；
- 教材复用 TextbookRetriever（BM25，不重建向量）；
- 题库复用只读 SQLite；
- 相关性过滤复用 retrieval_review 的候选校准，不升级任何审核状态。
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from src.corpus import Page
from src.evidence import plan_evidence
from src.quiz_bank import query_questions
from src.retrieval_review import RelevanceCalibration, RetrievalReviewSession
from src.retriever import Hit, MODE_EXPANDED, MODE_STRICT, SearchResponse
from src.text_utils import query_terms
from src.textbook_kb import TextbookRetriever, load_blocks


# 第三阶段冻结的候选校准；provenance 明确为助手候选，不是人工金标。
PROVISIONAL_CALIBRATION = RelevanceCalibration(
    (1, 2, 0, 0, 1),
    0.3660714285714286,
    0.6875,
    "assistant_review_provisional_not_human_gold",
)


def _record_page(record: dict[str, Any], rank: int) -> Page | None:
    """把 retrieval_review 记录转成只读 Page；不伪造审核状态。"""
    sources = record.get("sources") or []
    source = next((s for s in sources if s.get("filename") and s.get("physical_page")), None)
    if not source:
        return None
    kind = record.get("kind", "")
    status = (record.get("review_status") or "").lower()
    # PPT 只有 strict_eligible 才映射为严格；教材/题库保持未审核。
    if kind in {"ppt_old", "ppt_new"} and record.get("strict_eligible"):
        category = "B" if status.startswith("b") else "A"
        repaired = category == "B"
    else:
        category = None
        repaired = False
    return Page(
        document_id=str(source.get("document_sha256") or record.get("id", f"material-{rank}")),
        filename=str(source["filename"]),
        page_number=int(source["physical_page"]),
        text=record.get("text", ""),
        page_status="text",
        review_category=category,
        repair_applied=repaired,
        review_note=(
            f"检索材料：{kind}；原始审核状态：{record.get('review_status', 'UNVERIFIED')}。"
            "相关性校准为助手候选，不是人工金标。"
        ),
        review_basis="exam_materials_review_provisional",
        source_file=f"material:{record.get('id')}",
        dataset_version=(
            "exam_2026" if kind == "ppt_new"
            else "old" if kind == "ppt_old"
            else "textbook" if kind == "textbook"
            else "quiz"
        ),
        versioned_source=True,
    )


def _record_hit(record: dict[str, Any], rank: int, score: float = 0.0) -> Hit | None:
    page = _record_page(record, rank)
    if page is None:
        return None
    features = record.get("features") or {}
    return Hit(
        page=page,
        score=float(score or record.get("score") or 0.0),
        bm25_score=float((record.get("raw_scores") or {}).get("bm25") or 0.0),
        coverage=float(features.get("term_coverage") or 0.0),
        matched_terms=tuple(query_terms(record.get("text", ""))[:8]),
        phrase_match=False,
        snippet=record.get("text", "")[:380],
        rank=rank,
        score_type="review_calibrated",
    )


class LocalMaterialsRetriever:
    """对 QA/选择题暴露与 Retriever 相同的最小 search 接口。"""

    def __init__(self, base, textbook: TextbookRetriever, blocks, bank):
        self.base = base
        self.corpus = getattr(base, "corpus", None)
        self.blocks = blocks
        self.bank = list(bank)
        self.session = RetrievalReviewSession(
            {"ppt_old": base.old, "ppt_new": base.new}
            if hasattr(base, "old") and hasattr(base, "new") else {},
            textbook,
            blocks,
            self.bank,
            PROVISIONAL_CALIBRATION,
        )

    @classmethod
    def load(cls, base):
        blocks, _ = load_blocks()
        textbook = TextbookRetriever(blocks)  # 复用 BM25；不重建教材向量
        try:
            bank = query_questions()
        except Exception:
            bank = []
        return cls(base, textbook, blocks, bank)

    def search(self, query: str, *, mode: str = MODE_STRICT, top_k: int | None = None):
        # 严格范围保持原有 PPT 严格边界；教材/题库全部 UNVERIFIED，不进入严格池。
        if mode == MODE_STRICT:
            return self.base.search(query, mode=mode, top_k=top_k)
        limit = max(1, int(top_k or 6))
        reviewed = self.session.search(query, top_k=max(limit, 8), strict=False)
        selected = reviewed.get("selected", [])
        records = [entry["record"] for entry in selected]
        hits = []
        seen = set()
        # 严格页始终排在扩展候选之前；相关性过滤只能补充，不能把严格页挤出 Top-K。
        ordered = sorted(
            selected,
            key=lambda entry: 0 if entry["record"].get("strict_eligible") else 1,
        )
        for entry in ordered:
            record = entry["record"]
            if record.get("kind") == "quiz":
                # 题库题干只用于选择题/诊断，不当作简答题事实正文。
                continue
            hit = _record_hit(record, len(hits) + 1, entry.get("score", 0.0))
            if hit is not None and hit.evidence_id not in seen:
                seen.add(hit.evidence_id)
                hits.append(hit)
        diagnostics = {
            "active_mode": "local_ppt_textbook_review",
            "review": {
                "coverage": reviewed.get("coverage"),
                "calibration": reviewed.get("calibration"),
                "filtered": reviewed.get("filtered", [])[:12],
                "quiz_matches": [r.get("id") for r in records if r.get("kind") == "quiz"],
                "provenance": PROVISIONAL_CALIBRATION.provenance,
                "note": "相关性为助手候选校准；相关不等于充分，不升级审核状态。",
            },
            "materials": {
                "ppt": sum(1 for h in hits if h.page.dataset_version in {"old", "exam_2026"}),
                "textbook": sum(1 for h in hits if h.page.dataset_version == "textbook"),
            },
            "selected_pages": [
                dict(version=h.page.dataset_version, filename=h.page.filename,
                     page_number=h.page.page_number, evidence_id=h.evidence_id)
                for h in hits
            ],
            "retrieval_diagnostics": reviewed.get("retrieval_diagnostics", {}),
        }
        return SearchResponse(
            query=query,
            mode=MODE_EXPANDED,
            terms=query_terms(query),
            hits=tuple(hits[:limit]),
            pool_size=len(getattr(self.base.corpus, "pages", ())),
            strict_pool_size=len(getattr(getattr(self.base, "old", None), "corpus", self.base.corpus).strict_pages)
            if getattr(getattr(self.base, "old", None), "corpus", self.base.corpus) else 0,
            expanded_pool_size=len(getattr(self.base.corpus, "expanded_pages", ())) + len(self.blocks) + len(self.bank),
            diagnostics=diagnostics,
        )
