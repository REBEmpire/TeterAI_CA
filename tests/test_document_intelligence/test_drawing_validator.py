"""
Tests for DrawingValidator — index-to-sheet reconciliation.
"""
import pytest

from document_intelligence.validators.drawing_validator import DrawingValidator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def validator():
    return DrawingValidator()


# ---------------------------------------------------------------------------
# TestReconcile
# ---------------------------------------------------------------------------

class TestReconcile:
    def test_all_matched(self, validator):
        index_sheets = [{"sheet_number": "A1.0", "title": "SITE PLAN"}, {"sheet_number": "A2.1", "title": "FLOOR PLAN"}]
        detected = ["A1.0", "A2.1"]
        results = validator.reconcile(index_sheets, detected)
        assert results["matched"] == ["A1.0", "A2.1"]
        assert results["index_only"] == []
        assert results["document_only"] == []

    def test_index_only(self, validator):
        index_sheets = [{"sheet_number": "A1.0"}, {"sheet_number": "A2.1"}]
        detected = ["A1.0"]
        results = validator.reconcile(index_sheets, detected)
        assert results["index_only"] == ["A2.1"]

    def test_document_only(self, validator):
        index_sheets = [{"sheet_number": "A1.0"}]
        detected = ["A1.0", "A3.0"]
        results = validator.reconcile(index_sheets, detected)
        assert results["document_only"] == ["A3.0"]

    def test_empty_index(self, validator):
        results = validator.reconcile([], ["A1.0"])
        assert results["document_only"] == ["A1.0"]

    def test_empty_detected(self, validator):
        index_sheets = [{"sheet_number": "A1.0"}, {"sheet_number": "A2.0"}]
        results = validator.reconcile(index_sheets, [])
        assert results["index_only"] == ["A1.0", "A2.0"]
        assert results["matched"] == []
        assert results["document_only"] == []

    def test_both_empty(self, validator):
        results = validator.reconcile([], [])
        assert results["matched"] == []
        assert results["index_only"] == []
        assert results["document_only"] == []

    def test_result_keys(self, validator):
        results = validator.reconcile([], [])
        assert set(results.keys()) == {"matched", "index_only", "document_only"}

    def test_lists_are_sorted(self, validator):
        index_sheets = [{"sheet_number": "S1.0"}, {"sheet_number": "A1.0"}, {"sheet_number": "E1.0"}]
        detected = ["E1.0", "A1.0", "S1.0"]
        results = validator.reconcile(index_sheets, detected)
        assert results["matched"] == sorted(results["matched"])

    def test_partial_overlap(self, validator):
        index_sheets = [
            {"sheet_number": "A1.0"},
            {"sheet_number": "A2.0"},
            {"sheet_number": "S1.0"},
        ]
        detected = ["A1.0", "A3.0"]
        results = validator.reconcile(index_sheets, detected)
        assert results["matched"] == ["A1.0"]
        assert results["index_only"] == ["A2.0", "S1.0"]
        assert results["document_only"] == ["A3.0"]


# ---------------------------------------------------------------------------
# TestVerificationStatus
# ---------------------------------------------------------------------------

class TestVerificationStatus:
    def test_assign_status(self, validator):
        recon = {"matched": ["A1.0"], "index_only": ["A2.1"], "document_only": ["A3.0"]}
        assert validator.get_verification_status("A1.0", recon) == "matched"
        assert validator.get_verification_status("A2.1", recon) == "index_only"
        assert validator.get_verification_status("A3.0", recon) == "document_only"
        assert validator.get_verification_status("X9.9", recon) == ""

    def test_unknown_sheet_returns_empty_string(self, validator):
        recon = {"matched": [], "index_only": [], "document_only": []}
        assert validator.get_verification_status("Z9.9", recon) == ""

    def test_matched_status(self, validator):
        recon = {"matched": ["A1.0", "A2.0"], "index_only": [], "document_only": []}
        assert validator.get_verification_status("A1.0", recon) == "matched"
        assert validator.get_verification_status("A2.0", recon) == "matched"

    def test_index_only_status(self, validator):
        recon = {"matched": [], "index_only": ["A1.0"], "document_only": []}
        assert validator.get_verification_status("A1.0", recon) == "index_only"

    def test_document_only_status(self, validator):
        recon = {"matched": [], "index_only": [], "document_only": ["A1.0"]}
        assert validator.get_verification_status("A1.0", recon) == "document_only"


# ---------------------------------------------------------------------------
# TestGenerateReport
# ---------------------------------------------------------------------------

class TestGenerateReport:
    def test_report_keys(self, validator):
        recon = {"matched": ["A1.0"], "index_only": ["A2.0"], "document_only": ["A3.0"]}
        report = validator.generate_report(recon)
        assert set(report.keys()) == {"total", "matched", "index_only", "document_only", "match_rate"}

    def test_report_counts(self, validator):
        recon = {"matched": ["A1.0", "A2.0"], "index_only": ["S1.0"], "document_only": ["E1.0", "E2.0"]}
        report = validator.generate_report(recon)
        assert report["total"] == 5
        assert report["matched"] == 2
        assert report["index_only"] == 1
        assert report["document_only"] == 2

    def test_match_rate_all_matched(self, validator):
        recon = {"matched": ["A1.0", "A2.0"], "index_only": [], "document_only": []}
        report = validator.generate_report(recon)
        assert report["match_rate"] == 1.0

    def test_match_rate_none_matched(self, validator):
        recon = {"matched": [], "index_only": ["A1.0"], "document_only": ["A2.0"]}
        report = validator.generate_report(recon)
        assert report["match_rate"] == 0.0

    def test_match_rate_partial(self, validator):
        recon = {"matched": ["A1.0"], "index_only": ["A2.0"], "document_only": ["A3.0"]}
        report = validator.generate_report(recon)
        # 1/3 rounded to 3 decimals = 0.333
        assert report["match_rate"] == 0.333

    def test_match_rate_rounded_to_3_decimals(self, validator):
        recon = {"matched": ["A1.0", "A2.0"], "index_only": ["S1.0"], "document_only": []}
        report = validator.generate_report(recon)
        # 2/3 rounded to 3 decimals = 0.667
        assert report["match_rate"] == 0.667

    def test_empty_reconciliation(self, validator):
        recon = {"matched": [], "index_only": [], "document_only": []}
        report = validator.generate_report(recon)
        assert report["total"] == 0
        assert report["match_rate"] == 0.0
