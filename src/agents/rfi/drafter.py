import logging
import os
from datetime import date

from ai_engine.engine import AIEngine
from ai_engine.models import AIRequest, CapabilityClass

from .models import RFIExtraction, KGLookupResult, RFIResponse

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the RFI Agent for Teter Engineering's Construction Administration system.
Draft a professional RFI response based on the provided RFI question, spec citations, and playbook guidance.

Your response must be formatted EXACTLY as follows (no deviations):

RESPONSE:
<substantive response text, citing specifications in format "Specification Section XX XX XX, Paragraph X.X.X">

REFERENCES:
- <reference 1>
- <reference 2>

CONFIDENCE: <decimal 0.00 to 1.00>
CONFIDENCE_REASONING: <one sentence explaining your confidence level>

Confidence scoring criteria:
- High (0.75–1.00): Clear spec citations available, question is unambiguous, no design judgment required
- Medium (0.50–0.74): Some ambiguity, limited spec coverage, or minor design judgment involved
- Low (0.00–0.49): Significant ambiguity, missing spec info, or design decision required — escalate

Respond ONLY with the formatted content above — no additional commentary."""

_MAX_SPEC_CITATIONS = int(os.environ.get("RFI_MAX_SPEC_CITATIONS", 5))
_THRESHOLD_STAGE = float(os.environ.get("RFI_CONFIDENCE_THRESHOLD_STAGE", 0.75))
_THRESHOLD_ESCALATE = float(os.environ.get("RFI_CONFIDENCE_THRESHOLD_ESCALATE", 0.50))


def _format_spec_sections(sections: list) -> str:
    if not sections:
        return "None found in knowledge graph."
    lines = []
    for s in sections[:_MAX_SPEC_CITATIONS]:
        lines.append(
            f"  - Section {s.get('section_number', 'N/A')} — {s.get('title', 'N/A')}: "
            f"{s.get('content_summary', 'No summary available.')}"
        )
    return "\n".join(lines)


def _format_playbook_rules(rules: list) -> str:
    if not rules:
        return "None."
    lines = []
    for r in rules:
        lines.append(f"  - [{r.get('condition', '')}]: {r.get('action', '')}")
    return "\n".join(lines)


class RFIDrafter:
    def __init__(self, ai_engine: AIEngine):
        self._engine = ai_engine

    def draft(
        self,
        extraction: RFIExtraction,
        kg_result: KGLookupResult,
        task_id: str,
        project_id: str = "UNKNOWN",
        project_name: str = "",
        rfi_number_internal: str = "RFI-???",
    ) -> RFIResponse:
        today = date.today().isoformat()
        spec_sections_str = _format_spec_sections(kg_result.spec_sections)
        playbook_str = _format_playbook_rules(kg_result.playbook_rules)

        user_prompt = (
            f"PROJECT: {project_id}{' — ' + project_name if project_name else ''}\n"
            f"RFI #: {rfi_number_internal}\n"
            f"DATE: {today}\n"
            f"FROM: Teter Architects\n"
            f"TO: {extraction.contractor_name}\n"
            f"RE: RFI-{extraction.rfi_number_submitted}\n\n"
            f"CONTRACTOR'S QUESTION:\n{extraction.question}\n\n"
            f"REFERENCED SPEC SECTIONS (from contractor): "
            f"{', '.join(extraction.referenced_spec_sections) or 'None'}\n"
            f"REFERENCED DRAWING SHEETS (from contractor): "
            f"{', '.join(extraction.referenced_drawing_sheets) or 'None'}\n\n"
            f"SPEC SECTIONS FROM KNOWLEDGE GRAPH:\n{spec_sections_str}\n\n"
            f"PLAYBOOK GUIDANCE:\n{playbook_str}\n\n"
            "Draft a professional response addressing the contractor's question."
        )

        request = AIRequest(
            capability_class=CapabilityClass.REASON_DEEP,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
            calling_agent="AGENT-RFI-001",
            task_id=task_id,
        )

        response = self._engine.generate_response(request)
        raw = response.content

        response_text, references, confidence_score = self._parse_draft(raw, task_id)

        if confidence_score >= _THRESHOLD_STAGE:
            review_flag = None
        elif confidence_score >= _THRESHOLD_ESCALATE:
            review_flag = "REVIEW_CAREFULLY"
        else:
            review_flag = "ESCALATED"

        header = (
            f"PROJECT: {project_id}{' — ' + project_name if project_name else ''}\n"
            f"RFI #: {rfi_number_internal}\n"
            f"DATE: {today}\n"
            f"FROM: Teter Architects\n"
            f"TO: {extraction.contractor_name}\n"
            f"RE: RFI-{extraction.rfi_number_submitted}"
        )

        return RFIResponse(
            header=header,
            response_text=response_text,
            references=references,
            confidence_score=confidence_score,
            review_flag=review_flag,
            raw_response=raw,
        )

    def _parse_draft(self, raw: str, task_id: str) -> tuple:
        """Parse structured draft response. Returns (response_text, references, confidence)."""
        response_text = ""
        references: list[str] = []
        confidence_score = 0.5  # conservative default if parsing fails

        try:
            lines = raw.splitlines()
            section = None
            resp_lines: list[str] = []
            ref_lines: list[str] = []

            for line in lines:
                stripped = line.strip()
                if stripped == "RESPONSE:":
                    section = "response"
                    continue
                elif stripped == "REFERENCES:":
                    section = "references"
                    continue
                elif (
                    stripped.startswith("CONFIDENCE:")
                    and not stripped.startswith("CONFIDENCE_REASONING:")
                ):
                    try:
                        confidence_score = float(stripped.split(":", 1)[1].strip())
                    except ValueError:
                        pass
                    continue
                elif stripped.startswith("CONFIDENCE_REASONING:"):
                    continue

                if section == "response":
                    resp_lines.append(line)
                elif section == "references" and stripped.startswith("- "):
                    ref_lines.append(stripped[2:])

            response_text = "\n".join(resp_lines).strip()
            references = ref_lines

        except Exception as e:
            logger.warning(
                f"[{task_id}] Draft parse warning: {e} — using raw content as response"
            )
            response_text = raw
            references = []

        return response_text, references, confidence_score
