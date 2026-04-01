"""
Tests for SpecParser — TOC detection, section splitting, and CSI pattern matching.
"""
import pytest

from document_intelligence.parsers.spec_parser import SpecParser


@pytest.fixture
def parser():
    return SpecParser()


# ---------------------------------------------------------------------------
# TestParseTocLines
# ---------------------------------------------------------------------------

class TestParseTocLines:
    def test_standard_toc_line(self, parser):
        lines = [
            "SECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES ....... 412",
            "SECTION 07 92 00 - JOINT SEALANTS ............... 380",
        ]
        sections = parser.parse_toc_lines(lines)
        assert len(sections) == 2
        assert sections[0]["section_number"] == "09 21 16"
        assert sections[0]["title"] == "GYPSUM BOARD ASSEMBLIES"
        assert sections[0]["page_number"] == 412

    def test_second_toc_entry(self, parser):
        lines = [
            "SECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES ....... 412",
            "SECTION 07 92 00 - JOINT SEALANTS ............... 380",
        ]
        sections = parser.parse_toc_lines(lines)
        assert sections[1]["section_number"] == "07 92 00"
        assert sections[1]["title"] == "JOINT SEALANTS"
        assert sections[1]["page_number"] == 380

    def test_toc_line_without_dots(self, parser):
        lines = ["SECTION 03 30 00 - CAST-IN-PLACE CONCRETE 150"]
        sections = parser.parse_toc_lines(lines)
        assert len(sections) == 1
        assert sections[0]["section_number"] == "03 30 00"

    def test_toc_line_without_dots_title(self, parser):
        lines = ["SECTION 03 30 00 - CAST-IN-PLACE CONCRETE 150"]
        sections = parser.parse_toc_lines(lines)
        assert sections[0]["title"] == "CAST-IN-PLACE CONCRETE"
        assert sections[0]["page_number"] == 150

    def test_toc_line_no_section_prefix(self, parser):
        lines = ["09 21 16 GYPSUM BOARD ASSEMBLIES 412"]
        sections = parser.parse_toc_lines(lines)
        assert len(sections) == 1

    def test_toc_line_no_section_prefix_content(self, parser):
        lines = ["09 21 16 GYPSUM BOARD ASSEMBLIES 412"]
        sections = parser.parse_toc_lines(lines)
        assert sections[0]["section_number"] == "09 21 16"

    def test_non_matching_lines_ignored(self, parser):
        lines = ["This is a random line", "Page 5 of 10", ""]
        assert parser.parse_toc_lines(lines) == []

    def test_division_inferred(self, parser):
        lines = ["SECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES ....... 412"]
        sections = parser.parse_toc_lines(lines)
        assert sections[0]["division"] == "09"

    def test_division_inferred_different(self, parser):
        lines = ["SECTION 03 30 00 - CAST-IN-PLACE CONCRETE 150"]
        sections = parser.parse_toc_lines(lines)
        assert sections[0]["division"] == "03"

    def test_mixed_lines(self, parser):
        lines = [
            "TABLE OF CONTENTS",
            "SECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES ....... 412",
            "Page 1",
            "SECTION 07 92 00 - JOINT SEALANTS ............... 380",
        ]
        sections = parser.parse_toc_lines(lines)
        assert len(sections) == 2

    def test_compact_section_number_normalized(self, parser):
        """Compact section numbers like 092116 are normalized to 09 21 16."""
        lines = ["SECTION 092116 - GYPSUM BOARD ASSEMBLIES 412"]
        sections = parser.parse_toc_lines(lines)
        assert len(sections) == 1
        assert sections[0]["section_number"] == "09 21 16"

    def test_page_number_is_int(self, parser):
        lines = ["SECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES ....... 412"]
        sections = parser.parse_toc_lines(lines)
        assert isinstance(sections[0]["page_number"], int)

    def test_page_number_none_when_missing(self, parser):
        """Lines with no trailing page number return page_number=None."""
        lines = ["SECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES"]
        sections = parser.parse_toc_lines(lines)
        # Should still match, just no page number
        if sections:
            assert sections[0]["page_number"] is None

    def test_result_keys(self, parser):
        lines = ["SECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES ....... 412"]
        sections = parser.parse_toc_lines(lines)
        assert set(sections[0].keys()) == {"section_number", "title", "page_number", "division"}


# ---------------------------------------------------------------------------
# TestInferDivision
# ---------------------------------------------------------------------------

class TestInferDivision:
    def test_infer_division(self, parser):
        assert parser.infer_division("09 21 16") == "09"
        assert parser.infer_division("03 30 00") == "03"

    def test_infer_division_07(self, parser):
        assert parser.infer_division("07 92 00") == "07"

    def test_infer_division_single_digit_padded(self, parser):
        assert parser.infer_division("01 10 00") == "01"

    def test_infer_division_high(self, parser):
        assert parser.infer_division("32 10 00") == "32"


# ---------------------------------------------------------------------------
# TestNormalizeSectionNumber
# ---------------------------------------------------------------------------

class TestNormalizeSectionNumber:
    def test_already_spaced(self, parser):
        assert parser._normalize_section_number("09 21 16") == "09 21 16"

    def test_compact_6_digits(self, parser):
        assert parser._normalize_section_number("092116") == "09 21 16"

    def test_compact_different(self, parser):
        assert parser._normalize_section_number("033000") == "03 30 00"

    def test_strips_extra_whitespace(self, parser):
        assert parser._normalize_section_number("09  21  16") == "09 21 16"


# ---------------------------------------------------------------------------
# TestDetectSectionHeaders
# ---------------------------------------------------------------------------

class TestDetectSectionHeaders:
    def test_detect_section_header_in_text(self, parser):
        text = "Some preamble\nSECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES\nPART 1"
        headers = parser.detect_section_headers(text)
        assert len(headers) == 1
        assert headers[0]["section_number"] == "09 21 16"

    def test_detect_multiple_headers(self, parser):
        text = (
            "SECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES\n"
            "Some body text\n"
            "SECTION 07 92 00 - JOINT SEALANTS\n"
        )
        headers = parser.detect_section_headers(text)
        assert len(headers) == 2

    def test_header_title_captured(self, parser):
        text = "SECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES\nPART 1"
        headers = parser.detect_section_headers(text)
        assert headers[0]["title"] == "GYPSUM BOARD ASSEMBLIES"

    def test_no_headers_returns_empty(self, parser):
        text = "Some random construction spec text.\nNo section headers here."
        headers = parser.detect_section_headers(text)
        assert headers == []

    def test_result_keys(self, parser):
        text = "SECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES\n"
        headers = parser.detect_section_headers(text)
        assert set(headers[0].keys()) == {"section_number", "title"}

    def test_header_not_matched_mid_line(self, parser):
        """SECTION header in the middle of a line should not match (requires start of line)."""
        text = "  SECTION 09 21 16 - TITLE\n"
        # indented — should NOT match (must be start of line)
        headers = parser.detect_section_headers(text)
        assert headers == []


# ---------------------------------------------------------------------------
# TestSplitPagesBySections
# ---------------------------------------------------------------------------

class TestSplitPagesBySections:
    def _make_pages(self, count: int, text_prefix: str = "page") -> list[dict]:
        return [
            {"page_number": i + 1, "text": f"{text_prefix} {i + 1} content"}
            for i in range(count)
        ]

    def test_basic_split(self, parser):
        pages = self._make_pages(10)
        toc_sections = [
            {"section_number": "09 21 16", "title": "GYPSUM BOARD", "page_number": 1, "division": "09"},
            {"section_number": "07 92 00", "title": "JOINT SEALANTS", "page_number": 5, "division": "07"},
        ]
        chunks = parser.split_pages_by_sections(pages, toc_sections)
        assert len(chunks) == 2
        assert chunks[0]["section_number"] == "09 21 16"
        assert chunks[0]["page_start"] == 1
        assert chunks[0]["page_end"] == 4
        assert chunks[1]["section_number"] == "07 92 00"
        assert chunks[1]["page_start"] == 5
        assert chunks[1]["page_end"] == 10

    def test_result_keys(self, parser):
        pages = self._make_pages(5)
        toc_sections = [
            {"section_number": "09 21 16", "title": "GYPSUM BOARD", "page_number": 1, "division": "09"},
        ]
        chunks = parser.split_pages_by_sections(pages, toc_sections)
        required = {"section_number", "title", "division", "content", "page_start", "page_end"}
        assert required == set(chunks[0].keys())

    def test_content_contains_page_text(self, parser):
        pages = self._make_pages(3)
        toc_sections = [
            {"section_number": "09 21 16", "title": "GYPSUM BOARD", "page_number": 1, "division": "09"},
        ]
        chunks = parser.split_pages_by_sections(pages, toc_sections)
        assert "page 1 content" in chunks[0]["content"]
        assert "page 2 content" in chunks[0]["content"]
        assert "page 3 content" in chunks[0]["content"]

    def test_empty_toc_returns_empty(self, parser):
        pages = self._make_pages(5)
        chunks = parser.split_pages_by_sections(pages, [])
        assert chunks == []

    def test_page_offset(self, parser):
        """page_offset shifts the effective page numbers for matching."""
        pages = [
            {"page_number": 1, "text": "section A content"},
            {"page_number": 2, "text": "section B content"},
            {"page_number": 3, "text": "section B more"},
        ]
        # TOC refers to PDF absolute pages 101 and 102, but our pages list starts at 1
        toc_sections = [
            {"section_number": "09 21 16", "title": "GYPSUM BOARD", "page_number": 101, "division": "09"},
            {"section_number": "07 92 00", "title": "JOINT SEALANTS", "page_number": 102, "division": "07"},
        ]
        chunks = parser.split_pages_by_sections(pages, toc_sections, page_offset=100)
        assert len(chunks) == 2
        assert chunks[0]["page_start"] == 1
        assert chunks[1]["page_start"] == 2

    def test_three_sections(self, parser):
        pages = self._make_pages(9)
        toc_sections = [
            {"section_number": "03 30 00", "title": "CONCRETE", "page_number": 1, "division": "03"},
            {"section_number": "07 92 00", "title": "SEALANTS", "page_number": 4, "division": "07"},
            {"section_number": "09 21 16", "title": "GYPSUM BOARD", "page_number": 7, "division": "09"},
        ]
        chunks = parser.split_pages_by_sections(pages, toc_sections)
        assert len(chunks) == 3
        assert chunks[0]["page_end"] == 3
        assert chunks[1]["page_start"] == 4
        assert chunks[1]["page_end"] == 6
        assert chunks[2]["page_start"] == 7
        assert chunks[2]["page_end"] == 9
