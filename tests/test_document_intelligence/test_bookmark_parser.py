"""
Tests for BookmarkParser — PDF bookmark/outline extraction.

Uses pypdf.PdfWriter for real blank PDFs (no-bookmark case).
Uses unittest.mock to simulate PDFs with bookmarks without needing actual
bookmarked PDF files.
"""
import io
import unittest.mock as mock

import pypdf
import pytest

from document_intelligence.extractors.bookmark_parser import BookmarkParser


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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def parser():
    return BookmarkParser()


@pytest.fixture
def blank_pdf_path(tmp_path):
    """Write a 3-page blank PDF to a temp file and return its path."""
    pdf_bytes = _make_blank_pdf(num_pages=3)
    p = tmp_path / "blank.pdf"
    p.write_bytes(pdf_bytes)
    return str(p)


# ---------------------------------------------------------------------------
# 1. test_no_bookmarks — blank PDF returns []
# ---------------------------------------------------------------------------

def test_no_bookmarks(parser, blank_pdf_path):
    """A PDF with no outline/bookmarks should return an empty list."""
    result = parser.extract_bookmarks(blank_pdf_path)
    assert result == []


# ---------------------------------------------------------------------------
# 2. test_find_toc_bookmark_returns_none_when_absent
# ---------------------------------------------------------------------------

def test_find_toc_bookmark_returns_none_when_absent(parser, blank_pdf_path):
    """find_toc_bookmark should return None when no TOC bookmark exists."""
    result = parser.find_toc_bookmark(blank_pdf_path)
    assert result is None


# ---------------------------------------------------------------------------
# 3. test_bookmark_structure — verify extracted bookmark dicts have correct keys
# ---------------------------------------------------------------------------

def test_bookmark_structure(parser, tmp_path):
    """
    Mock pypdf.PdfReader to return two Destination objects and verify that
    extract_bookmarks returns correctly structured dicts.
    """
    # Build a minimal real PDF so the file-exists check passes
    pdf_bytes = _make_blank_pdf(num_pages=3)
    pdf_path = str(tmp_path / "mocked.pdf")
    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)

    # Create mock Destination objects (simulate outline items)
    dest_a = mock.MagicMock()
    dest_a.title = "Section A"
    dest_a.__class__ = pypdf.generic.Destination

    dest_b = mock.MagicMock()
    dest_b.title = "Section B"
    dest_b.__class__ = pypdf.generic.Destination

    mock_reader = mock.MagicMock()
    mock_reader.outline = [dest_a, dest_b]
    mock_reader.get_destination_page_number.side_effect = [0, 2]

    with mock.patch("pypdf.PdfReader", return_value=mock_reader):
        result = parser.extract_bookmarks(pdf_path)

    assert len(result) == 2

    for item in result:
        assert set(item.keys()) == {"title", "page_number"}, (
            f"Bookmark dict has unexpected keys: {set(item.keys())}"
        )
        assert isinstance(item["title"], str)
        assert isinstance(item["page_number"], int)

    assert result[0]["title"] == "Section A"
    assert result[0]["page_number"] == 0

    assert result[1]["title"] == "Section B"
    assert result[1]["page_number"] == 2
