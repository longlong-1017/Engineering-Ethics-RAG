# 第四阶段考试问答接入报告

日期：2026-11-12  
项目：`/Users/along/Projects/Engineering-Ethics-RAG`  
范围：简答题混合/本地模式、选择题混合模式、界面精简、回归测试。未重建知识库、未重做 OCR、未重建 1461 条教材向量、未修改 PDF 页码映射或 UNVERIFIED 审核状态。

## 1. 接管检查结果

- Git：`main` 已有初始提交；工作区有大量其他智能体未提交改动（教材、题库、双版本、检索审查、选择题等），本次没有 reset/checkout/覆盖。
- 已有模块：`src/retriever.py`、`src/versioned_corpus.py`、`src/textbook_kb.py`、`src/quiz_bank.py`、`src/retrieval_review.py`、`src/choice_solver.py`。
- 当前测试基线不是 435 项，而是 **496 项**；其中已有 **8 项失败**（app 默认 `new_first` 与测试/Mock 的 hybrid 预期冲突，以及旧结构化测试的 fake hit 缺少 `page` 属性）。
- 正式 QA 原先没有接入教材/题库；`RetrievalReviewSession` 是先前的独立联调入口，未进入正式 QA/选择题。

## 2. 最小修改方案

1. UI 只显示两种简答模式：
   - 混合模式（默认）：本地 PPT/教材/题库 → 相关性判断 → 一次 DeepSeek；材料不足允许通用补充。
   - 本地模式：只检索本地材料，强制 `provider=local, allow_api=False`。
2. 新增薄适配层 `src/exam_materials.py`，只读复用：
   - `VersionedRetriever` 的 PPT 双版本；
   - `TextbookRetriever` 教材 BM25；
   - `query_questions()` 题库；
   - `RetrievalReviewSession` + 第三阶段冻结候选校准做相关性过滤。
   不重新生成教材向量，不重写题库或审核状态。
3. 混合模式无足够证据但存在部分材料时，把这些片段作为“背景”传给最多一次通用补充；页面单独展示本地部分材料。
4. 选择题检索 query 改为只使用题干，不使用选项文本；题库匹配仍可用选项做精确匹配。
5. UI 删除新版优先/通用问答入口；选择题固定混合模式。
6. 修复接管时已有 8 项失败，增加考试问答/选择题回归。

## 3. 简答题行为

### 混合模式（默认）

- 严格 PPT 证据优先；
- 扩展检索复用本地材料适配层，包含 PPT、教材 BM25 和题库候选；
- 直接相关/部分相关候选由 `review_results` 保留，相关性不等于充分性；
- 有足够课件证据：复用现有结构化 JSON 答案、引用校验、VERIFIED/UNVERIFIED；
- 只有部分材料：本次实现将其作为背景传给 DeepSeek 通用补充，不生成本地引用；
- 没有材料：DeepSeek 独立通用回答，同样标注未经课件核实；
- 一次提交最多一次模型调用，保留预算/API 总开关/无自动重试。

### 本地模式

- 强制 `QA_MODE_LOCAL`，调用 `_answer_courseware(mode='expanded', provider=local, allow_api=False)`；
- 不调用 DeepSeek；
- 展示证据、来源文件、PDF 物理页码和审核状态；
- 只有严格页足够时才生成完整摘录；未审核/部分页只作为相关线索或带风险标记。

## 4. 选择题行为

- 题库精确匹配仍优先，并保留选项重排映射；
- 题库未命中/待核实才走本地材料 + DeepSeek；
- **检索 query = 题干**，不再拼接所有选项，避免干扰项关键词污染证据召回；
- 模型提示中仍列出全部选项，要求返回选项字母和简短解析；
- 无证据时允许 DeepSeek 独立推理；
- 不编造题目缺失选项，答案只接受实际存在的选项字母；
- 题库待核实答案不使用历史学生作答冒充标准答案。

## 5. 修改文件

- `src/app.py`：简答模式只保留 hybrid/local；本地模式强制关闭 API；选择题固定混合模式；本地/教材来源 PDF 展示适配。
- `src/qa.py`：新增 `QA_MODE_LOCAL`；混合模式部分材料传给通用补充；保留既有三态/预算/结构化校验。
- `src/choice_solver.py`：题干核心概念检索，去掉选项拼 query。
- `src/exam_materials.py`：新增本地 PPT/教材/题库薄适配层。
- `src/corpus.py`：教材/题库 Page 的版本标签。
- `src/versioned_corpus.py`：教材/题库来源 PDF 路径解析（只读）。
- `src/cli.py`：增加 `--qa-mode local`。
- `tests/test_exam_qa.py`：新增混合/本地/无证据/本地材料测试。
- `tests/test_choice_solver.py`：新增题干检索、单选、多选测试。
- `tests/test_phase4_app.py`、`tests/test_dual_versions.py`、`tests/test_structured_answer.py`：修复接管前已有失败。
- `README.md`：当前模式与使用说明。

## 6. 测试结果

最终完整测试：

```text
518 passed, 5 warnings, 0 failed
```

安全诊断：

```text
224 passed, 2 deselected
```

日志：

- [`pytest.log`](pytest.log)
- [`api_diagnostics.log`](api_diagnostics.log)

接管时基线：496 项，8 失败；本次新增 7 项考试问答/选择题回归，并修复原有 8 项失败。

覆盖：

- 混合模式本地材料检索；
- 本地模式 0 次 DeepSeek；
- 无充分材料时通用补充；
- 无材料独立回答；
- 部分材料背景与本地证据区分；
- 单选；
- 多选；
- 题干检索不包含选项；
- 教材/PPT 本地材料适配；
- 原有三态、预算、API 门禁、题库/OCR 等测试。

## 7. 网页验收

```sh
cd /Users/along/Projects/Engineering-Ethics-RAG
source .venv/bin/activate
streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

1. 侧栏“回答模式”应只有两项，默认“混合模式（默认）”。
2. AI 关闭时：混合模式只走本地材料；本地模式始终不调用 DeepSeek。
3. 混合模式开启 AI：
   - 输入“工程风险的技术因素有哪些？”；
   - 查看是否出现本地 PPT/教材来源；
   - 若材料不足，查看“本地部分材料（未作为已验证依据）”和 AI 补充提示。
4. 本地模式：
   - 输入同一问题；
   - 确认没有 API 调用、没有 AI 按钮触发；
   - 查看证据来源、审核状态和 PDF 物理页码。
5. 选择题标签页：
   - 输入单选/多选；
   - 查看答案选项和解析；
   - 检查题库/课件来源。
6. 手机宽度下检查按钮和答案卡片不横向溢出。

## 8. Mock 与真实 API 的边界

- 本阶段测试全部为 Mock/Fake，无真实 DeepSeek 请求，无额外费用。
- 真实 API 的行为、教材相关性校准、题库实际答案仍需用户在本机人工验收。
- 第三阶段报告已说明相关性校准是“助手候选、非人工金标”；本适配层沿用该校准，未把它升级为生产安全标准。
- 教材使用现有 `TextbookRetriever` BM25，未重建 1461 条向量；这避免了重复编码，但也意味着没有在本阶段重新验证教材向量检索质量。

## 9. 剩余风险

1. 相关性校准来自第三阶段助手候选，不是人工金标；部分相关仍可能漏滤/误升。
2. 本地材料适配层把 PPT、教材和题库候选放在同一审查结果中，跨版本/跨来源结论的人工一致性仍需复核；未把“相关”升级为“充分”或 VERIFIED。
3. 教材目前只用 BM25 检索；现有教材向量缓存未重建也未接入本次适配层。
4. 题库在简答题中仅作为候选/诊断，不作为事实正文引用；选择题仍通过题库精确匹配和模型推理。
5. 真实 DeepSeek API 未参与本阶段验证；Mock 通过不等于真实 API 验收通过。
6. `QA_MODE_NEW_FIRST`、`QA_MODE_GENERAL`、`QA_MODE_RAG` 仍在引擎内部保留以兼容既有测试/旧调用；网页已只显示 hybrid/local。

## 10. 安全

- 未读取、打印或修改真实 `.env` / API Key。
- 未发起真实 DeepSeek API 请求；所有 API 测试使用 Mock。
- 未修改原始 PDF、`processed_v3`、教材向量、题库数据库或审核结论。
- 未自动 git add/commit/push。
- 已生成工作区快照：`backups/phase4_exam_qa_20261112-181058/`（本次修改后的受控快照；未覆盖其他智能体未提交改动）。
