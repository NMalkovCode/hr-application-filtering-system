from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from hr_screening import config
from hr_screening.extraction import ExtractionError, extract_document
from hr_screening.models import ContentKind

from .conftest import CV_TEXT, make_docx, make_image, make_scan_image, make_scanned_pdf, make_text_pdf


def test_text_pdf_is_extracted_locally(tmp_path: Path):
    (doc,) = extract_document(make_text_pdf(tmp_path / "cv.pdf", pages=2))
    assert doc.kind is ContentKind.TEXT
    assert "Senior Data Analyst" in doc.text
    assert doc.page_count == 2
    assert not doc.data


def test_scanned_pdf_is_kept_for_claude(tmp_path: Path):
    (doc,) = extract_document(make_scanned_pdf(tmp_path / "scan.pdf"))
    assert doc.kind is ContentKind.PDF
    assert doc.media_type == "application/pdf"
    assert doc.data.startswith(b"%PDF")
    assert doc.needs_vision


def test_docx_includes_header_body_and_tables(tmp_path: Path):
    (doc,) = extract_document(make_docx(tmp_path / "cv.docx"))
    assert doc.kind is ContentKind.TEXT
    assert "jane.doe@example.com" in doc.text
    assert "Power BI" in doc.text
    assert "English, French" in doc.text


def test_docx_with_only_a_pasted_scan_uses_the_image(tmp_path: Path):
    from docx import Document
    from docx.shared import Inches

    img_path = make_image(tmp_path / "page.png")
    path = tmp_path / "scan_in_word.docx"
    d = Document()
    d.add_picture(str(img_path), width=Inches(6))
    d.save(str(path))

    docs = extract_document(path)
    assert [d.kind for d in docs] == [ContentKind.IMAGE]


def test_small_native_image_is_passed_through_unchanged(tmp_path: Path):
    path = make_image(tmp_path / "cv.png", size=(800, 1100))
    (doc,) = extract_document(path)
    assert doc.kind is ContentKind.IMAGE
    assert doc.media_type == "image/png"
    assert doc.data == path.read_bytes()


def test_large_image_is_downscaled(tmp_path: Path):
    (doc,) = extract_document(make_image(tmp_path / "photo.jpg", size=(3000, 4000)))
    assert doc.media_type == "image/jpeg"
    from io import BytesIO
    assert max(Image.open(BytesIO(doc.data)).size) <= config.MAX_IMAGE_EDGE_PX


def test_tiff_and_bmp_are_converted(tmp_path: Path):
    (bmp,) = extract_document(make_image(tmp_path / "cv.bmp", size=(600, 800)))
    assert bmp.media_type == "image/jpeg"

    tiff = tmp_path / "multi.tiff"
    pages = [make_scan_image((600, 800)), make_scan_image((600, 800), "PAGE 2")]
    pages[0].save(tiff, save_all=True, append_images=pages[1:])
    docs = extract_document(tiff)
    assert len(docs) == 2 and all(d.media_type == "image/jpeg" for d in docs)


def test_text_file(tmp_path: Path):
    path = tmp_path / "cv.txt"
    path.write_text(CV_TEXT, encoding="cp1252")
    (doc,) = extract_document(path)
    assert doc.text.startswith("Jane Doe")


@pytest.mark.parametrize(
    "name, content, message",
    [
        ("broken.pdf", b"not a pdf at all", "damaged"),
        ("broken.docx", b"not a zip", "damaged"),
        ("broken.png", b"not an image", "damaged"),
        ("empty.txt", b"", "empty"),
        ("empty.pdf", b"", "empty"),
        ("blank.txt", b"   \n\n ", "empty"),
        ("protected.docx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600, "password-protected"),
    ],
)
def test_corrupt_files_raise_friendly_errors(tmp_path: Path, name, content, message):
    path = tmp_path / name
    path.write_bytes(content)
    with pytest.raises(ExtractionError, match=message):
        extract_document(path)


def test_missing_file(tmp_path: Path):
    with pytest.raises(ExtractionError, match="no longer exists"):
        extract_document(tmp_path / "gone.pdf")


def test_file_locked_by_another_program(tmp_path: Path, monkeypatch):
    path = make_text_pdf(tmp_path / "cv.pdf")
    import hr_screening.extraction as ex

    def locked(*a, **k):
        raise PermissionError("in use")
    monkeypatch.setattr(ex, "PdfReader", locked)
    with pytest.raises(ExtractionError, match="open in another program"):
        extract_document(path)


def test_password_protected_pdf(tmp_path: Path):
    from pypdf import PdfReader, PdfWriter

    plain = make_text_pdf(tmp_path / "plain.pdf")
    writer = PdfWriter(clone_from=PdfReader(plain))
    writer.encrypt(user_password="secret", owner_password="owner")
    locked = tmp_path / "locked.pdf"
    with open(locked, "wb") as f:
        writer.write(f)
    with pytest.raises(ExtractionError, match="password"):
        extract_document(locked)


def test_edit_restricted_pdf_with_empty_password_is_readable(tmp_path: Path):
    from pypdf import PdfReader, PdfWriter

    plain = make_text_pdf(tmp_path / "plain.pdf")
    writer = PdfWriter(clone_from=PdfReader(plain))
    writer.encrypt(user_password="", owner_password="owner")
    restricted = tmp_path / "restricted.pdf"
    with open(restricted, "wb") as f:
        writer.write(f)
    (doc,) = extract_document(restricted)
    assert "Senior Data Analyst" in doc.text
