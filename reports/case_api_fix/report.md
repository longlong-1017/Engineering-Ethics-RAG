# 案例分析真实 API 截断与理论依据不足修复报告

日期：2026-11-12  
问题样本：挑战者号航天飞机事故，4 个设问。  
范围：`src/case_solver.py`、`src/deepseek_client.py`、`src/config.py`、`.env.example`、案例页面诊断和测试。未修改 PDF、教材向量或审核状态。

## 1. 根因

### 1.1 输出 Token 被全局上限截断

案例调用请求：

```text
client.chat(..., max_tokens=2400)
```

但 `DeepSeekClient` 实际发送：

```text
max_tokens = min(请求值, settings.max_output_tokens)
settings.max_output_tokens = 1000
```

因此 4 个设问、逐项事实边界和 3～5 个要点的 JSON 被限制在 1000 token，DeepSeek 返回：

```text
finish_reason = length
```

旧客户端把所有非 `stop` 的 finish_reason 统一变成：

```text
DeepSeekError(... code='invalid_response')
```

页面因此只显示：

```text
DeepSeek API失败（invalid_response）：回答被截断或未正常结束
```

这不是 JSON 格式错误，也不是网络错误，而是**输出长度截断**。

### 1.2 4 个设问全部“课件理论依据不足”的检索原因

案例适配层 `LocalMaterialsRetriever` 使用第三阶段相关性校准。案例检索 query 包含：

```text
挑战者号 + 1986 + 28 + 案例事实
```

校准特征（主题/关系/覆盖）因此把 PPT 理论页判为不相关，全部过滤。

实际本地检索检查：

```text
理论页存在（如风险、责任、安全类 PPT），
但带挑战者号专有事实的 query 被校准器过滤 -> 0 条理论证据。
```

所以不是“课件完全没有理论”，而是**案例事实词污染了理论检索 query**。

## 2. 修复

### 2.1 案例独立输出预算

- `Settings` 新增：

```text
case_max_output_tokens = 3600
```

- 环境变量：

```text
DEEPSEEK_CASE_MAX_OUTPUT_TOKENS=3600
```

- `solve_case` 只在创建本次案例客户端时使用该预算：

```python
DeepSeekClient(replace(config, max_output_tokens=case_tokens))
```

不改变简答题/选择题的全局 `max_output_tokens=1000`。

- 案例 Prompt 要求：
  - 每问先直接回答；
  - 每问 3～5 个要点；
  - 每问约 500 中文字以内；
  - 不重复理论、不凑要点。

### 2.2 finish_reason 错误分类

`DeepSeekClient` 现在区分：

| finish_reason | code | 含义 |
|---|---|---|
| `length` | `output_truncated` | 输出 Token 不足 |
| 其他非 `stop` | `finish_reason` | 模型未正常结束 |
| 空 content | `empty_response` | 空回答 |
| 非法 JSON/结构 | `invalid_response` | 响应结构异常 |
| 网络 | `network_error` | 网络失败 |
| HTTP 非 2xx | `http_error` | 服务端/认证/限流等 |

案例页面显示：

- `API 结果类型`
- HTTP 状态（若有）
- token usage（若有）
- 明确错误文本

不完整 JSON、缺失设问、错序/非法引用仍不会被标记成功。

### 2.3 理论检索与事实检索分离

`_retrieve_for_questions` 对每个设问做两次本地检索：

```text
理论 query = 理论关键词（不含事故专有细节）
事实 query = 设问核心概念 + 最多 4 个案例事实词
```

- 理论 query 避免“挑战者号/1986”等事故细节触发校准器过滤；
- 事实 query 用于召回类似案例/背景；
- 证据分类后按：
  ```text
  理论依据 → 背景补充 → 类似案例
  ```
  排序。
- 如果设问与案例都没有明确理论词，使用通用理论方向召回，不直接放弃：
  ```text
  工程伦理原则、责任伦理、风险治理、安全优先、工程师职业责任
  ```
- 如果最终仍没有理论页，才提示“课件理论依据不足”，不降低证据标准。

### 2.4 事实边界/简洁格式

- 调用前列出案例已知事实；
- Prompt 要求 `known_facts_used`、`inferences`、`unknowns`；
- 轻量标记：
  - 未提供报告情节却断言“未报告”；
  - 未提供签署情节却断言签署/拒签；
  - 事实不足却认定法律责任；
  - 引用类似案例；
  - 数字/长度风险。
- Prompt 限制每问 3～5 个要点，减少输出规模。

## 3. 测试结果

```text
556 passed, 5 warnings, 0 failed
```

安全诊断：

```text
224 passed, 2 deselected
```

新增/更新覆盖：

- 4 问案例一次调用、答案顺序/数量；
- 案例输出预算传给客户端（3600）；
- `finish_reason=length` -> `output_truncated`；
- 空响应 -> `empty_response`；
- JSON 错误/网络错误与截断区分；
- 不完整 JSON 不标记成功；
- 理论 query 不包含挑战者号/1986 等事故细节；
- 理论页优先于其他事故页；
- 4 问无理论时逐问提示；
- 既有简答题、选择题、OCR、预算测试全部通过。

## 4. 检索优化前后

### 之前（挑战者号类设问）

```text
query = 设问 + 案例事实（挑战者号、1986...）
LocalMaterialsRetriever 校准器判为不相关
-> 0 条理论证据
-> 4 问均“课件理论依据不足”
```

### 现在

```text
理论 query = 安全优先/责任伦理/风险治理...
理论 query 不含挑战者号/1986
-> 命中 PPT 理论页 -> theory
事实 query = 设问 + 少量案例事实
-> 召回类似案例/背景 -> similar/background
排序：theory -> background -> similar
```

本地挑战者号样本验证：

```text
4 个设问均有 theory 证据，理论不足提示不再出现。
```

## 5. 人工复测步骤

```sh
cd /Users/along/Projects/Engineering-Ethics-RAG
source .venv/bin/activate
streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

1. 上传/粘贴挑战者号案例，确认 4 个设问。
2. 开启 AI，提交一次：
   - 页面只应产生一次生成进度；
   - 若成功，4 问均应有答案；
   - 查看“API 结果类型”；成功应为 `accepted`，不应是 `output_truncated`。
3. 展开证据：
   - 应有“理论依据”标签；
   - 理论页应排在类似事故前；
   - 若仍无理论，应明确“课件理论依据不足”，不能编造。
4. 检查答案：
   - 每问 3～5 个要点；
   - 不把挑战者号与其他事故混写；
   - 没有报告/签署/法律事实时出现风险标记。
5. 如再次出现 `output_truncated`：
   - 说明真实输出仍超过 3600 token；
   - 可临时提高 `DEEPSEEK_CASE_MAX_OUTPUT_TOKENS`（上限 4096），或减少案例/设问；
   - 系统仍然不会把截断 JSON 当成功，也不会自动重试。

## 6. 剩余风险

- 3600 token 是当前建议值，不保证任意长案例/极长答案都不截断；`output_truncated` 会明确报告。
- 理论词表和证据分类是规则法，不等于语义检索质量验收；仍需人工核对 PPT 原文。
- `LocalMaterialsRetriever` 的校准仍是助手候选，不是人工金标。
- 真实 API 未在本阶段调用；真实模型 JSON 兼容性和答案质量需本机复测。
- 一次提交仍最多一次模型调用，不自动重试。
- 未读取/输出 API Key；未修改 PDF、页码、教材向量或审核状态；未 git commit/push。
