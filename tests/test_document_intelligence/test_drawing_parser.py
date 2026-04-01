"""
Tests for DrawingParser — sheet index detection, title block parsing,
and discipline inference.
"""
import pytest

from document_intelligence.parsers.drawing_parser import DrawingParser


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def parser():
    return DrawingParser()


# ---------------------------------------------------------------------------
# TestInferDiscipline
# ---------------------------------------------------------------------------

class TestInferDiscipline:
    def test_architectural(self, parser):
        assert parser.infer_discipline("A2.3") == "Architectural"

    def test_structural(self, parser):
        assert parser.infer_discipline("S3.1") == "Structural"

    def test_mechanical(self, parser):
        assert parser.infer_discipline("M1.0") == "Mechanical"

    def test_electrical(self, parser):
        assert parser.infer_discipline("E2.1") == "Electrical"

    def test_plumbing(self, parser):
        assert parser.infer_discipline("P1.0") == "Plumbing"

    def test_landscape(self, parser):
        assert parser.infer_discipline("L1.0") == "Landscape"

    def test_civil(self, parser):
        assert parser.infer_discipline("C1.0") == "Civil"

    def test_fire_protection(self, parser):
        assert parser.infer_discipline("FP1.0") == "Fire Protection"

    def test_fire_suppression(self, parser):
        assert parser.infer_discipline("FS1.0") == "Fire Suppression"

    def test_telecommunications(self, parser):
        assert parser.infer_discipline("T1.0") == "Telecommunications"

    def test_general(self, parser):
        assert parser.infer_discipline("G0.1") == "General"

    def test_unknown(self, parser):
        assert parser.infer_discipline("X1.0") == "Unknown"

    def test_two_letter_prefix_takes_priority(self, parser):
        # FP should NOT match as F (which is not even in the map) but as "Fire Protection"
        assert parser.infer_discipline("FP2.0") == "Fire Protection"

    def test_fs_two_letter_priority(self, parser):
        assert parser.infer_discipline("FS2.0") == "Fire Suppression"

    def test_lowercase_unknown(self, parser):
        # Sheet numbers are expected upper-case; lower-case should return Unknown
        assert parser.infer_discipline("a2.3") == "Unknown"


# ---------------------------------------------------------------------------
# TestParseSheetIndexLines
# ---------------------------------------------------------------------------

class TestParseSheetIndexLines:
    def test_standard_lines(self, parser):
        lines = [
            "A1.0    ARCHITECTURAL SITE PLAN",
            "S1.0    STRUCTURAL FOUNDATION PLAN",
        ]
        sheets = parser.parse_sheet_index_lines(lines)
        assert len(sheets) == 2
        assert sheets[0]["sheet_number"] == "A1.0"
        assert sheets[0]["title"] == "ARCHITECTURAL SITE PLAN"
        assert sheets[0]["discipline"] == "Architectural"
        assert sheets[1]["sheet_number"] == "S1.0"
        assert sheets[1]["discipline"] == "Structural"

    def test_dash_separator(self, parser):
        lines = ["A1.0 - ARCHITECTURAL SITE PLAN"]
        sheets = parser.parse_sheet_index_lines(lines)
        assert len(sheets) == 1
        assert sheets[0]["sheet_number"] == "A1.0"
        assert sheets[0]["title"] == "ARCHITECTURAL SITE PLAN"

    def test_non_matching(self, parser):
        assert parser.parse_sheet_index_lines(["Not a sheet", ""]) == []

    def test_two_letter_prefix(self, parser):
        lines = ["FP1.0    FIRE SUPPRESSION RISER DIAGRAM"]
        sheets = parser.parse_sheet_index_lines(lines)
        assert len(sheets) == 1
        assert sheets[0]["sheet_number"] == "FP1.0"
        assert sheets[0]["discipline"] == "Fire Protection"

    def test_mixed_valid_and_invalid(self, parser):
        lines = [
            "SHEET INDEX",
            "A1.0    FLOOR PLAN",
            "Rev Date",
            "E2.1    ELECTRICAL PANEL SCHEDULE",
        ]
        sheets = parser.parse_sheet_index_lines(lines)
        assert len(sheets) == 2
        assert sheets[0]["sheet_number"] == "A1.0"
        assert sheets[1]["sheet_number"] == "E2.1"

    def test_dict_keys(self, parser):
        lines = ["A1.0    FLOOR PLAN"]
        sheets = parser.parse_sheet_index_lines(lines)
        assert set(sheets[0].keys()) == {"sheet_number", "title", "discipline"}

    def test_empty_input(self, parser):
        assert parser.parse_sheet_index_lines([]) == []

    def test_sheet_without_digit_ignored(self, parser):
        # "AA    TITLE" — no digit after the letter(s), should be skipped
        lines = ["AA    ARCHITECTURAL TITLE SHEET"]
        sheets = parser.parse_sheet_index_lines(lines)
        assert sheets == []


# ---------------------------------------------------------------------------
# TestDetectTitleBlock
# ---------------------------------------------------------------------------

class TestDetectTitleBlock:
    def test_detect_sheet_number(self, parser):
        text = "Some notes\nSheet: A2.3\nTitle: FLOOR PLAN"
        result = parser.detect_title_block(text)
        assert result is not None
        assert result["sheet_number"] == "A2.3"

    def test_detect_discipline(self, parser):
        text = "Project: Sample\nSheet: S1.0\nDate: 2024-01-01"
        result = parser.detect_title_block(text)
        assert result is not None
        assert result["discipline"] == "Structural"

    def test_sheet_number_at_end_of_line(self, parser):
        # "Sheet A2.3" at end of line (no colon)
        text = "Drawing Title\nA2.3"
        result = parser.detect_title_block(text)
        assert result is not None
        assert result["sheet_number"] == "A2.3"

    def test_no_sheet_number_returns_none(self, parser):
        text = "General Notes\nSome random text\nNo sheet here"
        result = parser.detect_title_block(text)
        assert result is None

    def test_fire_protection_sheet(self, parser):
        text = "Sheet: FP1.0\nFire Suppression System"
        result = parser.detect_title_block(text)
        assert result is not None
        assert result["sheet_number"] == "FP1.0"
        assert result["discipline"] == "Fire Protection"

    def test_result_keys(self, parser):
        text = "Sheet: A1.0"
        result = parser.detect_title_block(text)
        assert result is not None
        assert set(result.keys()) == {"sheet_number", "discipline"}

    def test_empty_text_returns_none(self, parser):
        assert parser.detect_title_block("") is None


# ---------------------------------------------------------------------------
# TestSplitPagesBySheets
# ---------------------------------------------------------------------------

class TestSplitPagesBySheets:
    def _make_pages(self, texts):
        """Helper: build a list of page dicts matching PdfExtractor output."""
        return [
            {"page_number": i + 1, "text": t, "extraction_method": "pypdf",
             "char_count": len(t), "flagged": False}
            for i, t in enumerate(texts)
        ]

    def _make_index(self, entries):
        """Helper: build a sheet index list."""
        return [
            {"sheet_number": sn, "title": title, "discipline": disc}
            for sn, title, disc in entries
        ]

    def test_basic_assignment(self, parser):
        pages = self._make_pages([
            "Cover page text",
            "Sheet: A1.0\nFloor Plan text",
            "Sheet: A2.0\nElevation text",
        ])
        index = self._make_index([
            ("A1.0", "FLOOR PLAN", "Architectural"),
            ("A2.0", "ELEVATIONS", "Architectural"),
        ])
        result = parser.split_pages_by_sheets(pages, index)
        assert len(result) == 2

        a1 = next(r for r in result if r["sheet_number"] == "A1.0")
        assert a1["page_start"] == 2
        assert "Floor Plan text" in a1["content"]

        a2 = next(r for r in result if r["sheet_number"] == "A2.0")
        assert a2["page_start"] == 3

    def test_sheet_not_found_in_pages(self, parser):
        pages = self._make_pages(["Cover page only"])
        index = self._make_index([
            ("A1.0", "FLOOR PLAN", "Architectural"),
        ])
        result = parser.split_pages_by_sheets(pages, index)
        assert len(result) == 1
        a1 = result[0]
        assert a1["content"] == ""
        assert a1["page_start"] is None
        assert a1["page_end"] is None

    def test_result_keys(self, parser):
        pages = self._make_pages(["Sheet: A1.0\nSome content"])
        index = self._make_index([("A1.0", "FLOOR PLAN", "Architectural")])
        result = parser.split_pages_by_sheets(pages, index)
        expected_keys = {
            "sheet_number", "title", "discipline",
            "content", "page_start", "page_end",
        }
        assert set(result[0].keys()) == expected_keys

    def test_empty_index(self, parser):
        pages = self._make_pages(["Sheet: A1.0\nSome content"])
        result = parser.split_pages_by_sheets(pages, [])
        assert result == []

    def test_multi_page_sheet(self, parser):
        pages = self._make_pages([
            "Sheet: A1.0\nFloor Plan page 1",
            "Continuation of A1.0",
            "Sheet: A2.0\nElevations",
        ])
        index = self._make_index([
            ("A1.0", "FLOOR PLAN", "Architectural"),
            ("A2.0", "ELEVATIONS", "Architectural"),
        ])
        result = parser.split_pages_by_sheets(pages, index)
        a1 = next(r for r in result if r["sheet_number"] == "A1.0")
        # Should span pages 1 and 2
        assert a1["page_start"] == 1
        assert a1["page_end"] == 2
        assert "Continuation" in a1["content"]
