"""仅生成明确标注的测试 PDF，不使用或改写课程资料。"""

import hashlib
import json

import pymupdf
import pytest

from src.pdf_loader import extract_pdf, process_directory, save_result


@pytest.fixture
def sample_pdf(tmp_path):
    path = tmp_path / "临时测试资料.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 50), "工程伦理：责任、公正与安全。", fontname="china-s")
        page.insert_text((40, 90), "TEST ONLY - Engineering ethics 123 & @ % + =", fontname="helv")
        doc.new_page()  # 保留空白页，以验证物理页码不会被压缩。
        page = doc.new_page()
        page.insert_text((40, 50), "第三页：测试专用", fontname="china-s")
        doc.save(path)
    return path


def test_text_unicode_page_numbers_and_source_unchanged(sample_pdf):
    original = sample_pdf.read_bytes()
    result = extract_pdf(sample_pdf)
    assert result["page_count"] == 3
    assert [p["page_number"] for p in result["pages"]] == [1, 2, 3]
    assert "工程伦理：责任、公正与安全。" in result["pages"][0]["text"]
    assert "Engineering ethics 123 & @ % + =" in result["pages"][0]["text"]
    assert "第三页：测试专用" in result["pages"][2]["text"]
    assert result["pages"][1]["status"] == "blank"
    assert result["pages"][1]["warnings"]
    assert result["document_id"] == hashlib.sha256(original).hexdigest()
    assert all(p["filename"] == sample_pdf.name and p["document_id"] == result["document_id"] for p in result["pages"])
    assert sample_pdf.read_bytes() == original


def test_json_roundtrip_and_no_overwrite(sample_pdf, tmp_path):
    result = extract_pdf(sample_pdf)
    first = save_result(result, tmp_path / "output")
    original = first.read_bytes()
    second = save_result(result, tmp_path / "output")
    assert first != second
    assert first.read_bytes() == original
    assert "工程伦理" in first.read_text(encoding="utf-8")
    assert json.loads(first.read_text(encoding="utf-8")) == result


def test_empty_directory(tmp_path, capsys):
    assert process_directory(tmp_path, tmp_path / "output") == []
    assert "没有 PDF" in capsys.readouterr().out
    assert not (tmp_path / "output").exists()


def test_corrupt_file_does_not_stop_batch(sample_pdf, tmp_path):
    (tmp_path / "broken.PDF").write_bytes(b"not a PDF")
    (tmp_path / "ignore.txt").write_text("ignored", encoding="utf-8")
    results = process_directory(tmp_path, tmp_path / "output")
    assert len(results) == 2
    broken = next(r for r in results if r["filename"] == "broken.PDF")
    assert broken["status"] == "error" and broken["errors"]
    assert next(r for r in results if r["filename"] == sample_pdf.name)["page_count"] == 3
    assert len(list((tmp_path / "output").glob("*.json"))) == 2


def test_missing_directory(tmp_path):
    with pytest.raises(NotADirectoryError):
        process_directory(tmp_path / "missing", tmp_path / "output")


def test_missing_file(tmp_path):
    result = extract_pdf(tmp_path / "missing.pdf")
    assert result["status"] == "error" and result["errors"]
    assert result["document_id"] is None


def test_image_only_pdf(tmp_path):
    path = tmp_path / "TEST_ONLY_scan.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        pix = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 20, 20), False)
        pix.clear_with(128)
        page.insert_image(page.rect, pixmap=pix)
        doc.save(path)
    result = extract_pdf(path)
    assert result["pages"][0]["status"] == "suspected_scan"
    assert result["pages"][0]["text"] == ""
    assert "未执行 OCR" in result["pages"][0]["warnings"][0]


def test_encrypted_pdf(tmp_path):
    path = tmp_path / "encrypted.pdf"
    with pymupdf.open() as doc:
        doc.new_page()
        doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret")
    result = extract_pdf(path)
    assert result["status"] == "error"
    assert "加密" in result["errors"][0]


def test_id_is_content_based(sample_pdf, tmp_path):
    copy = tmp_path / "renamed.pdf"
    copy.write_bytes(sample_pdf.read_bytes())
    assert extract_pdf(copy)["document_id"] == extract_pdf(sample_pdf)["document_id"]
