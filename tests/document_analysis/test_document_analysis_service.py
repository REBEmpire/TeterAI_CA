import pytest
from src.document_analysis.document_analysis_service import DocumentAnalysisService

class TestDocumentAnalysisService:
    def setup_method(self):
        # The method _parse_analysis_content doesn't use any instance variables,
        # so we can instantiate the service without any external dependencies.
        self.service = DocumentAnalysisService()

    def test_parse_analysis_content_fallback_with_sections(self):
        """Test fallback parser correctly extracts sections from formatted plain text."""
        content = """
Here is the analysis of the document.

Summary:
This document outlines the main architecture of the new bridge project. It focuses on the structural requirements and safety measures.

The findings are as follows:
- The structural integrity meets safety standards.
- Several cost-saving measures can be applied.
- Environmental impact is minimal.
- Project timeline is feasible.
- Local community supports the project.
- Extra finding that should be ignored since limit is 5.
"""
        result = self.service._parse_analysis_content(content)

        assert "summary" in result
        assert result["summary"] == "This document outlines the main architecture of the new bridge project. It focuses on the structural requirements and safety measures."

        assert "key_findings" in result
        assert len(result["key_findings"]) == 5
        assert result["key_findings"][0] == "The structural integrity meets safety standards."
        assert result["key_findings"][4] == "Local community supports the project."

    def test_parse_analysis_content_fallback_plain_text(self):
        """Test fallback parser handles plain unstructured text properly."""
        # Avoiding words that might trigger the regex (like the word "summary")
        content = "This is a very simple plain text response that does not contain any specific sum-mary keyword or bulleted findings. " * 10

        result = self.service._parse_analysis_content(content)

        assert "summary" in result
        assert "key_findings" not in result

        # In actual logic, result["summary"] is content[:500] + "..."
        # so length is 500 + 3 = 503
        assert len(result["summary"]) == 503
        assert result["summary"].endswith("...")
        assert result["summary"].startswith("This is a very simple plain text")

    def test_parse_analysis_content_invalid_json_fallback(self):
        """Test fallback parser activates when response contains invalid JSON block."""
        # Using a word that doesn't trigger the "summary:" regex prematurely within the invalid JSON
        content = """```json
{
    "desc": "This JSON is broken",
    "key_findings": [
        "Missing closing brace for the array and object"
```

Summary:
The fallback mechanism should pick this up instead.

- Finding 1
- Finding 2"""
        result = self.service._parse_analysis_content(content)

        assert "summary" in result
        assert result["summary"] == "The fallback mechanism should pick this up instead."

        assert "key_findings" in result
        assert len(result["key_findings"]) == 2
        assert result["key_findings"][0] == "Finding 1"
        assert result["key_findings"][1] == "Finding 2"

    def test_parse_analysis_content_invalid_raw_json_fallback(self):
        """Test fallback parser activates when response contains invalid raw JSON."""
        # Using a word that doesn't trigger the "summary:" regex prematurely within the invalid JSON
        content = """{
    "desc": "This raw JSON is broken,
    "key_findings": [
        "Unclosed string"
    ]
}

Summary:
Fallback parser FTW.

* Finding A
* Finding B"""
        result = self.service._parse_analysis_content(content)

        assert "summary" in result
        assert result["summary"] == "Fallback parser FTW."

        assert "key_findings" in result
        assert len(result["key_findings"]) == 2
        assert result["key_findings"][0] == "Finding A"
        assert result["key_findings"][1] == "Finding B"
