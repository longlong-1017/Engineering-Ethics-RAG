# 第五阶段：DeepSeek RAG 引用校验与 API 使用修复报告

日期：2026-11-08（Asia/Shanghai）  
项目：`/Users/along/Projects/Engineering-Ethics-RAG`  
约束：未发起真实付费 API 请求；未修改原始 PDF / `processed_v3`；未修改已有验收题目与评分标准；未推送远程仓库。

> **第六阶段更新（2026-11-08）**：新增智能混合问答与通用知识模式；当前完整测试 273 passed，安全诊断 171 passed。见 [第六阶段报告](../phase6_hybrid/phase6_report.md)。

> 真实 API 引导语误判的补充修复见 [`citation_guide_fix.md`](citation_guide_fix.md)。  
> “依据/根据资料/综上所述”等引用指针误判的补充修复见 [`citation_connective_fix.md`](citation_connective_fix.md)。

## 1. 接管时发现的问题

Git 仓库当前为 `main`，没有任何提交，所有文件均为未跟踪状态；没有远程推送。Codex 在修改每日预算/统计后留下：

- 2 个 `tests/test_phase4_app.py` 失败：页面已从逐题 checkbox 改为 AI toggle，但测试仍查找 checkbox。
- `DEEPSEEK_API_ENABLED=false` 的配置总开关可被网页 toggle 绕过：旧代码在页面内直接 `replace(settings, api_enabled=True)`。
- 引用校验仍要求模型结论**逐字**在原文中连续出现；模型准确归纳、合并或改写会被拒绝并回退，正是真实 API 答案无法采用的主要原因。
- README、`.env.example`、真实联调指南仍保留 `DEEPSEEK_MAX_REQUESTS=1`、每日 1 次等旧说明；请求次数硬限制代码实际已经取消，但文档和状态提示不一致。
- 费用预算代码本身已有本地估算、保护预留和原子账本；本阶段重点是补齐引用校验、总开关门禁和测试。

修改前已备份到：

`backups/phase5_20261108-190729/`

## 2. 修复内容

### 2.1 新的引用校验：允许归纳，不允许新增事实

新增 `src/citations.py`：

- 将 `【S1】`、`（S1）`、`[S1, S2]` 等常见写法规范为稳定的 `[S1]` / `[S1][S2]`。
- 逐条拆分模型结论，检查：
  1. 引用的 `[S#]` 必须来自本次提示词实际给出的证据编号；
  2. 每条事实性结论必须有引用；标题/过渡句可以无引用；
  3. 数字、金额、比例、年份必须与所引证据一致；
  4. 结论关键词必须与所引证据有足够重合；
  5. 多页引用的每一页都必须对结论有实质贡献；
  6. 引用页不能只是“同主题/同关键词”但与结论无关。
- 允许准确归纳、合并、改写；不再要求与原文逐字相同。例如：

  > “工程风险的技术因素主要有三类：零部件老化会造成功能失调，控制系统失灵会带来隐患，非线性作用也会引发安全风险。 [S1]”

  可以与该页原文不同，但会通过关键词、数字和引用页支持检查。
- 明确拒绝：

  > “允许公开所有客户信息。 [S1]”（新增事实/引用页不支持）  
  > “数据保管包括加密客户记录。 [S1] 还可以出售客户记录。”（未引用的新增结论）  
  > “工程风险包括技术因素。 [S9]”（不存在的编号）  
  > “9.75亿元。 [S1]”（数字与原文 2.75亿元 不符）

### 2.2 提示词改造

`src/qa.py` 的系统提示改为：

- 允许准确归纳、合并、改写；
- 禁止添加证据中没有的事实、数字、主体、时间、地点、因果或评价；
- 每条事实性结论必须带 `[S#]`；
- 只能用证据块实际给出的编号，编号可能不连续，必须原样使用；
- 多页支持同一结论时写 `[S1][S2]`；
- 每条引用必须实际支持该条结论；
- 标题/过渡句可以无引用，但不得包含事实结论；
- 证据不足只回答“资料不足”。

在用户提示中额外列出：

> 本次允许使用的证据编号仅限：`[S1]`、`[S3]`……。编号可能不连续，必须原样使用，不得新增编号。

### 2.3 校验失败不再当有效答案

`AnswerEngine._api_answer` 现在会：

- 调用 `validate_citations(...)`；
- 校验通过：`provider=deepseek`，保留 API 返回的 token/费用统计；
- 校验失败：`provider=local`，`api_outcome=citation_rejected`，回退到已核验的本地摘录；
- 在 `api_reason` 和网页警告中给出具体原因，例如：
  - `引用了不存在的证据编号：S9`
  - `第 2 条结论缺少 [S#] 引用：...`
  - `数字未在所引证据出现：9.75`
  - `结论与所引证据的关键词覆盖不足（33%）`
  - `引用 S2 与该条结论无实质重合`
- 不会把失败答案作为 DeepSeek 答案展示，也不会隐藏“API 已调用、已可能计费”的事实。

### 2.4 Streamlit 总开关与 AI toggle

- `DEEPSEEK_API_ENABLED` 现在是硬门禁：配置为 false 时，页面 toggle 禁用，不能从 UI 绕过。
- 页面使用“AI：DeepSeek RAG（关闭为离线摘录）”toggle：
  - toggle 本身不发送请求；
  - 打开后提交问题才调用；
  - 关闭后只走本地摘录；
  - 预算已达上限、账本不可用、缺少密钥或总开关关闭时，toggle 禁用并说明原因。
- 页面显示：
  - DeepSeek 生成：`已采用 DeepSeek 生成，并通过逐条引用校验的答案。`
  - API 失败/校验失败回退：明确的本地回退警告，而不是成功采用模型答案。
  - API 结果与下一次离线模式分开显示，不把上次结果混进新答案。

### 2.5 每日预算与请求统计

- **取消每日请求次数硬限制**：`RequestLimiter` 不再按次数拒绝；`DEEPSEEK_MAX_REQUESTS` 不再读取，旧构造参数 `max_requests` 仅为兼容，不用于限制。
- 保留：
  - UTC 日请求尝试次数；
  - prompt / completion / total token 统计；
  - 已知用量的费用估算；
  - 未知/在途用量的保护预留；
  - 跨进程 SQLite 账本（失败/超时也计数）。
- 默认每日预算 **2 元人民币**；网页可调整。金额是 `token × 配置单价` 的本地估算，**不是官方账单、不是账户级硬限额**。
- 不自动重试：HTTP 错误、超时、429、截断、无效 JSON 均直接失败并按需回退；请求失败/用量未知时保留保护预留，不伪装成零费用。
- 保留用户主动开关 AI；关闭即离线，不调用。
- `DeepSeek` 生成、API 失败、本地回退在 `provider`、`api_outcome`、`api_reason`、`api_accounting` 和网页状态中分开显示。

## 3. 新增/修改测试

新增 `tests/test_citation_validation.py`，使用虚构密钥和 `FakeClient` / `FakeSession`，不联网：

- 有效归纳（非逐字）通过；
- 无依据新增事实被拒绝；
- 缺少引用被拒绝；
- 不存在编号被拒绝；
- 部分引用（一条没引用）被拒绝；
- 多页引用通过；
- 多页中有一页与结论无实质重合时被拒绝；
- 数字题：2.75亿元通过，9.75/60/100亿元被拒绝；
- 全角/组合引用规范为 `[S1]`；
- Mock 数字题、简答题、案例分析题通过；
- Mock 多页引用通过；
- Mock 非法引用/无引用回退并保留具体原因；
- 提示词包含允许编号和归纳许可。

同时修复：

- `tests/test_phase4_app.py` 改为测试 AI toggle、总开关硬门禁、开关本身不请求、关闭后离线；
- `tests/test_api_diagnostics.py` 增加总开关状态断言；
- `tests/run_api_diagnostics.py` 纳入新引用测试；
- `tests/test_app.py`、`tests/test_real_corpus.py` 改为显式 `Settings`，避免测试读取真实 `.env`；
- README、`.env.example`、首次真实联调指南同步“无次数硬限制 / 默认预算 2 元 / AI toggle / 归纳校验”。

## 4. 测试结果

```sh
.venv/bin/python -m pytest -q
```

结果：**235 passed，5 warnings，0 failed**。日志见 [`pytest.log`](pytest.log)。

5 个 warning 为既有 PyMuPDF/SWIG 弃用提示；测试 fixture 继续禁止真实 HTTP，所有 DeepSeek 调用均为 FakeSession/Mock。测试中的 AppTest 与真实语料路径使用显式 `Settings`，dotenv 测试只使用临时目录合成值，不读取真实 `.env`。

安全诊断子集：

```sh
.venv/bin/python tests/run_api_diagnostics.py
```

结果：**147 passed，2 deselected**（排除 dotenv/gitignore 环境测试，避免触碰本地配置）。日志见 [`api_diagnostics.log`](api_diagnostics.log)。

## 5. 如何在 Streamlit 中验证“真正的大模型答案”

以下步骤需要你本人明确接受费用后执行；本报告没有执行真实请求。

1. **确认总开关与预算**
   - 本地 `.env` 中设置 `DEEPSEEK_API_ENABLED=true`、`DEEPSEEK_DAILY_BUDGET_CNY=2`、`DEEPSEEK_MODEL=deepseek-flash`；
   - 填入真实 `DEEPSEEK_API_KEY`（不要发到聊天、不要提交到 Git）；
   - 重启 Streamlit 进程（配置在进程内缓存）。

2. **启动网页**

   ```sh
   cd /Users/along/Projects/Engineering-Ethics-RAG
   source .venv/bin/activate
   streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
   ```

3. **先验证总开关**
   - 侧栏应显示 API 已配置、UTC 日尝试次数、token 统计、预算和保护预留；
   - 若 `DEEPSEEK_API_ENABLED=false`，AI toggle 应为禁用，不能从页面打开；
   - 页面关闭 AI 时提交问题，生成方式应为“离线原文摘录”，token 统计不增加。

4. **提交一个已知有严格证据的问题**
   - 选择“严格”范围；
   - 打开 AI toggle；
   - 提交例如：“工程风险的技术因素有哪些？”；
   - 预期看到：
     - `已采用 DeepSeek 生成，并通过逐条引用校验的答案。`
     - `生成方式：DeepSeek · deepseek-flash`
     - API token 用量；
     - 答案中的 `[S1]` 对应证据卡片，显示 PDF 文件名、物理页码 8；
     - 页面不出现“回退本地原文摘录”警告。

5. **故意验证失败路径（可选，仍会产生一次付费请求）**
   - 如果模型答案被判定为引用不通过，页面会显示：
     `API已返回，但答案未通过逐条引用校验：...已回退本地原文摘录。`
   - 这表示 API **已调用、可能已计费**，但不是有效模型答案；不能把它当成 DeepSeek 成功答案。
   - 若是 HTTP/超时/预算失败，会显示对应结构化错误；不会自动重试。

6. **关闭**
   - 关闭 AI toggle；
   - 将 `DEEPSEEK_API_ENABLED` 改回 `false` 并重启，或直接用 `DEEPSEEK_API_ENABLED=false` 启动；
   - 保留 `data/runtime/api_limits.sqlite3` 账本，核对 DeepSeek 账户实际用量和账单。

## 6. 残留限制

- 引用校验是保守的词法/数字/关键词检查，不是通用语义证明器；准确的同义改写仍可能被拒绝并回退，安全优先。
- 它只校验提示词中实际发送的证据块；模型若引用了检索结果但未列入证据块的页面，会被判为不存在编号。
- 每日预算是本地估算保护，不是账户级硬限额；其他设备/程序或删除账本不受保护。实际费用以官方账单为准。
- 真实模型答案的最终学术正确性仍需教师/人工核对，特别是 C/E/未审核页、B 类重排页和源资料疑点。
- 本阶段没有修改原始 PDF/JSON，也没有修改既有 30 题验收题目和评分标准。

## 7. 主要变更文件

- `src/citations.py`（新增）
- `src/qa.py`
- `src/app.py`
- `src/config.py`
- `src/api_limits.py`
- `src/cli.py`
- `src/deepseek_client.py`
- `src/evidence.py`
- `tests/test_citation_validation.py`（新增）
- `tests/test_phase4_app.py`、`tests/test_api_diagnostics.py`、`tests/run_api_diagnostics.py`
- `README.md`、`.env.example`、`reports/phase4_integration/首次真实联调指南.md`
- 本报告
- [`pytest.log`](pytest.log)、[`api_diagnostics.log`](api_diagnostics.log)、[`changes.json`](changes.json)、[`integrity_check.json`](integrity_check.json)

修改前备份：`backups/phase5_20261108-190729/`。

## 8. 结论

- 真实 API 答案不再因为“不是逐字原文”而被一律回退；准确归纳可通过引用校验。
- 不存在编号、未引用结论、数字不符、引用页不支持结论等仍会被拒绝，并显示具体原因。
- API 总开关、每日预算、AI toggle、失败/回退/DeepSeek 生成状态已分开。
- 请求次数硬限制已取消；token/尝试次数统计保留；默认预算 2 元为本地估算。
- 235 项测试通过，未发起真实付费请求，未修改原始数据和既有验收标准。
