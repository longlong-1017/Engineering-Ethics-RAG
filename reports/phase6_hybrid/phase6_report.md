# 第六阶段：智能混合问答与通用知识模式报告

日期：2026-11-08（Asia/Shanghai）  
项目：`/Users/along/Projects/Engineering-Ethics-RAG`  
约束：未发起真实付费 API 请求；未修改原始 PDF / `processed_v3`；未修改既有验收题目与评分标准；未推送远程仓库。

> 第七阶段已改为结构化 JSON 答案；见 [`structured_answer_report.md`](../phase7_structured/structured_answer_report.md)。

> 补充修复：混合调用顺序见 [`hybrid_flow_fix.md`](hybrid_flow_fix.md)；结论标签/无引用总结/第10条误拒绝见 [`conclusion_validation_fix.md`](conclusion_validation_fix.md)。

## 1. 目标与结论

新增三种回答模式，并在网页默认使用“智能混合问答”：

| 模式 | 行为 |
|---|---|
| **仅课件 RAG** | 只使用严格合格课件；证据不足返回“资料不足”，不调用通用知识。 |
| **智能混合问答（默认）** | 严格 RAG → 扩展 RAG → DeepSeek 通用知识；来源分开标注。 |
| **DeepSeek 通用问答** | 直接调用 DeepSeek 通用知识，不使用课件，不生成伪造引用/页码。 |

核心安全行为：

- 扩展检索中的未审核/C/E/未修复 B 页继续标记“需复核”，不当作已验证内容。
- 通用知识固定标记“AI 通用知识补充，未经课件核实”，不显示 `[S#]` 或 PDF 页码。
- 智能混合最多**一次模型调用**；严格/扩展阶段已经调用过模型（包括引用校验失败、模型拒答、超时、预算暂停）时，不会自动再调用通用知识。
- API 总开关、AI 开关、每日估算预算、密钥任一不满足时，不绕过限制。
- 不自动重试；第二次模型调用必须重新获得用户许可。

## 2. 三种模式流程

### 2.1 仅课件 RAG

`qa_mode=rag`：

1. 强制严格检索（只使用 A 类 + 已修复 B 类页）；
2. 证据足够则走课件答案（本地摘录或 DeepSeek 课件回答 + 引用校验）；
3. 证据不足直接返回“资料不足”，不调用通用知识。

### 2.2 智能混合问答（默认）

`qa_mode=hybrid`：

```text
严格 RAG
  ├─ 有答案 → 返回（来源：严格合格课件）
  └─ 资料不足
       ├─ 严格阶段曾调用 API / 受预算、开关限制 → 返回该结果，不再自动调用
       └─ 严格阶段未调用 API
            ↓
        扩展 RAG
          ├─ 有答案 → 返回（来源：扩展课件，未审核内容标“待复核”）
          └─ 资料不足
               ├─ 扩展阶段曾调用 API / 受限 → 返回该结果，不再自动调用
               └─ 扩展阶段未调用 API
                    ↓
              DeepSeek 通用知识（最多一次）
                ├─ 成功 → 返回（来源：AI 通用知识，未经课件核实）
                └─ 门禁关闭/失败 → 明确报错或返回“资料不足 + 原因”，不伪造答案
```

要点：

- 严格 RAG 命中时不会使用扩展页或通用知识。
- 扩展 RAG 命中时，来源标为“扩展课件（含未审核/待复核）”。
- 通用知识只在课件严格、扩展都没有证据时使用。
- 引用校验失败不会静默转通用知识：严格/扩展课件阶段已有模型调用，直接返回其本地回退或错误原因。
- 一次提交最多一次模型调用；不自动重试。

### 2.3 DeepSeek 通用问答

`qa_mode=general`：

1. 不检索课件，不读取 `search` 证据；
2. 直接调用 DeepSeek；
3. 通用知识回答固定标记“AI 通用知识补充，未经课件核实”；
4. 自动清理模型生成的伪造 `[S#]`、PDF 文件名、页码；
5. 不生成课件引用卡片，不知道页码就绝不编造页码。

## 3. 答案格式与来源分离

### 课件答案

- 保持原课件证据结构：要点/摘录 + `[S#]` + 真实 PDF 文件名和物理页码。
- 严格页显示“严格合格”；扩展未审核页显示“未审核/待复核”。
- 引用校验继续生效；失败时回退本地摘录并显示具体原因。

### 通用知识答案

通用知识提示词要求：

```text
【简明答案】
一两句话直接回答。

【分点说明】
1. ...
2. ...

【参考依据】
- AI 通用知识补充，未经课件核实。
```

本地后处理会：

- 去掉 `[S1]` 等引用编号；
- 去掉 `《...pdf》`、`.pdf`、`第 N 页`；
- 把“依据课件/根据资料”改为“依据通用知识”；
- 强制补充“AI 通用知识补充，未经课件核实；不提供 [S#] 课件引用或 PDF 页码”；
- 如果模型只输出引用说明而没有实质内容，拒绝并报错，不用课件内容冒充。

## 4. 代码结构

### `src/qa.py`

- 新增常量：`QA_MODE_RAG`、`QA_MODE_HYBRID`、`QA_MODE_GENERAL`，以及 `QA_MODE_LABELS`。
- `Answer` 新增：
  - `qa_mode`
  - `evidence_source`（strict/expanded/general/none）
  - `general_knowledge`
  - `model_calls`
  - `qa_mode_label`、`source_label`
- 公共 `answer(..., qa_mode=None)`：
  - `None` 保留旧行为，避免破坏已有测试；
  - `rag` 强制严格课件；
  - `hybrid` 执行严格 → 扩展 → 通用；
  - `general` 直接调用通用模型。
- 原严格/扩展课件流程抽为 `_answer_courseware()`，原有引用校验、预算、API 诊断和本地回退保持不变。
- 新增 `_answer_hybrid()`、`_answer_general()`、`_sanitize_general_answer()`。

### `src/app.py`

- 侧栏新增“回答模式”三选一，默认“智能混合问答”。
- 显示 `回答模式 / 证据来源 / 生成方式`。
- 通用知识答案显示“AI 通用知识补充，未经课件核实”，不显示课件证据卡片。
- 混合模式课件答案仍显示真实 `[S#]`、PDF 文件名和物理页码。
- API 总开关、预算、密钥门禁保持；通用模式未开 AI 时显示警告，提交不会绕过限制。

### `src/cli.py`

新增：

```sh
python -m src.cli ask "问题" --qa-mode rag
python -m src.cli ask "问题" --qa-mode hybrid
python -m src.cli ask "问题" --qa-mode general --allow-api
```

默认 `hybrid`；真实调用仍需 `--allow-api` 且本地总开关/密钥/预算满足。

## 5. Mock 验收

新增 `tests/test_qa_modes.py`，覆盖：

| 场景 | 断言 |
|---|---|
| 仅课件 RAG，无证据 | 资料不足，0 次模型调用 |
| 智能混合，严格页有证据 | 来源 strict，1 次调用，引用 p8 |
| 智能混合，严格不足、扩展有证据 | 来源 expanded，1 次调用，未审核警告 |
| 智能混合，严格/扩展都不足 | 来源 general，1 次调用，无 `[S#]`，有“AI 通用知识”标记 |
| 通用问答 | 不检索课件，无 citations，清理伪造 `[S#]`/PDF/页码 |
| 混合模式引用校验失败 | 仍为本地课件回退，不转通用知识，调用次数 1 |
| 混合模式 API 未授权 | 资料不足 + 原因，0 次调用 |
| 通用模式总开关 false | 错误，0 次 HTTP |
| 通用模式预算为 0 | 错误，0 次 HTTP |
| 通用模式缺密钥 | 错误，0 次 HTTP |
| 通用模式纯文本 | 自动补全【简明答案】【分点说明】【参考依据】结构 |

真实语料 + FakeClient（不联网）验证：

```text
严格问题：status=ok  source=strict   citations=p8   model_calls=1
扩展问题：status=ok  source=expanded citations=p18  warnings=含未审核提示
通用问题：status=ok  source=general  citations=[]   general=True
```

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

## 7. Streamlit 使用说明

### 启动

```sh
cd /Users/along/Projects/Engineering-Ethics-RAG
source .venv/bin/activate
streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

### 三种模式

1. **智能混合问答（默认）**
   - AI 关闭：只用课件；严格不足时扩展课件；仍不足返回资料不足。
   - AI 开启：严格课件 → 扩展课件 → 通用知识补充；最多一次模型调用。
   - 课件来源显示真实 PDF 文件名/页码；通用部分标“AI 通用知识补充，未经课件核实”。

2. **仅课件 RAG**
   - 只用 81 页严格合格课件。
   - 不调用扩展页，不调用通用知识。
   - 证据不足显示“资料不足”。

3. **DeepSeek 通用问答**
   - 不检索课件。
   - 直接使用通用知识。
   - 答案不含 `[S#]` 或 PDF 页码，固定标注“未经课件核实”。
   - 必须开启总开关、AI 开关并配置密钥；否则明确报错，不伪造答案。

### 验证真实大模型答案

1. 侧栏确认 API 总开关、AI toggle、预算/token 统计；
2. 打开 AI toggle（仅打开不请求）；
3. 选择“智能混合”或“DeepSeek 通用问答”；
4. 提交问题；
5. 查看：
   - `生成方式：DeepSeek · deepseek-flash`
   - `证据来源：严格合格课件 / 扩展课件 / AI 通用知识`
   - 课件答案的 `[S1]`、PDF 文件名、物理页码；
   - 通用答案的“AI 通用知识补充，未经课件核实”；
   - token 用量与预算估算。
6. 关闭 AI toggle 即回到离线/仅课件路径。

## 8. 修改文件清单

- `src/qa.py`：三种问答模式、严格/扩展先检索后调用、通用提示词、通用输出清洗、来源元数据、格式与单次调用控制。
- `src/evidence.py`：关系/联系题合并同主题互补页。
- `src/citations.py`：受限的简明总结句支持与无依据总结拒绝。
- `src/app.py`：回答模式三选一、来源标签、通用知识展示、证据分支、API 门禁提示。
- `src/cli.py`：`--qa-mode`、默认 hybrid、通用/混合调用参数。
- `tests/test_qa_modes.py`：新增 14 项模式 Mock 测试。
- `tests/test_citation_validation.py`：增加关系题总结句正向/反向测试。
- `tests/test_phase4_app.py`：Streamlit 三模式/门禁测试。
- `tests/run_api_diagnostics.py`：纳入模式测试。
- `README.md`：新增第六阶段说明与使用方式。
- `reports/phase6_hybrid/phase6_report.md`：本报告。
- `reports/phase6_hybrid/hybrid_flow_fix.md`：本次实际故障的补充修复报告。
- `reports/phase5_integration/pytest.log`、`api_diagnostics.log`：最新测试日志。

## 9. 安全与限制

- 未调用真实 DeepSeek API；未读取/输出/修改真实 `.env` 或 API Key。
- 未修改原始 PDF、`processed_v3`、既有验收题目或评分标准。
- 未关闭引用校验、每日预算保护或 API 总开关门禁。
- 未 git add/commit/push。
- 通用知识不是课件证据，不能标注为已审核；其学术正确性仍需人工核对。
- 智能混合避免自动二次调用；如用户希望第二次调用，必须在页面上重新操作/授权。
- 通用知识清理是安全后处理，不保证模型通用知识本身正确；它只保证不伪造课件引用。
