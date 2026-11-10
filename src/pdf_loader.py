"""按 PDF 物理页提取文字；不执行 OCR，不修改输入文件。"""

import argparse
import hashlib
import json
from pathlib import Path

import pymupdf


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def extract_pdf(path: Path) -> dict:
    """返回文档及逐页记录。SHA-256 标识文件内容，不依赖文件名。"""
    path = Path(path)
    result = {
        "schema_version": 1,
        "filename": path.name,
        "document_id": None,
        "page_count": 0,
        "status": "error",
        "warnings": [],
        "errors": [],
        "pages": [],
    }
    try:
        content = path.read_bytes()
        result["document_id"] = hashlib.sha256(content).hexdigest()
        with pymupdf.open(stream=content, filetype="pdf") as doc:
            if not doc.is_pdf:
                raise ValueError("文件不是 PDF")
            if doc.needs_pass:
                raise ValueError("PDF 已加密，需要人工提供密码或解密后的副本")
            result["page_count"] = len(doc)
            for index in range(len(doc)):
                record = {
                    "document_id": result["document_id"],
                    "filename": path.name,
                    "page_number": index + 1,
                    "text": "",
                    "status": "error",
                    "warnings": [],
                }
                try:
                    page = doc.load_page(index)
                    record["text"] = page.get_text("text", sort=True)
                    if record["text"].strip():
                        record["status"] = "text"
                        if "\ufffd" in record["text"]:
                            record["warnings"].append("存在 Unicode 替换字符，请人工检查字体映射")
                    elif page.get_image_info():
                        record["status"] = "suspected_scan"
                        record["warnings"].append("无可提取文本但有图像，疑似扫描页或纯图片页；未执行 OCR，需人工检查")
                    elif page.get_drawings():
                        record["status"] = "non_text"
                        record["warnings"].append("无可提取文本但有矢量内容，可能是轮廓文字；未执行 OCR，需人工检查")
                    else:
                        record["status"] = "blank"
                        record["warnings"].append("空白页：未发现可提取文字、图像或矢量内容")
                except Exception as exc:
                    record["warnings"].append(f"页面读取失败：{type(exc).__name__}: {exc}")
                result["pages"].append(record)
            if not result["pages"]:
                result["warnings"].append("PDF 没有页面")
            if any(p["status"] == "error" for p in result["pages"]):
                result["status"] = "partial"
            elif any(p["warnings"] for p in result["pages"]) or not result["pages"]:
                result["status"] = "warning"
            else:
                result["status"] = "ok"
    except Exception as exc:
        result["errors"].append(f"无法读取 PDF：{type(exc).__name__}: {exc}")
    return result


def save_result(result: dict, output_dir: Path) -> Path:
    """以 UTF-8 保存；使用排他创建，重复运行也不会覆盖已有文件。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(result["filename"]).stem
    identifier = result["document_id"] or "unreadable"
    base = f"{stem}_{identifier}"
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    number = 0
    while True:
        suffix = f"_{number}" if number else ""
        target = output_dir / f"{base}{suffix}.json"
        try:
            with target.open("x", encoding="utf-8") as handle:
                handle.write(payload)
            return target
        except FileExistsError:
            number += 1


def process_directory(input_dir: Path, output_dir: Path) -> list[dict]:
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    if not input_dir.is_dir():
        raise NotADirectoryError(f"输入目录不存在或不是目录：{input_dir}")
    paths = sorted(p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
    print(f"发现 PDF 文件：{len(paths)}")
    if not paths:
        print("输入目录中没有 PDF，无需处理。")
        return []
    results = []
    for path in paths:
        result = extract_pdf(path)
        destination = save_result(result, output_dir)
        print(f"{path.name}：{result['page_count']} 页，状态 {result['status']}，输出 {destination.name}")
        for message in result["warnings"] + result["errors"]:
            print(f"  提示：{message}")
        for page in result["pages"]:
            for message in page["warnings"]:
                print(f"  第 {page['page_number']} 页：{message}")
        results.append(result)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=PROJECT_ROOT / "data/pdfs")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data/processed")
    args = parser.parse_args()
    for path in (args.input_dir, args.output_dir):
        if not path.resolve().is_relative_to(PROJECT_ROOT):
            parser.error("输入和输出目录必须位于当前项目内")
    try:
        results = process_directory(args.input_dir, args.output_dir)
    except (OSError, ValueError) as exc:
        print(f"处理失败：{exc}")
        return 1
    return int(any(r["status"] in {"error", "partial"} for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
