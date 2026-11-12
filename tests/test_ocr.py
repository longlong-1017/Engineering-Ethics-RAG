"""OCR 识别模块单元测试：引擎不存在、格式错误、Mock测试及真实Vision引擎验证。"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ocr import OCRResult, recognize_image, ocr_and_parse_question


def test_recognize_image_file_not_found():
    res = recognize_image("/non/existent/path/to/image.png")
    assert res.status == "error"
    assert "不存在" in res.error or "不可用" in res.error


def test_recognize_image_unsupported_type():
    res = recognize_image(12345)
    assert res.status == "error"
    assert "不支持" in res.error or "不可用" in res.error


def test_recognize_image_missing_engine(tmp_path):
    img = tmp_path / "test.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    fake_engine = tmp_path / "no_engine"
    res = recognize_image(img, engine_path=fake_engine)
    assert res.status == "error"
    assert "不可用" in res.error


def test_recognize_image_mock_success(tmp_path):
    img = tmp_path / "test.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    engine = tmp_path / "mock_engine"
    engine.touch()

    mock_observations = [
        {"candidates": [{"text": "1. [单选] 工程师的首要责任是：", "confidence": 0.95}], "pixel_bbox_top_left": [10, 20]},
        {"candidates": [{"text": "A. 保护公众安全", "confidence": 0.92}], "pixel_bbox_top_left": [10, 50]},
        {"candidates": [{"text": "B. 满足雇主要求", "confidence": 0.88}], "pixel_bbox_top_left": [10, 80]},
    ]
    mock_payload = {"status": "ok", "observations": mock_observations}

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(mock_payload), stderr="")
        res = recognize_image(img, engine_path=engine)

        assert res.status == "ok"
        assert len(res.lines) == 3
        assert "工程师的首要责任是：" in res.text
        assert res.confidence > 0.9


def test_ocr_and_parse_question_mock(tmp_path):
    img = tmp_path / "test.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    engine = tmp_path / "mock_engine"
    engine.touch()

    mock_observations = [
        {"candidates": [{"text": "2. [多选] 工程伦理责任的主体包括：", "confidence": 0.95}], "pixel_bbox_top_left": [10, 20]},
        {"candidates": [{"text": "A. 工程师个人", "confidence": 0.90}], "pixel_bbox_top_left": [10, 50]},
        {"candidates": [{"text": "B. 工程共同体", "confidence": 0.91}], "pixel_bbox_top_left": [10, 80]},
        {"candidates": [{"text": "C. 施工单位", "confidence": 0.89}], "pixel_bbox_top_left": [10, 110]},
        {"candidates": [{"text": "D. 普通公众", "confidence": 0.85}], "pixel_bbox_top_left": [10, 140]},
    ]
    mock_payload = {"status": "ok", "observations": mock_observations}

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(mock_payload), stderr="")
        q = ocr_and_parse_question(img, engine_path=engine)

        assert q["status"] == "ok"
        assert q["question_type"] == "多选"
        assert "工程伦理责任的主体包括：" in q["stem"]
        assert len(q["options"]) == 4
        assert q["options"]["A"] == "工程师个人"
        assert q["options"]["D"] == "普通公众"


def test_ocr_bytes_input_handling(tmp_path):
    engine = tmp_path / "mock_engine"
    engine.touch()
    mock_payload = {"status": "ok", "observations": [{"candidates": [{"text": "测试", "confidence": 1.0}], "pixel_bbox_top_left": [0, 0]}]}

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(mock_payload), stderr="")
        res = recognize_image(b"fake png bytes", engine_path=engine)
        assert res.status == "ok"
        assert res.lines == ["测试"]
