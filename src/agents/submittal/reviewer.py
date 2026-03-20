"""
SubmittalReviewer — builds the submittal review prompt and parses structured JSON output.

The system prompt is assembled from:
  1. The core review instructions (hardcoded below).
  2. Text extracted from tests/Submittal Review Template.docx
  3. Text extracted from tests/Submittal Review Comparison.docx

Each model must return a JSON object matching REVIEW_OUTPUT_SCHEMA.
"""

import json
import logging
import os
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths to the reference DOCX files (relative to repo root)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]  # TeterAI_CA/
_TEMPLATE_DOCX = _REPO_ROOT / "tests" / "Submittal Review Template.docx"
_COMPARISON_DOCX = _REPO_ROOT / "tests" / "Submittal Review Comparison.docx"

# ---------------------------------------------------------------------------
# Core review prompt (per user specification)
# ---------------------------------------------------------------------------

_CORE_PROMPT = """You are reviewing a product submittal against the project specifications and drawings for a construction project. Your job is to identify any and all differences, with special attention to anything that could impact code compliance, accessibility, structural requirements, or coordination with other trades.

Instructions:
1. Extract and list all critical dimensions and features from both the project specifications and the submittal, including but not limited to:
   - Size (width x length)
   - Overall footprint and height
   - Required clearances
   - Weight and capacity
   - Power requirements
   - Structural attachment details
   - Safety features
   - Compliance with ADA, local code, and referenced standards

2. Create a side-by-side comparison table of these items, showing:
   - Specified value
   - Submitted value
   - Difference (highlight any increases or decreases)
   - Compliance (Yes/No)
   - Comments/Implications

3. For any item where the submitted value is larger, heavier, or otherwise deviates from the specified value, flag it as a MAJOR_WARNING and explain:
   - How this could affect code compliance (especially accessibility/ADA)
   - Potential impacts on structural design or attachment
   - Possible coordination issues with other trades or existing conditions

4. Summarize all flagged issues in a clear, bulleted list at the end, with recommendations for what to do next (e.g., request resubmittal, require design review, notify architect/engineer).

5. If any information is missing or unclear, note it as a MISSING_INFO_WARNING and recommend follow-up.

6. Do not assume compliance unless the submitted value exactly matches the specified value. If in doubt, flag it for review.

Context: Assume the project was designed with minimal tolerances and any increase in size, weight, or required clearances could cause significant problems. Be thorough and err on the side of caution."""

# ---------------------------------------------------------------------------
# JSON output schema instruction (appended to prompt)
# ---------------------------------------------------------------------------

_JSON_SCHEMA_INSTRUCTION = """
IMPORTANT — Output Format:
You MUST respond with ONLY valid JSON (no markdown, no prose before or after). Use this exact schema:

{
  "comparison_table": [
    {
      "id": "<uuid-v4>",
      "category": "<category string>",
      "item": "<attribute name>",
      "specified_value": "<value from project specs>",
      "submitted_value": "<value from submittal>",
      "difference": "<description of difference, e.g. +2 inches or N/A if identical>",
      "compliance": <true if fully compliant, false otherwise>,
      "severity": "<OK | MINOR_NOTE | MAJOR_WARNING>",
      "comments": "<explanation and implications>"
    }
  ],
  "warnings": [
    {
      "id": "<uuid-v4>",
      "type": "MAJOR_WARNING",
      "description": "<clear description of the problem>",
      "recommendation": "<what to do next>"
    }
  ],
  "missing_info": [
    {
      "id": "<uuid-v4>",
      "type": "MISSING_INFO_WARNING",
      "description": "<what information is missing or unclear>",
      "recommendation": "<how to obtain the missing information>"
    }
  ],
  "summary": "<overall narrative summary of the review findings>"
}

Rules:
- Every item must have a unique id (UUID v4 format).
- severity for comparison_table items: use MAJOR_WARNING if non-compliant or risky, MINOR_NOTE for minor differences, OK if fully compliant.
- All arrays may be empty if not applicable, but must be present.
- Do not include any text outside the JSON object.
"""


def _extract_docx_text(path: Path) -> str:
    """Extract plain text from a DOCX file. Returns empty string on failure."""
    try:
        from docx import Document  # python-docx
        doc = Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)
    except Exception as e:
        logger.warning(f"Could not read DOCX {path}: {e}")
        return ""


def _load_reference_docs() -> str:
    """Load text from the reference DOCX files for inclusion in the system prompt."""
    parts = []

    template_text = _extract_docx_text(_TEMPLATE_DOCX)
    if template_text:
        parts.append(f"--- SUBMITTAL REVIEW TEMPLATE (reference format) ---\n{template_text}")

    comparison_text = _extract_docx_text(_COMPARISON_DOCX)
    if comparison_text:
        parts.append(f"--- SUBMITTAL REVIEW COMPARISON EXAMPLE ---\n{comparison_text}")

    return "\n\n".join(parts)


def build_system_prompt() -> str:
    """Assemble the full system prompt including reference documents."""
    ref_docs = _load_reference_docs()
    parts = [_CORE_PROMPT]
    if ref_docs:
        parts.append(
            "\nThe following reference documents from the project library provide "
            "the expected format and a comparison example:\n\n" + ref_docs
        )
    parts.append(_JSON_SCHEMA_INSTRUCTION)
    return "\n\n".join(parts)


def build_user_prompt(
    submittal_text: str,
    spec_sections: list[str],
    project_id: str,
) -> str:
    """Build the user-turn prompt with the actual submittal content and spec context."""
    spec_block = "\n\n".join(spec_sections) if spec_sections else "No specific spec sections retrieved."
    return (
        f"Project ID: {project_id}\n\n"
        f"=== PROJECT SPECIFICATIONS (relevant sections) ===\n{spec_block}\n\n"
        f"=== SUBMITTAL DOCUMENT CONTENT ===\n{submittal_text}\n\n"
        "Please perform the submittal review as instructed and return only the JSON output."
    )


def parse_review_output(raw_content: str, task_id: str) -> dict:
    """
    Parse the model's raw text response into a validated review dict.
    Assigns UUIDs to any items missing them.
    Returns a dict with keys: comparison_table, warnings, missing_info, summary.
    """
    # Strip markdown code fences if present
    text = raw_content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove opening fence
        lines = lines[1:] if lines[0].startswith("```") else lines
        # Remove closing fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"[{task_id}] Failed to parse model JSON: {e}")
        return {
            "comparison_table": [],
            "warnings": [],
            "missing_info": [],
            "summary": f"[Parse error — model did not return valid JSON: {e}]",
            "parse_error": str(e),
        }

    # Ensure all required keys exist
    result = {
        "comparison_table": data.get("comparison_table", []),
        "warnings": data.get("warnings", []),
        "missing_info": data.get("missing_info", []),
        "summary": data.get("summary", ""),
    }

    # Assign UUIDs to any items missing them
    for section_key in ("comparison_table", "warnings", "missing_info"):
        for item in result[section_key]:
            if not item.get("id"):
                item["id"] = str(uuid.uuid4())

    return result
