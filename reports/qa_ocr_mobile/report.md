# 简答题截图 OCR + 清空按钮 + 手机端体验优化报告

日期：2026-11-12  
范围：简答题 OCR 上传/回填、清空状态、移动端单列布局；未修改检索系统、教材向量、PDF、审核状态或选择题自动判断逻辑。

## 1. 检查结果

- Git 工作区包含其他智能体未提交改动，本轮未 reset/checkout/覆盖。
- 现有 `src/ocr.py` 已提供 `recognize_image()`，支持截图字节流；直接复用，没有引入新 OCR 系统。
- 选择题已有成熟的 uploader epoch + 文件哈希 + session_state 模式；简答题采用同样模式，但使用独立 key，互不影响。
- 原有简答题表单只有文本输入 + 提交；没有上传和清空状态层，且侧栏“清空当前结果”只清答案，不清题目/上传状态。

## 2. 简答题截图 OCR

### 实现

- 新增 `process_qa_upload()`：
  - 校验 PNG/JPG/JPEG；
  - 校验空文件；
  - 使用 `src.ocr.recognize_image(bytes)` 本地识别；
  - 只把文字写入 `session_state["question_input"]`；
  - 不触发提交、不调用 DeepSeek；
  - 成功/失败/空图片均显示明确提示。
- 使用文件 SHA-256：
  - 同一图片 rerun 不重复 OCR；
  - 用户手动修改后，rerun 不覆盖文本；
  - 新图片触发 OCR 并更新文本框。
- 使用独立 `qa_uploader_epoch`：
  - 清空后递增 uploader key，允许重新上传同一图片；
  - 不触碰选择题 uploader。
- OCR 临时文件由现有 `recognize_image()` 使用系统临时目录并清理，不写入项目仓库。

### 交互顺序

```text
上传截图 → 本地OCR → 回填可编辑文本框
        → 用户核对/修改
        → 点击“检索并回答”
```

上传本身不会自动提交。

## 3. 清空按钮

- 简答题输入框下方新增“清空题目”按钮，`type="secondary"`，与主提交按钮区分。
- `_clear_qa_state()`：
  - 清空 `question_input`；
  - 清除 `qa_uploaded_sig`、OCR 状态和上次答案/API 诊断；
  - 递增 `qa_uploader_epoch`，允许重新上传图片；
  - 不改变回答模式、AI 开关、预算或其他 session_state。
- 移除了侧栏旧的“清空当前结果”按钮，避免与题目清空混淆。
- 清空按钮是 `on_click` 回调，在控件实例化前修改 state，避免 Streamlit
  “控件创建后不能修改 session_state”异常。

## 4. 手机端与展示

- 简答题：上传、文本、提交、清空均为单列全宽。
- 选择题：搜索/清空改为纵向全宽；答案和来源不再并排两列。
- 新增移动端 CSS：
  - file uploader 100% 宽；
  - 表单按钮 100% 宽；
  - 输入框 16px 字号，避免 iOS 自动放大；
  - 长文本/代码块自动换行。
- 简答题最终“笔试精简答案”移动到状态提示之后、详细信息和风险之前，优先展示答案；详细分析、证据、风险、诊断保持可展开。

## 5. 测试

新增：

- `tests/test_qa_upload.py`：
  - OCR 成功回填；
  - OCR 失败保留手动文本；
  - 同一图片不重复 OCR/不覆盖手动修改；
  - 新图片替换；
  - 空图片、非法格式；
  - 清空保留模式/AI 开关；
  - 清空后同一图片可重新 OCR。
- `tests/test_phase4_app.py`：
  - 简答题清空按钮清空题目、保留模式；
  - 切换模式保留已输入题目；
  - 选择题默认自动判断仍通过。
- `tests/test_compact_display.py`：
  - 最终答案优先展示，风险提示随后。

完整测试：

```text
526 passed, 5 warnings, 0 failed
```

安全诊断：

```text
224 passed, 2 deselected
```

日志：

- [`pytest.log`](pytest.log)
- [`api_diagnostics.log`](api_diagnostics.log)

## 6. 修改文件

- `src/app.py`：简答题上传/OCR/清空状态、mobile 单列布局、最终答案优先、移除侧栏重复清空。
- `tests/test_qa_upload.py`：新增 OCR/清空回归。
- `tests/test_phase4_app.py`：清空/模式切换/选择题默认自动判断回归。
- `tests/test_compact_display.py`：最终答案优先顺序。
- `README.md`：当前能力说明。
- 本报告。

## 7. 网页验收

```sh
cd /Users/along/Projects/Engineering-Ethics-RAG
source .venv/bin/activate
streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

简答题标签页：

1. 上传一张 PNG/JPG/JPEG 题目截图：
   - 显示 OCR 识别进度；
   - 文字自动填入可编辑文本框；
   - 不会自动提交，也不会调用 DeepSeek。
2. 手动修改 OCR 文字后等待页面 rerun：
   - 同一图片不应覆盖手动修改。
3. 上传另一张图片：文本应更新为新识别内容。
4. 点击“清空题目”：
   - 文本、上传状态、OCR 状态、上次答案清空；
   - 回答模式保持不变；
   - 可重新上传同一张图片并再次识别。
5. 切换混合/本地模式：
   - 已输入文字不丢失；
   - 本地模式提交不调用 DeepSeek。
6. 点击“检索并回答”：
   - 显示“正在检索本地材料并生成答案…”进度；
   - 最终答案优先展示，详细分析/证据/风险/诊断在展开区。
7. 手机宽度：
   - 上传、输入、提交、清空单列；
   - 无横向滚动。

选择题标签页回归：

- 默认“自动判断”；
- 单选/多选/不确定逻辑未变；
- 搜索/清空按钮全宽单列。

## 8. 剩余风险

- OCR 依赖本地 `.build/vision_ocr` 引擎；引擎缺失或平台不支持时只能手动输入，页面会提示。
- OCR 文字质量受截图清晰度、表格/公式/手写影响；用户必须核对后再提交。
- 本次 OCR 测试使用 Mock，未对真实截图做视觉验收；真实引擎可用性需本机验证。
- 简答题最终“精简答案”依赖现有提取逻辑；无法无损提取时显示完整答案/风险，不强行生成标准答案。
- 清空会清除上次答案和诊断，但不会删除知识库、题库、日志或项目文件。
- 未重建教材向量、未修改 PDF/页码/审核状态，未自动提交 Git。
- 未读取或输出 API Key，未调用真实 DeepSeek API。
- 工作区快照：`backups/qa_ocr_mobile_20261112-185719/`。
