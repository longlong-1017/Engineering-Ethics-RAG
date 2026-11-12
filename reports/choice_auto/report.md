# 选择题“自动判断”模式修复报告

日期：2026-11-12  
范围：只修改选择题模块、选择题 Streamlit UI 和对应测试；未修改简答题、教材向量、PDF、审核状态或其他检索模块。

## 0. 本次真实运行问题的根因

页面此前只显示统一的“模型返回空内容、无效 JSON 或不合法选项”，真实错误被 `ChoiceResponseError` 吞并，无法区分。代码层定位到三个具体问题：

1. **新旧 schema 二选一**
   只要响应包含 `question_type`，解析器就进入新 schema；若模型同时返回 `question_type + answer` 而缺少 `selected_options`，会被误判为非法，尽管 `answer` 是合法信息。

2. **字段形态过窄**
   - `selected_options` 只接受数组，字符串 `"AC"` 会被拒绝；
   - `option_analysis` 只接受覆盖全部选项的 dict，列表、布尔判断、以选项正文为 key 的变体都会失败；
   - 真实模型输出分布与 Mock 的精确 schema 不一致。

3. **缺少脱敏诊断**
   错误类型、实际模型名、原始响应预览没有保留，用户只能看到统一回退文案，无法区分：
   - 网络/API 错误；
   - 空响应；
   - JSON 解析失败；
   - 选项字段不合法。

因此本次不是放宽所有校验，而是：
- 兼容真实模型常见 JSON 变体；
- 对不完整逐项分析明确标记“不确定”，不假装完整；
- 保留显式单选、非法选项、空响应等硬校验；
- 增加脱敏诊断，下一次真实失败可直接看到错误码和原始响应预览。

## 1. 问题

旧实现：

- 未标注题型时 `parse_choice_text` 默认 `"单选"`；
- 模型旧 schema 只有一个 `answer` 字符串；
- 因此未标注的多选题容易被当成单选题，模型只返回一个选项。

## 2. 修复

### 2.1 题型

- 支持：`自动判断`、`单选`、`多选`。
- 未标注时默认 `自动`；不再预设单选。
- 题干明确 `[单选]/[多选]/单选题/多选题/单项选择题/多项选择题` 时优先遵循题干。
- Streamlit 选择题页面新增题型选择，默认 `自动判断`。

### 2.2 题库优先

- 自动模式可以匹配任意题库题型（题库作为题型来源）。
- 题库已核实题型和标准答案优先，保留原有选项乱序映射。
- 题干明确单选与题库答案数量冲突时不强行使用题库答案。
- 题库待核实仍走 AI/证据推理，不使用历史学生作答冒充标准答案。

### 2.3 自动模式与结构化输出

DeepSeek 提示词改为结构化 JSON：

```json
{
  "question_type": "single | multiple | uncertain",
  "selected_options": ["A", "C"],
  "option_analysis": {
    "A": "逐项判断理由",
    "B": "逐项判断理由"
  },
  "explanation": "简短解析",
  "uncertainty_reason": "不确定原因"
}
```

- 自动模式不预设单选；
- 逐项判断每个实际选项；
- 只有一个正确项 → `single`；
- 多个正确项 → `multiple`；
- 无法确定 → `uncertain`，保留建议答案并显示风险；
- 反向题（“不正确的是”“不包括”“错误的是”等）在用户提示中显式提醒；
- 每次提交最多一次 DeepSeek 调用，不额外调用题型识别。

### 2.4 程序校验

- `selected_options` 只能包含实际存在的选项；
- 新 schema 的 `option_analysis` 应覆盖全部实际选项；
  - 完整覆盖 → 正常解析；
  - 完全不提供/漏项 → 保留建议答案，但标记“不确定/逐项分析不完整”，不假装完整；
  - 类型非法、选项不存在、显式单选多选 → 安全回退，不默认 A，不默认单选；
- 显式单选必须恰好一个选项；
- 自动模式允许一个或多个；根据数量推断单选/多选；
- `uncertain` 保留建议答案并显示 `uncertainty_reason`；
- 兼容旧 schema 仅用于既有测试/旧客户端，不作为新提示词目标。

### 2.5 检索

- 仍只使用题干核心概念检索，不把选项拼进 query；
- 选项只进入模型提示，不污染证据召回。

## 3. 修改文件

- `src/choice_solver.py`：
  - 自动/单选/多选；
  - 题库题型/答案优先与冲突保护；
  - 新结构化 JSON 解析、逐项校验、反向题提示、安全回退；
  - 自动模式按正确项数量推断单/多选。
- `src/app.py`：
  - 选择题题型选择，默认“自动判断”；
  - 显示题型、建议答案（uncertain）、逐项判断和风险提示。
- `tests/test_choice_solver.py`：
  - 自动未标注多选、明确单选/多选、反向题、选项重排、题库待核实、无材料通用推理、无效 JSON/空内容/非法选项、漏项、题型不确定。
- `tests/test_phase4_app.py`：
  - 选择题页面默认“自动判断”。
- `README.md`、本报告。

## 4. 测试结果

完整测试：

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

## 4.1 错误诊断

`ChoiceSolution.diagnostic` 现在包含：

- `error_type`：`empty_content` / `json_not_found` / `json_parse` / `json_root` / `selected_type` / `selected_value` / `selected_missing` / `selected_empty` / `selected_missing_field` / `analysis_type` / `analysis_option` / `analysis_reason` / `explicit_single` / `schema` / API 错误 code；
- `model`：实际 `ChatResult.model`；
- `raw_preview`：脱敏、截断后的模型响应。

页面“选择题 AI 诊断（脱敏）”折叠区展示这些字段；日志只记录错误类型，不记录 API Key。

## 5. 人工验收

```sh
cd /Users/along/Projects/Engineering-Ethics-RAG
source .venv/bin/activate
streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

选择题标签页：

1. 确认题型选择默认是“自动判断”。
2. 输入未标注题型、但有两个正确项的多选题：
   - 预期答案包含多个字母；
   - 题型显示“多选”；
   - 解析中列出逐项判断。
3. 输入带 `[单选]` 的题目：
   - 只能有一个答案；
   - 模型返回多个时安全失败，不默认选 A。
4. 输入带 `[多选]` 的题目：允许多个答案。
5. 输入“以下不正确的是”反向题：检查提示和答案是否符合反向要求。
6. 输入题库原题（选项顺序打乱）：确认使用题库答案并正确映射字母。
7. 输入题库待核实题：确认标记待核实，不采用历史学生作答。
8. 输入无相关材料题：确认允许通用推理并明确来源。
9. 在 Mock 测试中模拟空内容、非法 JSON、非法选项、漏掉 option_analysis：
   - 页面应显示错误/风险；
   - 不应出现默认 A。

## 6. 剩余风险

- 真实 DeepSeek 是否稳定返回新 schema 仍需用户在本机人工验收；本阶段全部使用 Mock。
- 反向题依赖模型按提示逐项判断；程序不自动反转答案。
- 旧 schema 兼容路径仍存在，但新提示词使用新 schema。
- 题库题型/答案与题干显式冲突时，优先题干并走安全推理。
- 自动模式的 `uncertain` 仍会显示建议答案；页面已标注“建议答案”和风险。
- 未读取或修改真实 `.env` / API Key；未调用真实 API；未自动提交 Git。
