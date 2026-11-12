"""选择题答题模块单元测试：格式解析、题库匹配、选项重排、未核实保护及API Mock。"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.choice_solver import (
    ParsedChoiceQuestion,
    ChoiceSolution,
    parse_choice_text,
    match_quiz_bank,
    solve_choice_question,
    solve_choice_raw_text,
)
from src.deepseek_client import ChatResult, DeepSeekError


def sample_bank():
    return [
        {
            "id": "1.5-01",
            "chapter": "1.5",
            "number": 1,
            "type": "单选",
            "question": "工程伦理教育是从什么时候开始开展的？",
            "options": {"A": "20世纪70年代", "B": "20世纪80年代", "C": "20世纪90年代", "D": "21世纪初"},
            "correct_answer": "C",
            "answer_status": "confirmed_from_screenshot",
            "verification_status": "source_reported_confirmed",
            "history": [{"user_answer": "C", "score": 5.0}],
            "pdf_sources": [{"pdf_filename": "test.pdf", "answer_page": 2, "question_pages": [1]}],
        },
        {
            "id": "1.5-02",
            "chapter": "1.5",
            "number": 2,
            "type": "多选",
            "question": "工程伦理责任的主体包括以下哪些？",
            "options": {"A": "政府机构", "B": "工程师个人", "C": "工程共同体", "D": "施工单位"},
            "correct_answer": "BC",
            "answer_status": "confirmed_from_screenshot",
            "verification_status": "source_reported_confirmed",
            "history": [{"user_answer": "BC", "score": 5.0}],
            "pdf_sources": [{"pdf_filename": "test.pdf", "answer_page": 2, "question_pages": [1]}],
        },
        {
            "id": "2.14-11",
            "chapter": "2.14",
            "number": 11,
            "type": "多选",
            "question": "根据工程伦理问题的对象,可见工程伦理问题大体分为以下几种情况：",
            "options": {
                "A": "因伦理意识缺失或者对行为后果估计不足导致的问题",
                "B": "因工程相关的各方利益冲突所造成的伦理困境",
                "C": "工程共同体内部意见不和导致的问题",
                "D": "工程共同体的伦理准则与规范等与其他伦理原则之间不一致导致的问题",
            },
            "correct_answer": None,
            "answer_status": "not_visible_in_screenshot",
            "verification_status": "pending",
            "history": [{"user_answer": "ABCD", "score": None}],
            "pdf_sources": [{"pdf_filename": "test.pdf", "answer_page": 4, "question_pages": [3]}],
        },
    ]


def test_parse_choice_text_various_formats():
    # 格式 1：带题号与全角括号
    t1 = """13.［多选］人道主义提倡关怀和尊重，主张人格平等。其原则包括：
    A. 遵守自然规律
    B. 不伤害原则
    C. 自主原则
    D. 遵从生态规律"""
    p1 = parse_choice_text(t1)
    assert p1.question_type == "多选"
    assert "人道主义" in p1.stem and not p1.stem.startswith("13")
    assert len(p1.options) == 4
    assert p1.options["B"] == "不伤害原则"

    # 格式 2：单行行内连续选项
    t2 = "处理工程与社会关系的基本原则是：A、社会公正 B、人道主义 C、和谐发展 D、环境保护"
    p2 = parse_choice_text(t2)
    assert p2.question_type == "自动"  # 未标注题型不得预设单选
    assert "基本原则" in p2.stem
    assert len(p2.options) == 4
    assert p2.options["A"] == "社会公正"
    assert p2.options["D"] == "环境保护"

    # 格式 3：空输入与无选项输入
    p3 = parse_choice_text("   ")
    assert p3.stem == "" and p3.options == {}


def test_match_quiz_bank_exact_and_reordering():
    bank = sample_bank()
    q = bank[0]  # correct_answer = "C" (20世纪90年代)

    # 1. 正常顺序匹配
    res = match_quiz_bank(q["question"], q["options"], "单选", bank)
    assert res["matched"] is True
    assert res["is_verified"] is True
    assert res["mapped_answer"] == "C"

    # 2. 乱序重排匹配：将 C 换到 A，A 换到 C
    shuffled_opts = {
        "A": "20世纪90年代",  # 原 C
        "B": "20世纪80年代",  # 原 B
        "C": "20世纪70年代",  # 原 A
        "D": "21世纪初",      # 原 D
    }
    res_shuffled = match_quiz_bank(q["question"], shuffled_opts, "单选", bank)
    assert res_shuffled["matched"] is True
    assert res_shuffled["is_verified"] is True
    assert res_shuffled["mapped_answer"] == "A"  # 成功映射到新 A 项

    # 3. 多选重排匹配：原 BC -> 打乱为 A: 工程师个人(原B), B: 政府机构(原A), C: 施工单位(原D), D: 工程共同体(原C)
    q2 = bank[1]  # correct_answer = "BC"
    shuffled_opts2 = {
        "A": "工程师个人",  # 原 B
        "B": "政府机构",    # 原 A
        "C": "施工单位",    # 原 D
        "D": "工程共同体",  # 原 C
    }
    res_shuffled2 = match_quiz_bank(q2["question"], shuffled_opts2, "多选", bank)
    assert res_shuffled2["matched"] is True
    assert res_shuffled2["is_verified"] is True
    assert res_shuffled2["mapped_answer"] == "AD"  # 原 BC 正确映射为 AD


def test_match_quiz_bank_pending_verification_safeguard():
    bank = sample_bank()
    q_pending = bank[2]  # 2.14-11, correct_answer is None, history ABCD

    res = match_quiz_bank(q_pending["question"], q_pending["options"], "多选", bank)
    assert res["matched"] is True
    assert res["is_verified"] is False
    assert res["mapped_answer"] is None  # 绝不可返回 ABCD
    assert "待核实" in res["warning"]


def test_solve_choice_question_bank_hit(monkeypatch):
    bank = sample_bank()
    monkeypatch.setattr("src.choice_solver.query_questions", lambda db_path: bank)

    q = bank[0]
    solution = solve_choice_question(
        stem=q["question"],
        options=q["options"],
        question_type="单选",
        allow_api=False,
    )
    assert solution.answer == "C"
    assert solution.verified is True
    assert "学习通题库" in solution.source
    assert solution.bank_id == "1.5-01"


def test_solve_choice_question_mock_deepseek(monkeypatch):
    # 模拟题库未命中
    monkeypatch.setattr("src.choice_solver.query_questions", lambda db_path: [])

    # 模拟 Retriever
    mock_hit = MagicMock()
    mock_hit.rank = 1
    mock_hit.page.filename = "01绪论.pdf"
    mock_hit.page.page_number = 42
    mock_hit.snippet = "人道主义包含不伤害原则与自主原则。"
    mock_hit.page.page_status_label = "严格合格"
    mock_retriever = MagicMock()
    mock_retriever.search.return_value = MagicMock(hits=[mock_hit])

    # 模拟 DeepSeekClient
    mock_client = MagicMock()
    mock_client.chat.return_value = ChatResult(
        content=json.dumps({
            "answer": "BC",
            "analysis": "根据课件[S1]，人道主义包含不伤害原则和自主原则。",
            "evidence_cited": ["S1"],
            "insufficient_evidence": False,
        }),
        model="deepseek-flash",
        usage={"total_tokens": 120},
    )

    mock_settings = MagicMock()
    mock_settings.api_enabled = True
    mock_settings.deepseek_configured = True

    solution = solve_choice_question(
        stem="人道主义的两条基本原则是：",
        options={"A": "社会公正", "B": "不伤害原则", "C": "自主原则", "D": "生态规律"},
        question_type="多选",
        retriever=mock_retriever,
        settings=mock_settings,
        allow_api=True,
        client=mock_client,
    )

    assert solution.answer == "BC"
    assert solution.verified is False
    assert "DeepSeek推断" in solution.source
    assert len(solution.evidence_context) == 1
    assert "01绪论.pdf" in solution.evidence_context[0]["filename"]


def test_solve_choice_question_pending_bank_falls_through_to_ai(monkeypatch):
    bank = sample_bank()
    monkeypatch.setattr("src.choice_solver.query_questions", lambda db_path: bank)

    mock_client = MagicMock()
    mock_client.chat.return_value = ChatResult(
        content=json.dumps({
            "answer": "ABCD",
            "analysis": "经课件证据全面论证，全选。",
            "evidence_cited": ["S1"],
            "insufficient_evidence": False,
        }),
        model="deepseek-flash",
        usage={"total_tokens": 150},
    )

    mock_settings = MagicMock()
    mock_settings.api_enabled = True
    mock_settings.deepseek_configured = True

    q_pending = bank[2]
    solution = solve_choice_question(
        stem=q_pending["question"],
        options=q_pending["options"],
        question_type="多选",
        settings=mock_settings,
        allow_api=True,
        client=mock_client,
    )

    # 虽最终由AI判断为ABCD，但明确标明是待核实AI推断，而非已核实题库答案
    assert solution.verified is False
    assert "待核实" in solution.source
    assert solution.bank_id == "2.14-11"


def test_solve_choice_question_input_validation_and_api_failure(monkeypatch):
    monkeypatch.setattr("src.choice_solver.query_questions", lambda db_path: [])

    # 1. 题干为空
    s1 = solve_choice_question("", {"A": "1", "B": "2"})
    assert s1.answer is None and "题干" in s1.warning

    # 2. 选项不足两个
    s2 = solve_choice_question("题干内容", {"A": "单个选项"})
    assert s2.answer is None and "至少" in s2.warning

    # 3. API 异常回退
    mock_client = MagicMock()
    mock_client.chat.side_effect = DeepSeekError("网络超时异常")
    mock_settings = MagicMock()
    mock_settings.api_enabled = True
    mock_settings.deepseek_configured = True

    s3 = solve_choice_question(
        stem="工程伦理问题包括：",
        options={"A": "选项A", "B": "选项B"},
        settings=mock_settings,
        allow_api=True,
        client=mock_client,
    )
    assert s3.answer is None
    assert "失败" in s3.warning or "未成功" in s3.source


def test_solve_choice_raw_text_bank_hit_and_validation(monkeypatch):
    bank = sample_bank()
    monkeypatch.setattr("src.choice_solver.query_questions", lambda db_path: bank)

    # 1. 直接传入整段题目文本（单文本框形式）
    raw_text = """工程伦理教育是从什么时候开始开展的？
    A. 20世纪70年代
    B. 20世纪80年代
    C. 20世纪90年代
    D. 21世纪初"""
    sol = solve_choice_raw_text(raw_text)
    assert sol.answer == "C"
    assert sol.verified is True
    assert "学习通题库" in sol.source

    # 2. 文本缺少选项
    sol_no_opts = solve_choice_raw_text("工程伦理教育是从什么时候开始开展的？")
    assert sol_no_opts.answer is None
    assert "选项" in sol_no_opts.warning

    # 3. 文本为空
    sol_empty = solve_choice_raw_text("   ")
    assert sol_empty.answer is None
    assert "空" in sol_empty.warning

    # 4. 选项乱序文本直接解答
    raw_shuffled = """工程伦理教育是从什么时候开始开展的？
    A. 20世纪90年代
    B. 20世纪80年代
    C. 20世纪70年代
    D. 21世纪初"""
    sol_shuffled = solve_choice_raw_text(raw_shuffled)
    assert sol_shuffled.answer == "A"  # 原 C 项重排到了 A
    assert sol_shuffled.verified is True


def test_upload_ocr_autofill_and_session_state_preservation(monkeypatch):
    import hashlib
    from src.ocr import OCRResult

    session_state = {"choice_unified_text_area": ""}

    mock_file1 = MagicMock()
    mock_file1.getvalue.return_value = b"fake_png_data_1"

    ocr_calls = []
    def mock_recognize(raw_bytes, **kwargs):
        ocr_calls.append(raw_bytes)
        return OCRResult(status="ok", text="1. 处理工程与人关系的基本原则是：\nA. 社会公正\nB. 人道主义\nC. 和谐发展\nD. 环境保护")

    # 1. 首次上传图片
    file_bytes = mock_file1.getvalue()
    file_sig = hashlib.sha256(file_bytes).hexdigest()
    if session_state.get("last_uploaded_file_sig") != file_sig:
        session_state["last_uploaded_file_sig"] = file_sig
        ocr_res = mock_recognize(file_bytes)
        if ocr_res.status == "ok" and ocr_res.text.strip():
            session_state["choice_unified_text_area"] = ocr_res.text

    assert len(ocr_calls) == 1
    assert "人道主义" in session_state["choice_unified_text_area"]

    # 2. 用户手动修改文本框内容
    session_state["choice_unified_text_area"] = "用户修改后的题目内容：\nA. 选项甲\nB. 选项乙"

    # 3. 页面 rerun，相同文件不触发 OCR，保留用户修改
    if session_state.get("last_uploaded_file_sig") != file_sig:
        session_state["choice_unified_text_area"] = "不应覆盖"

    assert len(ocr_calls) == 1
    assert "用户修改后的题目内容" in session_state["choice_unified_text_area"]

    # 4. 上传新图片，触发重新识别并回填
    mock_file2 = MagicMock()
    mock_file2.getvalue.return_value = b"fake_png_data_2"
    file_bytes2 = mock_file2.getvalue()
    file_sig2 = hashlib.sha256(file_bytes2).hexdigest()

    def mock_recognize2(raw_bytes, **kwargs):
        ocr_calls.append(raw_bytes)
        return OCRResult(status="ok", text="新题目内容：\nA. 新A\nB. 新B")

    if session_state.get("last_uploaded_file_sig") != file_sig2:
        session_state["last_uploaded_file_sig"] = file_sig2
        ocr_res2 = mock_recognize2(file_bytes2)
        if ocr_res2.status == "ok" and ocr_res2.text.strip():
            session_state["choice_unified_text_area"] = ocr_res2.text

    assert len(ocr_calls) == 2
    assert "新题目内容" in session_state["choice_unified_text_area"]



# ---------------------------------------------------------------------------
# 「清空」按钮相关测试（模拟 _clear_choice_state 逻辑）
# ---------------------------------------------------------------------------

def _simulate_clear(session_state: dict) -> None:
    """与 src/app.py::_clear_choice_state 相同的逻辑，用于离线测试。"""
    session_state["choice_unified_text_area"] = ""
    session_state.pop("last_choice_solution", None)
    session_state.pop("last_uploaded_file_sig", None)
    session_state["choice_uploader_epoch"] = (
        session_state.get("choice_uploader_epoch", 0) + 1
    )


def test_clear_after_manual_input():
    """手动输入文字后点击清空，文本框变空，答案消失。"""
    session_state = {
        "choice_unified_text_area": "手动输入的题目",
        "last_choice_solution": object(),  # 任意非 None 对象
        "choice_uploader_epoch": 0,
    }
    _simulate_clear(session_state)
    assert session_state["choice_unified_text_area"] == ""
    assert "last_choice_solution" not in session_state


def test_clear_after_ocr_autofill():
    """OCR 回填后点击清空，文本框变空，OCR sig 被清除，epoch 递增。"""
    session_state = {
        "choice_unified_text_area": "OCR识别的题目内容",
        "last_uploaded_file_sig": "abc123",
        "last_choice_solution": object(),
        "choice_uploader_epoch": 0,
    }
    _simulate_clear(session_state)
    assert session_state["choice_unified_text_area"] == ""
    assert "last_uploaded_file_sig" not in session_state
    assert "last_choice_solution" not in session_state
    assert session_state["choice_uploader_epoch"] == 1


def test_clear_resets_uploader_epoch():
    """多次清空，epoch 应单调递增，确保每次 uploader key 唯一。"""
    session_state = {"choice_uploader_epoch": 3}
    _simulate_clear(session_state)
    assert session_state["choice_uploader_epoch"] == 4
    _simulate_clear(session_state)
    assert session_state["choice_uploader_epoch"] == 5


def test_clear_allows_reupload_same_image():
    """清空后 epoch 递增，新 uploader 组件不保留旧 sig，可重新上传相同图片触发 OCR。"""
    import hashlib as _hashlib
    from unittest.mock import MagicMock
    from src.ocr import OCRResult

    file_bytes = b"fake_png_data_same"
    file_sig = _hashlib.sha256(file_bytes).hexdigest()

    session_state: dict = {
        "choice_unified_text_area": "旧 OCR 结果",
        "last_uploaded_file_sig": file_sig,  # 已识别过
        "last_choice_solution": object(),
        "choice_uploader_epoch": 0,
    }

    ocr_calls = []

    def mock_recognize(raw_bytes, **kwargs):
        ocr_calls.append(raw_bytes)
        return OCRResult(status="ok", text="重新识别的题目")

    # 清空（epoch 递增，sig 被清除）
    _simulate_clear(session_state)
    assert "last_uploaded_file_sig" not in session_state

    # 再次上传相同图片：sig 与 session_state 中不一致（已清除），应触发 OCR
    if session_state.get("last_uploaded_file_sig") != file_sig:
        session_state["last_uploaded_file_sig"] = file_sig
        ocr_res = mock_recognize(file_bytes)
        if ocr_res.status == "ok" and ocr_res.text.strip():
            session_state["choice_unified_text_area"] = ocr_res.text

    assert len(ocr_calls) == 1
    assert "重新识别的题目" in session_state["choice_unified_text_area"]


def test_clear_then_new_input_and_search(monkeypatch):
    """清空后直接输入新题目并搜索，不受旧答案干扰。"""
    from src.choice_solver import solve_choice_raw_text, ChoiceSolution

    session_state: dict = {
        "choice_unified_text_area": "",
        "choice_uploader_epoch": 1,
        # 清空后不应存在旧答案
    }
    assert "last_choice_solution" not in session_state

    # 输入新题目后搜索（mock match_quiz_bank 未命中，mock solve_choice_question 返回答案）
    new_text = "工程师的基本职责是：\nA. 对雇主负责\nB. 对社会公众负责\nC. 追求个人利益\nD. 听从上级指令"
    monkeypatch.setattr(
        "src.choice_solver.match_quiz_bank",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr(
        "src.choice_solver.solve_choice_question",
        lambda *a, **kw: ChoiceSolution(
            answer="B",
            analysis="工程师首要责任是保护公众安全与福祉。",
            source="AI推断",
            source_detail="",
            verified=False,
            confidence="medium",
        ),
    )
    solution = solve_choice_raw_text(new_text, retriever=None, settings={}, allow_api=True)
    session_state["last_choice_solution"] = solution
    assert session_state["last_choice_solution"].answer == "B"


def test_clear_no_error_when_state_already_empty():
    """清空操作在 session_state 为空时不应抛出异常。"""
    session_state: dict = {}
    _simulate_clear(session_state)  # 不应抛出 KeyError
    assert session_state["choice_unified_text_area"] == ""
    assert session_state["choice_uploader_epoch"] == 1


def _mock_choice_client(answer="A"):
    client = MagicMock()
    client.chat.return_value = ChatResult(
        content=json.dumps({
            "answer": answer,
            "analysis": "根据课件证据 [S1] 作出判断。",
            "evidence_cited": ["S1"],
            "insufficient_evidence": False,
        }),
        model="deepseek-flash",
        usage={"total_tokens": 50},
    )
    return client


def test_choice_retrieval_uses_stem_only_not_option_keywords(monkeypatch):
    monkeypatch.setattr("src.choice_solver.query_questions", lambda db_path: [])
    hit = MagicMock()
    hit.rank = 1
    hit.page.filename = "合成课件.pdf"
    hit.page.page_number = 8
    hit.snippet = "工程伦理责任主体包括工程师个人。"
    hit.page.page_status_label = "严格合格"
    retriever = MagicMock()
    retriever.search.return_value = MagicMock(hits=[hit])
    settings = MagicMock(api_enabled=True, deepseek_configured=True)
    stem = "工程伦理责任的主体包括哪些？"
    options = {"A": "政府机构", "B": "工程师个人", "C": "工程共同体", "D": "施工单位"}
    solution = solve_choice_question(
        stem=stem, options=options, question_type="多选",
        retriever=retriever, settings=settings, allow_api=True,
        client=_mock_choice_client("BC"),
    )
    assert solution.answer == "BC"
    called_query = retriever.search.call_args[0][0]
    assert called_query == stem
    assert "政府机构" not in called_query
    assert "施工单位" not in called_query


@pytest.mark.parametrize("question_type,answer", [("单选", "A"), ("多选", "BD")])
def test_single_and_multi_choice_return_valid_option_letters(monkeypatch, question_type, answer):
    monkeypatch.setattr("src.choice_solver.query_questions", lambda db_path: [])
    hit = MagicMock()
    hit.rank = 1
    hit.page.filename = "合成课件.pdf"
    hit.page.page_number = 8
    hit.snippet = "合成课堂证据。"
    hit.page.page_status_label = "严格合格"
    retriever = MagicMock()
    retriever.search.return_value = MagicMock(hits=[hit])
    settings = MagicMock(api_enabled=True, deepseek_configured=True)
    solution = solve_choice_question(
        stem="合成题干？", options={"A": "甲", "B": "乙", "C": "丙", "D": "丁"},
        question_type=question_type, retriever=retriever, settings=settings,
        allow_api=True, client=_mock_choice_client(answer),
    )
    assert solution.answer == answer
    assert solution.verified is False
    assert solution.analysis


def _structured_choice(answer, options, qtype="multiple", reason="", analysis="综合解析"):
    return json.dumps({
        "question_type": qtype,
        "selected_options": list(answer),
        "option_analysis": {
            key: ("该选项符合题干。" if key in answer else "该选项不符合题干。")
            for key in sorted(options)
        },
        "explanation": analysis,
        "uncertainty_reason": reason,
    }, ensure_ascii=False)


def _choice_engine(monkeypatch, content, *, bank=None, hits=True):
    monkeypatch.setattr("src.choice_solver.query_questions", lambda db_path: list(bank or []))
    retriever = MagicMock()
    if hits:
        hit = MagicMock()
        hit.rank = 1
        hit.page.filename = "合成课件.pdf"
        hit.page.page_number = 8
        hit.snippet = "工程伦理选项判断的合成证据。"
        hit.page.page_status_label = "严格合格"
        hit.page.version_label = "旧版·补充"
        retriever.search.return_value = MagicMock(hits=[hit])
    else:
        retriever.search.return_value = MagicMock(hits=[])
    client = MagicMock()
    client.chat.return_value = ChatResult(content=content, model="deepseek-flash", usage={"total_tokens": 80})
    settings = MagicMock(api_enabled=True, deepseek_configured=True)
    return retriever, client, settings


def test_auto_unmarked_multi_infers_multiple_and_preserves_all_options(monkeypatch):
    options = {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}
    retriever, client, settings = _choice_engine(
        monkeypatch, _structured_choice("AC", options), hits=True
    )
    solution = solve_choice_question(
        "未标注题型但可能有多项正确的题目？", options, question_type="自动",
        retriever=retriever, settings=settings, allow_api=True, client=client,
    )
    assert solution.answer == "AC"
    assert solution.question_type == "多选"
    assert set(solution.option_analysis) == set(options)
    assert client.chat.call_count == 1


def test_explicit_single_and_multiple_are_respected(monkeypatch):
    options = {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}
    retriever, client, settings = _choice_engine(
        monkeypatch, _structured_choice("BC", options, qtype="multiple")
    )
    single = solve_choice_question(
        "明确单选题？", options, question_type="单选",
        retriever=retriever, settings=settings, allow_api=True, client=client,
    )
    assert single.answer is None
    assert "单选题必须恰好一个" in single.warning

    multiple = solve_choice_question(
        "明确多选题？", options, question_type="多选",
        retriever=retriever, settings=settings, allow_api=True, client=client,
    )
    assert multiple.answer == "BC"
    assert multiple.question_type == "多选"


def test_reverse_question_is_flagged_in_prompt(monkeypatch):
    options = {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}
    retriever, client, settings = _choice_engine(
        monkeypatch, _structured_choice("D", options, qtype="single")
    )
    solution = solve_choice_question(
        "以下关于工程伦理的说法，不正确的是？", options, question_type="自动",
        retriever=retriever, settings=settings, allow_api=True, client=client,
    )
    prompt = client.chat.call_args[0][0][1]["content"]
    assert "反向选择题" in prompt
    assert solution.answer == "D"


def test_uncertain_type_keeps_suggestion_and_warns(monkeypatch):
    options = {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}
    retriever, client, settings = _choice_engine(
        monkeypatch,
        _structured_choice("A", options, qtype="uncertain", reason="证据不足，无法确认是否还有其他正确项"),
    )
    solution = solve_choice_question(
        "证据不足的题目？", options, question_type="自动",
        retriever=retriever, settings=settings, allow_api=True, client=client,
    )
    assert solution.answer == "A"
    assert solution.question_type == "不确定"
    assert "证据不足" in solution.uncertainty_reason
    assert "题型不确定" in solution.warning


def test_invalid_or_empty_json_never_defaults_to_a(monkeypatch):
    options = {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}
    for content in ("", "not json", '{"question_type":"single","selected_options":["E"],"option_analysis":{},"explanation":"x"}'):
        retriever, client, settings = _choice_engine(monkeypatch, content)
        solution = solve_choice_question(
            "无效响应的题目？", options, question_type="自动",
            retriever=retriever, settings=settings, allow_api=True, client=client,
        )
        assert solution.answer is None
        assert "A" not in (solution.answer or "")
        assert "失败" in solution.warning


def test_incomplete_option_analysis_is_marked_uncertain_not_silent(monkeypatch):
    options = {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}
    content = json.dumps({
        "question_type": "single",
        "selected_options": ["A"],
        "option_analysis": {"A": "正确"},
        "explanation": "解析",
        "uncertainty_reason": "",
    }, ensure_ascii=False)
    retriever, client, settings = _choice_engine(monkeypatch, content)
    solution = solve_choice_question(
        "逐项判断缺失的题目？", options, question_type="自动",
        retriever=retriever, settings=settings, allow_api=True, client=client,
    )
    assert solution.answer == "A"
    assert solution.question_type == "不确定"
    assert "逐项分析不完整" in solution.warning
    assert set(solution.option_analysis) == set(options)


def test_verified_bank_auto_uses_bank_type_and_reordered_answer(monkeypatch):
    bank = sample_bank()
    q = bank[0]
    shuffled = {"A": q["options"]["C"], "B": q["options"]["A"], "C": q["options"]["B"], "D": q["options"]["D"]}
    retriever, client, settings = _choice_engine(monkeypatch, "{}", bank=bank, hits=False)
    solution = solve_choice_question(
        q["question"], shuffled, question_type="自动",
        retriever=retriever, settings=settings, allow_api=True, client=client,
    )
    assert solution.verified is True
    assert solution.answer == "A"
    assert solution.question_type == "单选"
    assert client.chat.call_count == 0


def test_no_relevant_material_still_allows_structured_general_inference(monkeypatch):
    options = {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}
    retriever, client, settings = _choice_engine(
        monkeypatch, _structured_choice("B", options, qtype="single"), hits=False
    )
    solution = solve_choice_question(
        "无本地材料的题目？", options, question_type="自动",
        retriever=retriever, settings=settings, allow_api=True, client=client,
    )
    assert solution.answer == "B"
    assert "DeepSeek通用知识" in solution.source
    assert client.chat.call_count == 1


def test_code_block_json_is_parsed(monkeypatch):
    options = {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}
    content = "```json\n" + _structured_choice("AC", options, qtype="multiple") + "\n```"
    retriever, client, settings = _choice_engine(monkeypatch, content)
    solution = solve_choice_question(
        "代码块返回的题目？", options, question_type="自动",
        retriever=retriever, settings=settings, allow_api=True, client=client,
    )
    assert solution.answer == "AC"
    assert solution.question_type == "多选"
    assert solution.diagnostic["error_type"] is None
    assert solution.diagnostic["model"] == "deepseek-flash"


def test_mixed_schema_uses_answer_when_selected_options_missing(monkeypatch):
    options = {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}
    content = json.dumps({
        "question_type": "multiple",
        "answer": "AC",
        "analysis": "兼容旧字段的解析",
    }, ensure_ascii=False)
    retriever, client, settings = _choice_engine(monkeypatch, content)
    solution = solve_choice_question(
        "混合字段题目？", options, question_type="自动",
        retriever=retriever, settings=settings, allow_api=True, client=client,
    )
    assert solution.answer == "AC"
    assert solution.question_type == "不确定"  # 缺逐项分析，显式提示而非假装完整
    assert "逐项分析不完整" in solution.warning


def test_selected_options_string_and_analysis_list_are_supported(monkeypatch):
    options = {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}
    content = json.dumps({
        "question_type": "multiple",
        "selected_options": "A,C",
        "option_analysis": [
            {"option": "A", "reason": "A正确"},
            {"option": "B", "reason": "B错误"},
            {"option": "C", "reason": "C正确"},
            {"option": "D", "reason": "D错误"},
        ],
        "explanation": "解析",
        "uncertainty_reason": "",
    }, ensure_ascii=False)
    retriever, client, settings = _choice_engine(monkeypatch, content)
    solution = solve_choice_question(
        "字符串选项和列表分析题目？", options, question_type="自动",
        retriever=retriever, settings=settings, allow_api=True, client=client,
    )
    assert solution.answer == "AC"
    assert solution.question_type == "多选"
    assert set(solution.option_analysis) == set(options)


def test_option_analysis_list_strings_and_boolean_values_are_supported(monkeypatch):
    options = {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}
    content = json.dumps({
        "question_type": "single",
        "selected_options": ["A"],
        "option_analysis": ["A正确", "B错误", "C错误", "D错误"],
        "explanation": "解析",
    }, ensure_ascii=False)
    retriever, client, settings = _choice_engine(monkeypatch, content)
    solution = solve_choice_question(
        "列表字符串分析题目？", options, question_type="自动",
        retriever=retriever, settings=settings, allow_api=True, client=client,
    )
    assert solution.answer == "A"
    assert solution.question_type == "单选"
    assert set(solution.option_analysis) == set(options)

    bool_content = json.dumps({
        "question_type": "single",
        "selected_options": ["B"],
        "option_analysis": {"A": False, "B": True, "C": False, "D": False},
        "explanation": "解析",
    }, ensure_ascii=False)
    retriever, client, settings = _choice_engine(monkeypatch, bool_content)
    solution = solve_choice_question(
        "布尔分析题目？", options, question_type="自动",
        retriever=retriever, settings=settings, allow_api=True, client=client,
    )
    assert solution.answer == "B"
    assert solution.question_type == "单选"


def test_choice_error_diagnostics_distinguish_empty_json_and_bad_option(monkeypatch):
    options = {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}
    cases = [
        ("", "empty_content"),
        ("not json", "json_not_found"),
        ('{"question_type":"single","selected_options":["E"],"option_analysis":{},"explanation":"x"}', "selected_missing"),
    ]
    for content, code in cases:
        retriever, client, settings = _choice_engine(monkeypatch, content)
        solution = solve_choice_question(
            "诊断测试题目？", options, question_type="自动",
            retriever=retriever, settings=settings, allow_api=True, client=client,
        )
        assert solution.answer is None
        assert solution.diagnostic["error_type"] == code
        assert code in solution.warning


def test_diagnostic_preview_redacts_api_key(monkeypatch):
    options = {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}
    retriever, client, settings = _choice_engine(monkeypatch, "not json sk-synthetic-choice-secret")
    settings.deepseek_api_key = "sk-synthetic-choice-secret"
    solution = solve_choice_question(
        "脱敏诊断题目？", options, question_type="自动",
        retriever=retriever, settings=settings, allow_api=True, client=client,
    )
    assert "sk-synthetic-choice-secret" not in solution.diagnostic["raw_preview"]
    assert "[REDACTED]" in solution.diagnostic["raw_preview"]
