"""案例分析多截图 OCR、追加/去重、清空状态回归；不调用真实 OCR/API。"""
from __future__ import annotations

from types import SimpleNamespace

from src.app import _clear_case_state, process_case_uploads
from src.ocr import OCRResult


class FakeImage:
    def __init__(self, data, name):
        self._data = data
        self.name = name

    def getvalue(self):
        return self._data


def _recognizer(calls, results):
    def recognize(raw):
        calls.append(raw)
        return results[min(len(calls) - 1, len(results) - 1)]
    return recognize


def test_multi_image_ocr_keeps_success_when_one_fails():
    calls = []
    state = {}
    files = [FakeImage(b"one", "1.png"), FakeImage(b"two", "2.jpg"), FakeImage(b"three", "3.jpeg")]
    count, errors = process_case_uploads(
        files, state,
        recognize=_recognizer(calls, [
            OCRResult("ok", "案例背景：某工程发生事故。", [], 0.9),
            OCRResult("error", "", [], 0.0, "图片模糊"),
            OCRResult("ok", "（1）工程师应承担什么责任？", [], 0.9),
        ]),
    )
    assert count == 2
    assert len(errors) == 1
    assert "案例背景" in state["case_text"]
    assert "工程师应承担" in state["case_text"]
    assert len(state["case_uploaded_hashes"]) == 3


def test_duplicate_images_do_not_reocr_and_new_images_append():
    calls = []
    state = {}
    first = [FakeImage(b"one", "1.png")]
    process_case_uploads(first, state, recognize=_recognizer(calls, [OCRResult("ok", "第一段", [], 1.0)]))
    process_case_uploads(first, state, recognize=_recognizer(calls, [OCRResult("ok", "不应覆盖", [], 1.0)]))
    assert len(calls) == 1
    assert state["case_text"] == "第一段"

    state["case_text"] = "用户编辑后的案例"
    second = [FakeImage(b"two", "2.png")]
    process_case_uploads(second, state, recognize=_recognizer(calls, [OCRResult("ok", "新增第二段", [], 1.0)]))
    assert len(calls) == 2
    assert state["case_text"].startswith("用户编辑后的案例")
    assert "新增第二段" in state["case_text"]


def test_empty_and_bad_format_report_errors():
    state = {}
    count, errors = process_case_uploads(
        [FakeImage(b"", "empty.png"), FakeImage(b"x", "bad.gif")],
        state, recognize=lambda raw: OCRResult("ok", "x", [], 1.0),
    )
    assert count == 0
    assert any("图片为空" in error for error in errors)
    assert any("格式不支持" in error for error in errors)


def test_clear_case_keeps_other_module_state(monkeypatch):
    state = {
        "case_text": "案例",
        "case_questions_text": "设问",
        "case_uploaded_hashes": ["x"],
        "case_uploader_epoch": 4,
        "case_questions_dirty": True,
        "last_case_solution": object(),
        "question_input": "简答题不应被清空",
        "qa_mode": "hybrid",
    }
    monkeypatch.setattr("src.app.st", SimpleNamespace(session_state=state))
    _clear_case_state()
    assert state["case_text"] == ""
    assert state["case_questions_text"] == ""
    assert "case_uploaded_hashes" not in state
    assert "last_case_solution" not in state
    assert state["case_uploader_epoch"] == 5
    assert state["question_input"] == "简答题不应被清空"
    assert state["qa_mode"] == "hybrid"
