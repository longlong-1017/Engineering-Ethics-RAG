"""轻量 BM25 实现（Okapi BM25），不依赖第三方检索库。"""

from __future__ import annotations

import math
from collections import Counter
from typing import Sequence


class BM25Index:
    """针对已分词文档的 BM25 索引。

    IDF 使用 log(1 + (N - df + 0.5) / (df + 0.5))，对短课件页更稳定；
    未出现在语料中的查询词也返回较高的 IDF，用于计算查询覆盖率。
    """

    def __init__(
        self,
        documents: Sequence[Sequence[str]],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        if k1 < 0 or not 0 <= b <= 1:
            raise ValueError("BM25 参数非法：要求 k1 >= 0 且 0 <= b <= 1")
        self.k1 = k1
        self.b = b
        self.documents = tuple(tuple(document) for document in documents)
        self.doc_count = len(self.documents)
        self.term_frequencies = tuple(Counter(document) for document in self.documents)
        self.doc_lengths = tuple(len(document) for document in self.documents)
        self.average_length = (
            sum(self.doc_lengths) / self.doc_count if self.doc_count else 0.0
        )
        document_frequency: Counter[str] = Counter()
        for frequencies in self.term_frequencies:
            document_frequency.update(frequencies.keys())
        self.document_frequency = document_frequency
        self._idf_cache: dict[str, float] = {}

    def idf(self, term: str) -> float:
        cached = self._idf_cache.get(term)
        if cached is not None:
            return cached
        df = self.document_frequency.get(term, 0)
        value = math.log(1.0 + (self.doc_count - df + 0.5) / (df + 0.5))
        self._idf_cache[term] = value
        return value

    def document_matches(self, index: int, term: str) -> bool:
        if not 0 <= index < self.doc_count:
            raise IndexError(f"文档下标越界：{index}")
        return term in self.term_frequencies[index]

    def score(self, query: Sequence[str]) -> list[float]:
        """返回每个文档的 BM25 分数；重复查询词只计一次。"""
        terms = list(dict.fromkeys(query))
        scores = [0.0] * self.doc_count
        if not terms or not self.doc_count:
            return scores
        average_length = self.average_length or 1.0
        for term in terms:
            term_idf = self.idf(term)
            # df == 0 时 BM25 贡献为 0，但仍参与覆盖率计算。
            for index, frequencies in enumerate(self.term_frequencies):
                term_frequency = frequencies.get(term, 0)
                if not term_frequency:
                    continue
                length_ratio = self.doc_lengths[index] / average_length
                denominator = term_frequency + self.k1 * (1.0 - self.b + self.b * length_ratio)
                scores[index] += term_idf * (
                    term_frequency * (self.k1 + 1.0) / denominator
                )
        return scores
