"""打印 processed_v3 的覆盖与审核统计。只读，不修改任何文件。"""

from __future__ import annotations

from src.corpus import CorpusError, format_stats, load_corpus


def main() -> int:
    try:
        corpus = load_corpus()
    except CorpusError as exc:
        print(f"知识库加载失败：{exc}")
        return 1
    print(format_stats(corpus.stats()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
