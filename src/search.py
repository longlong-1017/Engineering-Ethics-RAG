"""旧版关键词检索入口（保留兼容）。

新代码请使用 `python -m src.cli search/ask` 或 `src.retriever.Retriever`。
本模块默认只检索严格合格页，并支持命令行交互。
"""

from __future__ import annotations

from pathlib import Path

from src.corpus import load_corpus
from src.retriever import MODE_STRICT, Retriever


def load_pages(data_dir: Path | str | None = None) -> list[dict]:
    """返回严格合格页的字典列表（兼容旧接口）。"""
    return [page.to_dict() for page in load_corpus(data_dir).strict_pages]


def search(
    query: str,
    *,
    mode: str = MODE_STRICT,
    limit: int = 10,
    data_dir: Path | str | None = None,
) -> list[dict]:
    """检索并返回命中页字典列表，供旧调用方使用。"""
    retriever = Retriever(load_corpus(data_dir))
    response = retriever.search(query, mode=mode, top_k=limit)
    return [hit.to_dict() for hit in response.hits]


def main() -> None:
    from src.retriever import MODE_EXPANDED

    retriever = Retriever(load_corpus())
    print("工程伦理本地知识库 - 中文检索（BM25 + 关键词覆盖率）")
    print("默认严格范围；输入 /expanded 切换到扩展范围；输入 q 退出")
    mode = MODE_STRICT

    while True:
        try:
            query = input("\n请输入关键词或问题：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n程序已退出")
            break

        if not query:
            print("请输入有效关键词。")
            continue
        if query.lower() == "q":
            print("程序已退出")
            break
        if query == "/expanded":
            mode = MODE_EXPANDED
            print("已切换到扩展范围（含未审核页面，结果会明确标注）。")
            continue
        if query == "/strict":
            mode = MODE_STRICT
            print("已切换到严格范围。")
            continue

        response = retriever.search(query, mode=mode, top_k=10)
        if not response.hits:
            print("没有找到匹配内容。")
            if mode == MODE_STRICT:
                print("严格范围只含已审核合格页；可输入 /expanded 查看全部有文本页面。")
            continue

        print(f"\n找到 {len(response.hits)} 条结果")
        for hit in response.hits:
            print(f"\n[S{hit.rank}] {hit.citation}")
            print(f"证据状态：{hit.review_label}")
            print(
                f"评分：{hit.score:.2f}｜BM25 {hit.bm25_score:.2f}｜"
                f"覆盖率 {hit.coverage:.0%}"
            )
            print(f"内容：{hit.snippet}")


if __name__ == "__main__":
    main()
