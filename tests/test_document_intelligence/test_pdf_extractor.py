"""
Tests for PdfExtractor — page-by-page PDF text extraction with OCR fallback.

These tests do not require reportlab. A minimal valid PDF is constructed
using pypdf.PdfWriter directly (which is a core dependency).
"""
import io
import os
import struct
import tempfile

import pypdf
import pytest

from document_intelligence.extractors.pdf_extractor import PdfExtractor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_blank_pdf(num_pages: int = 1) -> bytes:
    """Create a minimal valid PDF with blank pages using pypdf.PdfWriter."""
    writer = pypdf.PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
def extractor():
    return PdfExtractor()


@pytest.fixture
def blank_pdf_path(tmp_path):
    """Write a single-page blank PDF to a temp file and return its path."""
    pdf_bytes = _make_blank_pdf(num_pages=1)
    p = tmp_path / "blank.pdf"
    p.write_bytes(pdf_bytes)
    return str(p)


# ---------------------------------------------------------------------------
# 1. test_extract_nonexistent_file — returns []
# ---------------------------------------------------------------------------

def test_extract_nonexistent_file(extractor):
    result = extractor.extract_pages("/nonexistent/path/does_not_exist.pdf")
    assert result == []


# ---------------------------------------------------------------------------
# 2. test_extract_invalid_content — non-PDF bytes returns []
# ---------------------------------------------------------------------------

def test_extract_invalid_content(extractor, tmp_path):
    bad_file = tmp_path / "not_a_pdf.pdf"
    bad_file.write_bytes(b"This is not a PDF file at all!")
    result = extractor.extract_pages(str(bad_file))
    assert result == []


# ---------------------------------------------------------------------------
# 3. test_page_count_nonexistent — returns 0
# ---------------------------------------------------------------------------

def test_page_count_nonexistent(extractor):
    count = extractor.get_page_count("/nonexistent/path/does_not_exist.pdf")
    assert count == 0


# ---------------------------------------------------------------------------
# 4. test_extract_blank_pdf — blank PDF pages are flagged=True
# ---------------------------------------------------------------------------

def test_extract_blank_pdf(extractor, blank_pdf_path):
    pages = extractor.extract_pages(blank_pdf_path)
    assert len(pages) >= 1, "Should return at least one page result"
    for page in pages:
        assert page["flagged"] is True, (
            f"Blank page should be flagged (char_count={page['char_count']})"
        )


# ---------------------------------------------------------------------------
# 5. test_page_count_blank_pdf — returns 1
# ---------------------------------------------------------------------------

def test_page_count_blank_pdf(extractor, blank_pdf_path):
    count = extractor.get_page_count(blank_pdf_path)
    assert count == 1


# ---------------------------------------------------------------------------
# 6. test_extract_pages_structure — verify returned dicts have correct keys
# ---------------------------------------------------------------------------

def test_extract_pages_structure(extractor, blank_pdf_path):
    pages = extractor.extract_pages(blank_pdf_path)
    assert len(pages) >= 1

    required_keys = {"page_number", "text", "extraction_method", "char_count", "flagged"}
    for page in pages:
        assert required_keys == set(page.keys()), (
            f"Page dict missing keys. Got: {set(page.keys())}"
        )
        assert isinstance(page["page_number"], int)
        assert page["page_number"] >= 1
        assert isinstance(page["text"], str)
        assert page["extraction_method"] in ("pypdf", "ocr", "failed")
        assert isinstance(page["char_count"], int)
        assert isinstance(page["flagged"], bool)
        # char_count must be consistent with text
        assert page["char_count"] == len(page["text"])
