"""简答题截图 OCR、重复上传、清空与模式状态回归；不调用真实 OCR/DeepSeek。"""
from __future__ import annotations

from types import SimpleNamespace

from src.app import _clear_qa_state, process_qa_upload
from src.ocr import OCRResult


class FakeUpload:
    def __init__(self, data: bytes, name: str = "question.png"):
        self._data = data
        self.name = name

    def getvalue(self):
        return self._data


def _recognizer(calls, result):
    def recognize(raw):
        calls.append(raw)
        return result
    return recognize


def test_ocr_success_fills_question_without_submitting():
    calls = []
    state = {"qa_mode": "hybrid"}
    status, message = process_qa_upload(
        FakeUpload(b"image-one"), state,
        recognize=_recognizer(calls, OCRResult(status="ok", text="工程风险的技术因素有哪些？")),
    )
    assert status == "success"
    assert "已填入" in message
    assert state["question_input"] == "工程风险的技术因素有哪些？"
    assert len(calls) == 1
    assert "last_answer" not in state
    assert state["qa_mode"] == "hybrid"


def test_ocr_failure_keeps_manual_text_and_marks_image_processed():
    calls = []
    state = {"question_input": "手动输入的题目", "qa_uploaded_sig": None}
    upload = FakeUpload(b"bad-image")
    status, message = process_qa_upload(
        upload, state,
        recognize=_recognizer(calls, OCRResult(status="error", text="", error="引擎不可用")),
    )
    assert status == "error"
    assert "识别失败" in message
    assert state["question_input"] == "手动输入的题目"
    # 同一失败图片再次 rerun 不重复 OCR，用户可清空后重试。
    status2, _ = process_qa_upload(
        upload, state,
        recognize=_recognizer(calls, OCRResult(status="ok", text="不应使用")),
    )
    assert status2 == "duplicate"
    assert len(calls) == 1


def test_same_image_does_not_overwrite_manual_edit_and_new_image_replaces():
    calls = []
    state = {}
    first = FakeUpload(b"image-one")
    status, _ = process_qa_upload(
        first, state, recognize=_recognizer(calls, OCRResult(status="ok", text="OCR 第一版")),
    )
    assert status == "success"
    state["question_input"] = "用户手动修改后的题目"
    status, _ = process_qa_upload(
        first, state, recognize=_recognizer(calls, OCRResult(status="ok", text="不应覆盖")),
    )
    assert status == "duplicate"
    assert state["question_input"] == "用户手动修改后的题目"
    assert len(calls) == 1

    second = FakeUpload(b"image-two")
    status, _ = process_qa_upload(
        second, state, recognize=_recognizer(calls, OCRResult(status="ok", text="OCR 第二版")),
    )
    assert status == "success"
    assert state["question_input"] == "OCR 第二版"
    assert len(calls) == 2


def test_empty_and_unsupported_image_show_error():
    state = {}
    status, message = process_qa_upload(FakeUpload(b""), state, recognize=lambda raw: OCRResult("ok", "x", [], 1.0))
    assert status == "error" and "图片为空" in message
    status, message = process_qa_upload(FakeUpload(b"x", "question.gif"), state, recognize=lambda raw: OCRResult("ok", "x", [], 1.0))
    assert status == "error" and "格式不支持" in message


def test_clear_removes_question_upload_and_answer_but_keeps_mode(monkeypatch):
    state = {
        "question_input": "待清空",
        "qa_uploaded_sig": "sig",
        "qa_uploader_epoch": 2,
        "last_answer": "answer",
        "last_api_diagnostic": {"outcome": "accepted"},
        "qa_mode": "local",
        "ai_enabled": True,
    }
    monkeypatch.setattr("src.app.st", SimpleNamespace(session_state=state))
    _clear_qa_state()
    assert state["question_input"] == ""
    assert "qa_uploaded_sig" not in state
    assert "last_answer" not in state
    assert "last_api_diagnostic" not in state
    assert state["qa_uploader_epoch"] == 3
    assert state["qa_mode"] == "local"
    assert state["ai_enabled"] is True


def test_clear_then_same_image_triggers_ocr_again(monkeypatch):
    calls = []
    state = {"qa_uploader_epoch": 0}
    upload = FakeUpload(b"same-image")
    process_qa_upload(upload, state, recognize=_recognizer(calls, OCRResult("ok", "第一版", [], 1.0)))
    monkeypatch.setattr("src.app.st", SimpleNamespace(session_state=state))
    _clear_qa_state()
    status, _ = process_qa_upload(upload, state, recognize=_recognizer(calls, OCRResult("ok", "第二版", [], 1.0)))
    assert status == "success"
    assert state["question_input"] == "第二版"
    assert len(calls) == 2
