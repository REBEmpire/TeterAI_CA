"""
Tests for SpecValidator — TOC-to-content cross-validation.
"""
import pytest

from document_intelligence.validators.spec_validator import SpecValidator


@pytest.fixture
def validator():
    return SpecValidator()


# ---------------------------------------------------------------------------
# TestValidateSections
# ---------------------------------------------------------------------------

class TestValidateSections:
    def test_matched_section(self, validator):
        toc_sections = [{"section_number": "09 21 16", "title": "GYPSUM BOARD", "page_number": 5}]
        pages = {5: "SECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES\nPART 1 - GENERAL"}
        results = validator.validate_sections(toc_sections, pages)
        assert results[0]["status"] == "matched"

    def test_mismatched_section(self, validator):
        toc_sections = [{"section_number": "09 21 16", "title": "GYPSUM BOARD", "page_number": 5}]
        pages = {5: "SECTION 07 92 00 - JOINT SEALANTS\nPART 1 - GENERAL"}
        results = validator.validate_sections(toc_sections, pages)
        assert results[0]["status"] == "mismatch"

    def test_page_not_found(self, validator):
        toc_sections = [{"section_number": "09 21 16", "title": "GYPSUM BOARD", "page_number": 999}]
        pages = {1: "Some content"}
        results = validator.validate_sections(toc_sections, pages)
        assert results[0]["status"] == "page_not_found"

    def test_result_keys(self, validator):
        toc_sections = [{"section_number": "09 21 16", "title": "GYPSUM BOARD", "page_number": 5}]
        pages = {5: "SECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES\nPART 1 - GENERAL"}
        results = validator.validate_sections(toc_sections, pages)
        assert set(results[0].keys()) == {"section_number", "title", "toc_page", "actual_page", "status"}

    def test_result_toc_page_and_actual_page(self, validator):
        toc_sections = [{"section_number": "09 21 16", "title": "GYPSUM BOARD", "page_number": 5}]
        pages = {5: "SECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES\nPART 1 - GENERAL"}
        results = validator.validate_sections(toc_sections, pages)
        assert results[0]["toc_page"] == 5
        assert results[0]["actual_page"] == 5

    def test_page_offset_applied(self, validator):
        toc_sections = [{"section_number": "09 21 16", "title": "GYPSUM BOARD", "page_number": 10}]
        # With offset=2, look at page 10+2=12
        pages = {12: "SECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES\nPART 1 - GENERAL"}
        results = validator.validate_sections(toc_sections, pages, page_offset=2)
        assert results[0]["status"] == "matched"
        assert results[0]["actual_page"] == 12

    def test_multiple_sections_mixed(self, validator):
        toc_sections = [
            {"section_number": "09 21 16", "title": "GYPSUM BOARD", "page_number": 5},
            {"section_number": "07 92 00", "title": "JOINT SEALANTS", "page_number": 10},
            {"section_number": "03 30 00", "title": "CONCRETE", "page_number": 999},
        ]
        pages = {
            5: "SECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES",
            10: "SECTION 07 00 00 - THERMAL AND MOISTURE PROTECTION",  # different section on page
        }
        results = validator.validate_sections(toc_sections, pages)
        assert results[0]["status"] == "matched"
        assert results[1]["status"] == "mismatch"
        assert results[2]["status"] == "page_not_found"

    def test_empty_toc_returns_empty(self, validator):
        results = validator.validate_sections([], {1: "Some content"})
        assert results == []

    def test_section_number_spaces_stripped_for_comparison(self, validator):
        """CSI numbers in page text with no spaces should still match."""
        toc_sections = [{"section_number": "09 21 16", "title": "GYPSUM BOARD", "page_number": 5}]
        pages = {5: "SECTION 092116 - GYPSUM BOARD ASSEMBLIES\nPART 1"}
        results = validator.validate_sections(toc_sections, pages)
        assert results[0]["status"] == "matched"

    def test_not_found_actual_page_is_none(self, validator):
        toc_sections = [{"section_number": "09 21 16", "title": "GYPSUM BOARD", "page_number": 999}]
        pages = {1: "Some content"}
        results = validator.validate_sections(toc_sections, pages)
        assert results[0]["actual_page"] is None


# ---------------------------------------------------------------------------
# TestDetectPageOffset
# ---------------------------------------------------------------------------

class TestDetectPageOffset:
    def test_detect_offset(self, validator):
        toc_sections = [
            {"section_number": "09 21 16", "page_number": 100},
            {"section_number": "07 92 00", "page_number": 80},
        ]
        pages = {98: "SECTION 09 21 16", 78: "SECTION 07 92 00"}
        offset = validator.detect_page_offset(toc_sections, pages)
        assert offset == -2

    def test_no_offset_needed(self, validator):
        toc_sections = [{"section_number": "09 21 16", "page_number": 10}]
        pages = {10: "SECTION 09 21 16"}
        assert validator.detect_page_offset(toc_sections, pages) == 0

    def test_positive_offset(self, validator):
        toc_sections = [
            {"section_number": "09 21 16", "page_number": 5},
            {"section_number": "07 92 00", "page_number": 8},
        ]
        # Pages shifted by +3 from TOC references
        pages = {8: "SECTION 09 21 16", 11: "SECTION 07 92 00"}
        offset = validator.detect_page_offset(toc_sections, pages)
        assert offset == 3

    def test_returns_zero_when_no_sections_match(self, validator):
        toc_sections = [{"section_number": "09 21 16", "page_number": 50}]
        pages = {1: "No matching content here"}
        offset = validator.detect_page_offset(toc_sections, pages)
        assert offset == 0

    def test_empty_toc_returns_zero(self, validator):
        assert validator.detect_page_offset([], {1: "content"}) == 0

    def test_custom_search_range(self, validator):
        toc_sections = [{"section_number": "09 21 16", "page_number": 10}]
        # Offset of +5 — within range of 5
        pages = {15: "SECTION 09 21 16"}
        offset = validator.detect_page_offset(toc_sections, pages, search_range=5)
        assert offset == 5


# ---------------------------------------------------------------------------
# TestGenerateReport
# ---------------------------------------------------------------------------

class TestGenerateReport:
    def test_all_matched(self, validator):
        results = [
            {"status": "matched"},
            {"status": "matched"},
            {"status": "matched"},
        ]
        report = validator.generate_report(results)
        assert report["total"] == 3
        assert report["matched"] == 3
        assert report["mismatched"] == 0
        assert report["not_found"] == 0
        assert report["match_rate"] == 1.0

    def test_all_mismatched(self, validator):
        results = [{"status": "mismatch"}, {"status": "mismatch"}]
        report = validator.generate_report(results)
        assert report["matched"] == 0
        assert report["mismatched"] == 2
        assert report["match_rate"] == 0.0

    def test_mixed_results(self, validator):
        results = [
            {"status": "matched"},
            {"status": "matched"},
            {"status": "mismatch"},
            {"status": "page_not_found"},
        ]
        report = validator.generate_report(results)
        assert report["total"] == 4
        assert report["matched"] == 2
        assert report["mismatched"] == 1
        assert report["not_found"] == 1
        assert report["match_rate"] == 0.5

    def test_match_rate_rounded_to_3_decimals(self, validator):
        results = [{"status": "matched"}] * 2 + [{"status": "mismatch"}]
        report = validator.generate_report(results)
        # 2/3 = 0.6666... → 0.667
        assert report["match_rate"] == round(2 / 3, 3)

    def test_empty_results(self, validator):
        report = validator.generate_report([])
        assert report["total"] == 0
        assert report["match_rate"] == 0.0

    def test_report_keys(self, validator):
        report = validator.generate_report([{"status": "matched"}])
        assert set(report.keys()) == {"total", "matched", "mismatched", "not_found", "match_rate"}
