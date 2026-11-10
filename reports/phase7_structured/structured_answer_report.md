# 第七阶段：结构化 JSON 答案、统一渲染与事实校验

日期：2026-11-08  
项目：`/Users/along/Projects/Engineering-Ethics-RAG`

## 1. 问题与决定

真实 DeepSeek 返回后，引用校验器反复按自由文本中的 `[S#]` 位置判断：

- 第 1、3、5、7、9、11 条结论缺少引用；
- 结论/总结标签、自然语言总结、列表引导语不断触发新的误拒绝；
- 每当模型改写表达方式，就需要新增一个句式补丁。

决定停止针对单个句式打补丁，改为：

```text
DeepSeek 结构化 JSON
      ↓
JSON 解析 / 结构校验
      ↓
逐条事实与引用校验
      ↓
Python 统一渲染
      ↓
【简明答案】【分点论述】【总结】【参考依据】
```

自由文本 `[S#]` 不再承担“判断某条结论有没有引用”的职责。

## 2. 模型输出协议

`src/qa.py` 的课件提示词要求只返回一个 JSON 对象：

```json
{
  "summary": "简明结论",
  "points": [
    {
      "content": "第一条论述",
      "citations": ["S1", "S2"]
    }
  ],
  "conclusion": "总结",
  "insufficient": false
}
```

要求：

- 每条事实性论述和列表项都进入 `points`；
- 每条的引用只通过 `citations` 数组表达；
- 不允许把 `[S1]` 写进 `content` 代替 `citations`（解析时会移除并警告）；
- 只允许本次实际证据编号；
- 不允许模型生成 PDF 文件名或页码；
- 总结涉及新事实时，必须能由 points 的引用证据支持；
- 证据不足时返回 `insufficient: true`。

## 3. 解析、校验、渲染分离

新增 [`src/structured_answer.py`](../../src/structured_answer.py)。

### 3.1 结构解析

`parse_structured_answer()`：

- 支持纯 JSON、Markdown 代码块、前后少量说明；
- 检查必需字段与类型；
- 检查 points 非空（`insufficient=false` 时）；
- 规范化 `S1`、`[S1]`、`【S1】`；
- 拒绝不存在的 `[S#]`；
- 拒绝空 citations；
- 拒绝模型生成的 `.pdf`、`第 N 页`；
- 移除 content/summary/conclusion 中的内联 `[S#]`，并记录警告；
- 将结构格式错误与事实错误分开返回。

### 3.2 事实校验

`validate_structured_answer()`：

- 每条 points 单独校验；
- 引用的每一页都必须与论述有实质词项/数字重合；
- points 采用严格未知词检查，防止“出售客户记录”这类无证据短事实借引用通过；
- 数字、年份、金额必须精确出现在所引证据；
- summary/conclusion 对照所有 points 引用证据的并集校验；
- 总结新增数字、未知实体、无依据限定词会被拒绝；
- `insufficient=true` 不生成任何引用；
- 未审核证据仍由 QA 层加“需复核”警告，并在参考依据中显示审核状态。

### 3.3 统一渲染

`render_structured_answer()` 输出：

```text
【简明答案】
...

【分点论述】
1. ... [S1][S2]
2. ... [S1]

【总结】
...

【参考依据】
- [S1] 《真实文件名.pdf》第 X 页｜严格合格
- [S2] 《真实文件名.pdf》第 Y 页｜未审核
```

`[S#]` 只来自合法 citations 数组；PDF 文件名和物理页码只来自检索证据对象，模型无权生成。

### 3.4 安全诊断

- `Answer.model_raw_output` 保留模型原始输出（截断 4000 字）；
- `_safe_model_output()` 遮蔽 `sk-...` / `Bearer ...` 形式令牌；
- 网页“模型原始输出（诊断，截断/脱敏）”折叠展示；
- 不写入日志、不回显 API Key；
- 解析失败/事实校验失败时，可同时看到原始输出与具体拒绝原因。

## 4. API 路径行为

`_api_answer()` 现在：

1. 普通文本“资料不足” → `model_refused`；
2. 尝试 JSON 解析；
3. JSON 解析失败 → `citation_rejected`，回退本地摘录，显示具体原因；
4. `insufficient=true` → `model_refused`，状态资料不足；
5. 结构通过但事实校验失败 → `citation_rejected`，回退本地摘录；
6. 全部通过 → 渲染三段式考试答案，接受；
7. 任何路径最多一次模型调用，不自动重试；
8. API 失败/回退时仍显示“本次曾尝试 API”，本地摘录不会被伪装成 DeepSeek 答案。

## 5. 目标问题 Mock 重放

问题：

> 环境工程中的安全与社会公正有什么关系？

使用真实课件检索结果 + FakeClient（不联网）：

```text
status=ok
source=expanded
provider=deepseek
api_outcome=accepted
model_calls=1
citations=p28(未审核), p33(未审核), p34(严格)

【简明答案】环境工程中的安全与社会公正是相互关联的……
【分点论述】
1. 环境工程安全包括生产安全、公共安全和环境生态安全。 [S3]
2. 环境工程中的社会公正涉及资源和利益的分配。 [S2]
3. 环境公正应做到公平分配社会资源，分配不公会造成社会断裂。 [S1]
【总结】安全与公正是相互关联的，应同时考虑。
【参考依据】...
```

未审核页继续显示风险警告，不会被标为已验证。

## 6. 新增回归测试

[`tests/test_structured_answer.py`](../../tests/test_structured_answer.py) 覆盖：

- 多段 points、多页 citations、summary/conclusion；
- 未审核证据警告；
- JSON 代码块解析；
- 缺失字段、空 points；
- 不存在的 `S9`；
- 模型生成 PDF/页码；
- 内联 `[S#]` 被移除并要求 citations 数组；
- 错误数字；
- 未知实体；
- 无依据的 summary 数字；
- 无关的额外 citation；
- `insufficient=true`；
- JSON 解析失败回退、不转通用知识；
- 目标问题真实课件检索 Mock。

同时更新既有 API/Mock 测试为结构化 JSON，保留自由文本校验器的独立单元测试。

## 7. 测试结果

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

## 8. 修改文件

- `src/structured_answer.py`：新增 JSON 解析、结构校验、事实校验、统一渲染。
- `src/app.py`：模型原始输出安全诊断折叠展示。
- `src/citations.py`：新增 `assess_claim_support`，支持逐条严格校验。
- `src/qa.py`：结构化提示词、API 路径切换、结构化回退原因、脱敏原始输出。
- `tests/test_structured_answer.py`：新增 12 项结构化回归。
- `tests/test_qa.py`、`tests/test_phase3_evidence.py`、`tests/test_phase4_api.py`、`tests/test_api_diagnostics.py`、`tests/test_qa_modes.py`、`tests/test_citation_validation.py`、`tests/test_phase4_app.py`：Mock 返回改为 JSON。
- `tests/helpers.py`：新增 `structured_answer()` 测试构造器。
- `tests/run_api_diagnostics.py`：保持安全诊断范围（不含真实语料测试）。
- `README.md`、`reports/phase6_hybrid/phase6_report.md`：测试计数与阶段说明。

## 9. 网页验收

启动：

```sh
cd /Users/along/Projects/Engineering-Ethics-RAG
source .venv/bin/activate
streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

步骤：

1. 左侧选择“智能混合问答（默认）”。
2. 保持 AI toggle 关闭，先确认离线课件/资料不足路径不使用模型。
3. 配置好总开关/密钥/预算后，打开 AI toggle。
4. 提问：`环境工程中的安全与社会公正有什么关系？`
5. 预期：
   - 回答模式：智能混合问答
   - 证据来源：扩展课件（含未审核/待复核）
   - 生成方式：DeepSeek
   - `【简明答案】`、`【分点论述】`、`【总结】`、`【参考依据】`
   - 分点末尾的 `[S1]/[S2]/[S3]` 对应真实 PDF 文件名和 p28/p33/p34
   - 未审核页有“需复核”警告
   - token 统计只统计一次请求
6. 若模型未按 JSON 返回或引用无效：
   - 页面显示“结构化答案/事实校验失败”原因；
   - 回退本地摘录；
   - 不显示伪造的 DeepSeek 答案；
   - 通用知识模式不会被自动触发。

## 10. 安全状态

- 未调用真实 DeepSeek API；全部 FakeClient/FakeSession。
- 未读取、输出或修改真实 `.env` / API Key。
- 未修改原始 PDF、`data/processed_v3` 或既有评分标准。
- 保留每日 2 元预算、API 总开关、AI toggle、无自动重试。
- 一次提交最多一次模型调用。
- 未 git add/commit/push。
- 修改前备份：`backups/phase7_20261108-202046/`。
