# 第八阶段：VERIFIED / UNVERIFIED / FAILED 三态修复报告

日期：2026-11-08  
项目：`/Users/along/Projects/Engineering-Ethics-RAG`  
根因分析：[`root_cause.md`](root_cause.md)

## 1. 目标

不再因为一条论述的词法校验失败而丢掉整篇 DeepSeek 答案。实现三个明确状态：

| 状态 | 含义 | 用户看到什么 |
|---|---|---|
| `VERIFIED` | 结构、引用合法性、数字和关键事实通过 | 结构化 AI 答案 + 真实 PDF 文件名/页码 + 已验证 |
| `UNVERIFIED` | AI 已生成可读答案，但存在未通过项 | AI 草稿 + “未经逐条事实核验” + 失败原因 + 检索证据 |
| `FAILED` | API 失败、JSON 不可解析、没有可用答案 | 离线摘录兜底 + 失败原因 |

## 2. 根因

详见 [`root_cause.md`](root_cause.md)。核心：

1. 词法覆盖被当成事实真伪判断；
2. 任意一条校验失败导致整篇回退；
3. 结构解析失败与部分事实未核验没有区分；
4. 缺少 UNVERIFIED 展示层；
5. Mock 使用贴近原文的短句，真实模型输出更长、更自然，分布不同。

## 3. 实现

### 3.1 `Answer` 三态字段

`src/qa.py` 新增：

- `VERIFICATION_VERIFIED`
- `VERIFICATION_UNVERIFIED`
- `VERIFICATION_FAILED`
- `Answer.verification_status`
- `Answer.verification_errors`
- `Answer.verification_label`
- `Answer.model_raw_output`（脱敏诊断）

### 3.2 解析保留可读草稿

`src/structured_answer.py`：

- JSON 解析失败 → 无草稿 → `FAILED`；
- JSON 可解析但结构/引用/事实有问题 → 保留 partial `StructuredAnswer`；
- 新增 `render_unverified_draft()`：
  - 展示 AI summary / points / conclusion；
  - 不输出真实 PDF 文件名/页码；
  - 模型引用编号只显示为“模型标注的引用编号（未核验，不关联 PDF 页码）”；
  - 列出未通过校验原因；
  - 移除模型自造页码/文件名。
- 通过校验时仍用 `render_structured_answer()`：
  - `【简明答案】`
  - `【分点论述】`
  - `【总结】`
  - `【参考依据】`
  - 真实 PDF 文件名、物理页码、审核状态。

### 3.3 API 决策

`src/qa.py`：

- 有效结构化答案 + 全部校验通过 → `VERIFIED`；
- 有可读答案但部分校验失败/结构问题 → `UNVERIFIED`，`provider=deepseek`，`citations=()`；
- JSON 无法解析或无可用文本 → `FAILED`，本地摘录兜底；
- API 异常 → `FAILED`；
- `insufficient=true` → `FAILED` / 资料不足；
- 一次提交最多一次模型调用；不自动重试。

`UNVERIFIED` 的引用处理：

- 不把模型 citations 写入 `Answer.citations`；
- 不生成真实 PDF 证据卡片；
- 草稿中只显示“模型标注引用编号（未核验）”；
- 检索到的课件证据在页面单独展示，供人工复核。

### 3.4 网页展示

`src/app.py`：

- 新增 `验证状态：已验证 / 未经核验的 AI 草稿 / 生成失败/离线回退`；
- `UNVERIFIED`：
  - 黄色警告“AI 生成草稿，未经逐条事实核验；不得作为已验证课件依据”；
  - 展示 AI 草稿；
  - 展示失败原因；
  - 单独展示“检索到的课件证据（未作为已验证依据）”；
- `FAILED`：
  - 明确“API 调用失败、返回不可解析或没有可用答案；已回退本地原文摘录”；
- API 诊断：
  - 支持 `unverified` / `unparseable` 结果；
  - 展示脱敏原始输出；
  - 保留 token/费用统计。

## 4. Mock 三态验收

新增 [`tests/test_verification_states.py`](../../tests/test_verification_states.py)：

- `VERIFIED`：真实引用、结构化段落、citations 非空；
- `UNVERIFIED`：错误数字仍保留 AI 草稿，`citations=()`，错误原因可见，检索证据存在；
- `UNVERIFIED`：不存在的 `S99` 不产生真实引用；
- `FAILED`：不可解析 JSON → 本地摘录，`api_outcome=unparseable`；
- `FAILED`：API 超时 → 本地摘录；
- 通用知识 → `UNVERIFIED`，明确未经课件核实。

Streamlit 回归：

- `tests/test_phase4_app.py` 新增未核验草稿页面测试：
  - 警告“AI 生成草稿”；
  - 显示错误数字 999 的 AI 草稿；
  - 显示“检索到的课件证据”；
  - 显示“未核验”。

## 5. 关键安全边界

`UNVERIFIED` 不是“通过”：

- 不生成真实 PDF 引用；
- 不显示“已验证”；
- 不把模型 citations 当课件依据；
- 仍显示失败原因和检索证据；
- 不自动补引用。

继续拒绝：

- 不存在的 `[S#]`；
- 错误数字/年份/金额；
- 明显新增主体；
- 无依据的强限定/行动词；
- 模型自造 PDF 文件名/页码。

不会为了通过测试而关闭全部校验。`VERIFIED` 仍需全部严格检查通过。

## 6. 测试结果

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

## 7. Mock 验收 vs 真实 API 验收

- 本阶段只完成 **Mock 验收**：FakeClient/FakeSession，无真实 DeepSeek 请求，无额外费用。
- 未读取、输出或修改真实 `.env` / API Key。
- 真实 API 输出仍可能触发 `UNVERIFIED`；这正是设计目标：保留答案并明确标记，而不是整篇回退。
- 真实 API 是否稳定返回合法 JSON、是否通过 VERIFIED，需要用户在本机显式配置并付费后进行真实验收；本报告不声称真实 API 已验证通过。

## 8. 修改文件

- `src/qa.py`：三态字段、UNVERIFIED 构造、FAILED 回退、result 诊断。
- `src/structured_answer.py`：partial 解析、未核验草稿渲染。
- `src/app.py`：三态展示、未核验证据区、诊断。
- `tests/test_verification_states.py`：新增 6 项三态测试。
- `tests/test_phase4_app.py`：新增未核验页面测试。
- 更新既有 API Mock 测试预期为 UNVERIFIED。
- `tests/run_api_diagnostics.py`：纳入三态测试。
- `README.md`、`reports/phase8_verification/root_cause.md`、本报告。

## 9. 网页验收

```sh
cd /Users/along/Projects/Engineering-Ethics-RAG
source .venv/bin/activate
streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

1. 左侧选择“智能混合问答（默认）”。
2. 关闭 AI：只走离线课件，确认不调用模型。
3. 打开 AI toggle，提问：
   - `环境工程中的安全与社会公正有什么关系？`
4. 若全部校验通过：
   - 显示“已验证”；
   - 显示结构化答案；
   - 显示真实 PDF 页码；
   - 显示严格/未审核状态。
5. 若部分校验失败：
   - 显示“未经核验的 AI 草稿”；
   - 显示 AI 原文和失败原因；
   - 显示“检索到的课件证据（未作为已验证依据）”；
   - 不显示为已验证的 PDF 引用。
6. 若 API/JSON 失败：
   - 显示“生成失败/离线回退”；
   - 显示本地摘录和失败原因。

## 10. 安全状态

- 未调用真实 DeepSeek API。
- 未读取、搜索、打印或修改真实 `.env` / API Key。
- 未修改原始 PDF、`data/processed_v3` 或审核结论。
- 保留每日 2 元预算、API 总开关、AI toggle、一次提交最多一次模型调用。
- 未 git add/commit/push。
- 修改前备份：`backups/phase8_20261108-212350/`。
