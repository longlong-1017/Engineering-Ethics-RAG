# 第二阶段验收产物索引

验收日期：2026-11-08。所有文件均为只读验收产物；未修改 `data/pdfs/` 与 `data/processed_v3/`，未调用付费 API。

| 文件 | 用途 |
|---|---|
| [`acceptance_report.md`](acceptance_report.md) | **主报告**：结论、指标口径、结果、失败分析、风险与建议 |
| [`questions.json`](questions.json) | 30 道题、预期事实、金标页、备注 |
| [`逐题结果表.md`](逐题结果表.md) | 30 题严格/扩展并列结果表 |
| [`逐题引用核对表.md`](逐题引用核对表.md) | 60 次运行的引用文件/页码/自动核对/待复核明细 |
| [`failure_analysis.md`](failure_analysis.md) | 28 个失败运行的逐条原因 |
| [`evidence_risk_register.md`](evidence_risk_register.md) | 31 条非严格引用页的风险登记 |
| [`gold_page_validation.md`](gold_page_validation.md) | 42 个金标页的 PDF/JSON/页码自动核对 |
| [`labels.json`](labels.json) | 60 次运行的人工判定与失败类型 |
| [`metrics.json`](metrics.json) | 机器可读指标 |
| [`raw_results.json`](raw_results.json) | 60 次运行的完整原始结果 |
| [`review_packet.md`](review_packet.md) | 逐题原始答案与 Top-k 证据包（人工复核用） |
| [`per_run_results.csv`](per_run_results.csv) | 逐次运行汇总 CSV |
| [`citations.csv`](citations.csv) | 98 条引用的定位/内容/风险明细 |

## 复现

```sh
source .venv/bin/activate
python scripts/acceptance_eval.py
python scripts/acceptance_gold_check.py
python scripts/acceptance_score.py
```

`acceptance_eval.py` 使用 `provider=local` 和 `allow_api=False`，不会发起 API 请求。
