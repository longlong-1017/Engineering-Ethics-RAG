"""通用本地 OCR 识别模块：支持图片路径、字节流、PIL 图像。

设计原则：
1. 优先调用本地 macOS Vision 原生识别引擎 (.build/vision_ocr)；
2. 引擎不可用或跨平台时优雅降级，返回明确错误提示，不产生未捕获异常；
3. 通用设计：支持选择题解析（ocr_and_parse_question），也支持后续案例分析题等通用文本提取。
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from src.choice_solver import ParsedChoiceQuestion, parse_choice_text

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VISION_ENGINE = ROOT / ".build/vision_ocr"


@dataclass(frozen=True)
class OCRResult:
    status: str  # 'ok' 或 'error'
    text: str
    lines: list[str] = field(default_factory=list)
    confidence: float = 0.0
    error: str = ""


def recognize_image(
    image_input: str | Path | bytes | io.BytesIO | Any,
    *,
    engine_path: Path | str = DEFAULT_VISION_ENGINE,
    timeout: int = 20,
) -> OCRResult:
    """对传入图片执行本地 OCR 识别。

    支持输入：
    - 本地文件路径 (str 或 Path)
    - 二进制数据 (bytes)
    - 内存流 (io.BytesIO 或 Streamlit UploadedFile)
    - PIL.Image 对象
    """
    engine_file = Path(engine_path).resolve()
    if not engine_file.is_file():
        return OCRResult(
            status="error",
            text="",
            error=f"本地 OCR 引擎不可用：未找到 {engine_file}。如需测试可使用 Mock。",
        )

    # 规范化图片为临时文件路径
    temp_file_path = None
    target_path = None

    try:
        if isinstance(image_input, (str, Path)):
            p = Path(image_input).resolve()
            if not p.is_file():
                return OCRResult(status="error", text="", error=f"图片文件不存在：{p}")
            target_path = p
        elif isinstance(image_input, bytes):
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                tf.write(image_input)
                temp_file_path = Path(tf.name)
            target_path = temp_file_path
        elif hasattr(image_input, "getvalue"):  # Streamlit UploadedFile 或 BytesIO
            raw_bytes = image_input.getvalue()
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                tf.write(raw_bytes)
                temp_file_path = Path(tf.name)
            target_path = temp_file_path
        elif hasattr(image_input, "save"):  # PIL Image
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                image_input.save(tf, format="PNG")
                temp_file_path = Path(tf.name)
            target_path = temp_file_path
        else:
            return OCRResult(status="error", text="", error="不支持的图片输入类型")

        # 调用 Vision OCR 引擎
        proc = subprocess.run(
            [str(engine_file), str(target_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if proc.returncode != 0 and not proc.stdout.strip():
            err_msg = proc.stderr.strip() or f"OCR 进程退出异常，代码：{proc.returncode}"
            return OCRResult(status="error", text="", error=err_msg)

        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return OCRResult(status="error", text="", error="OCR 引擎返回的 JSON 解析失败")

        if data.get("status") != "ok":
            return OCRResult(status="error", text="", error=data.get("error", "OCR 处理失败"))

        observations = data.get("observations", [])
        # 按照从上到下（y坐标）排序观察值
        sorted_obs = sorted(
            observations,
            key=lambda o: (o.get("pixel_bbox_top_left", [0, 0])[1], o.get("pixel_bbox_top_left", [0, 0])[0])
        )

        lines = []
        confidences = []
        for obs in sorted_obs:
            cands = obs.get("candidates", [])
            if cands:
                top = cands[0]
                text_piece = top.get("text", "").strip()
                if text_piece:
                    lines.append(text_piece)
                    confidences.append(float(top.get("confidence", 0.0)))

        full_text = "\n".join(lines)
        avg_conf = sum(confidences) / max(len(confidences), 1)

        return OCRResult(
            status="ok",
            text=full_text,
            lines=lines,
            confidence=round(avg_conf, 3),
        )

    except subprocess.TimeoutExpired:
        return OCRResult(status="error", text="", error="OCR 识别超时")
    except Exception as exc:
        return OCRResult(status="error", text="", error=f"OCR 识别异常：{exc}")
    finally:
        if temp_file_path and temp_file_path.exists():
            try:
                temp_file_path.unlink()
            except OSError:
                pass


def ocr_and_parse_question(
    image_input: str | Path | bytes | io.BytesIO | Any,
    *,
    engine_path: Path | str = DEFAULT_VISION_ENGINE,
) -> dict[str, Any]:
    """对图片进行 OCR 识别，并将其解析为选择题题目结构（题干、选项、题型）。"""
    result = recognize_image(image_input, engine_path=engine_path)
    if result.status != "ok":
        return {
            "status": "error",
            "error": result.error,
            "raw_text": "",
            "stem": "",
            "options": {},
            "question_type": "单选",
            "lines": [],
        }

    parsed = parse_choice_text(result.text)
    return {
        "status": "ok",
        "error": "",
        "raw_text": result.text,
        "stem": parsed.stem,
        "options": parsed.options,
        "question_type": parsed.question_type,
        "lines": result.lines,
        "confidence": result.confidence,
    }
