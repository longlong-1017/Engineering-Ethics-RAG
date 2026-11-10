# 补充修复：结论标签、无引用总结与“第10条”误拒绝

日期：2026-11-08  
真实问题：`环境工程中的安全与社会公正有什么关系？`  
DeepSeek 已返回、消耗 1162 tokens，但系统回退本地摘录，错误包括：

> 第 1 条结论缺少 [S#] 引用：结论：现有证据只分别界定了……  
> 第 10 条结论缺少 [S#] 引用。

## 根因

1. **章节标签没有被剥离**
   - `结论：现有证据……` 被当成一条普通结论；
   - “结论：”是结构标签，不是独立事实；
   - 旧 `_strip_connectives` 没有处理“结论：”“简明答案：”。

2. **总结句没有“待核实”通道**
   - 旧校验只有“必须引用”或“整篇拒绝”两种结果；
   - 正常考试答案的“结论：”总结即使后文有充分引用，也会因为没有紧邻 `[S#]` 被整篇拒绝；
   - 模型有时把总结写成“第10条：……”，该标签被误当成数字 10，进一步导致数字校验失败。

3. **开头总结支持条件过窄**
   - 之前只允许第一条总结在非常严格的覆盖率下通过；
   - 自然语言改写（如“现有证据只分别界定了……”）容易低于阈值；
   - 于是整篇答案被拒绝，尽管后面每一条事实分点都有真实引用。

## 修复

### 1. 剥离结构标签

`src/citations.py` 的 `_strip_connectives` 现在识别并剥离：

- `结论：`
- `简明答案：`
- `总结：`、`分析：`、`论述：`、`答案：`、`要点：`
- `第10条：` 等编号结论标签
- `依据课件/根据资料/综上所述/参考来源` 等连接语

剥离后的正文才用于事实校验；标签本身不再被当成事实结论。

### 2. 总结句分级处理

- 若总结句由后文引用证据支持（至少 2 条已引用结论）→ 通过，不补引用。
- 若总结句没有单独引用，但：
  - 有 `结论/简明答案/综上/第N条` 等总结标签；
  - 后文至少 1 条有效引用；
  - 没有新增数字；
  - 没有新增 3 字以上实体；
  - 没有“冲突/所有/必然”等无依据限定词；
  - 长度不超过 180 字；
  
  则通过，但标记 **“总结句未单独标注引用，待核实”**。  
  **不自动添加 `[S#]`，不伪造引用。**
- 普通编号列表项缺引用仍拒绝。
- 无标签、非首条的普通事实句缺引用仍拒绝。

### 3. 提示词优化

`src/qa.py` 的课件提示词增加：

- 每个事实性结论和每个编号列表项必须带 `[S#]`；
- `结论：`/`简明答案：` 标签本身可无引用，但标签后的总结尽量并入有引用的分点，或明确标注“（待核实）”；
- 不得用无引用普通句承载具体数字、主体、时间、地点或因果；
- 输出适合研究生开卷考试：简明结论 → 分点论述 → 必要案例/分析 → 参考依据；
- 不要长篇复制课件原文。

### 4. 事实安全边界保持不变

继续拒绝：

- 不存在的 `[S9]`；
- 数字/金额/年份与所引证据不符；
- 新增 3 字以上未知主体；
- “所有、必然、冲突、无关”等无依据限定词；
- 编号列表项无引用；
- 无依据的“相互冲突”总结。

## Mock 重放本次失败结构

```text
问题：环境工程中的安全与社会公正有什么关系？
status=ok
source=expanded
provider=deepseek
api_outcome=accepted
model_calls=1
warnings=含未审核页面；2 条总结句待核实
citations=p28(未审核), p33(未审核), p34(严格)
```

模型答案中的：

- `结论：现有证据只分别界定了……` → 标记待核实，不补引用；
- `第10条：安全与公正是相互关联的……` → 标记待核实，不补引用；
- 每条有 `[S#]` 的分点继续逐条校验；
- 不再整篇回退。

## 回归测试

新增：

- `test_conclusion_label_summary_is_pending_not_rejected`
- `test_pending_summary_with_fake_number_is_rejected`
- `test_pending_summary_with_unknown_entity_is_rejected`
- `test_hybrid_accepts_grounded_conclusion_and_marks_uncited_summaries`
- `test_courseware_prompt_requires_citations_and_exam_structure`
- 原有“未引用列表项拒绝”“虚假引用/数字拒绝”“无依据冲突总结拒绝”继续通过。

## 测试结果

```text
273 passed, 5 warnings, 0 failed
```

安全诊断：

```text
171 passed, 2 deselected
```

日志：

- [`pytest.log`](../phase5_integration/pytest.log)
- [`api_diagnostics.log`](../phase5_integration/api_diagnostics.log)

## 修改文件

- `src/citations.py`：标签剥离、总结句待核实、严格事实边界。
- `src/qa.py`：课件提示词、引用校验 warnings 传递。
- `tests/test_citation_validation.py`：总结句正向/反向测试。
- `tests/test_qa_modes.py`：本次失败结构 Mock 重放、提示词测试。
- `README.md`、`reports/phase6_hybrid/phase6_report.md`：测试计数与说明。
- 本报告。

## 安全状态

- 未调用真实 DeepSeek API。
- 未读取、输出或修改真实 `.env` / API Key；测试使用虚构密钥和 FakeClient/FakeSession。
- 未修改原始 PDF、`processed_v3` 或既有评分标准。
- 未关闭引用校验、每日预算保护、API 总开关或 AI 开关。
- 未自动重试；一次提交最多一次模型调用。
- 未 git add/commit/push。
