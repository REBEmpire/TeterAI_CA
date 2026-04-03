import json
import logging

from ai_engine.engine import AIEngine
from ai_engine.models import AIRequest, CapabilityClass

from .models import RFIExtraction, RFIExtractionParseError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the RFI Agent for Teter Engineering's Construction Administration system.
Extract structured information from the RFI email and any attachment text provided.
Respond ONLY with valid JSON — no markdown, no explanation.

Return JSON exactly matching this schema (no extra keys):
{
  "rfi_number_submitted": "<contractor's RFI number as string, or UNKNOWN>",
  "contractor_name": "<company name>",
  "contractor_contact": "<contact person name, or null>",
  "question": "<the full question or clarification being requested>",
  "referenced_spec_sections": ["<CSI section numbers e.g. '03 30 00'>"],
  "referenced_drawing_sheets": ["<drawing sheet IDs e.g. 'S-101'>"],
  "date_submitted": "<YYYY-MM-DD or null>",
  "response_requested_by": "<YYYY-MM-DD or null>",
  "attachments_analyzed": ["<attachment filenames>"]
}"""


class RFIExtractor:
    def __init__(self, ai_engine: AIEngine):
        self._engine = ai_engine

    def extract(self, ingest: dict, task_id: str) -> RFIExtraction:
        subject = ingest.get("subject", "")
        sender_name = ingest.get("sender_name", "")
        sender_email = ingest.get("sender_email", "")
        body_text = ingest.get("body_text") or ""
        attachment_paths = ingest.get("attachment_drive_paths") or []
        if attachment_paths:
            attachment_names = [p.split("/")[-1] for p in attachment_paths]
        else:
            attachment_names = [
                m.get("filename", "")
                for m in (ingest.get("attachment_metadata") or [])
                if m.get("filename")
            ]
        attachments_str = ", ".join(attachment_names) if attachment_names else "none"

        user_prompt = (
            f"FROM: {sender_name} <{sender_email}>\n"
            f"SUBJECT: {subject}\n"
            f"ATTACHMENTS: {attachments_str}\n"
            f"BODY:\n{body_text[:3000]}"
        )

        request = AIRequest(
            capability_class=CapabilityClass.EXTRACT,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.0,
            calling_agent="AGENT-RFI-001",
            task_id=task_id,
        )

        response = self._engine.generate_response(request)

        try:
            raw = response.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            data = json.loads(raw)
            return RFIExtraction(
                rfi_number_submitted=data.get("rfi_number_submitted", "UNKNOWN"),
                contractor_name=data.get("contractor_name", ""),
                contractor_contact=data.get("contractor_contact"),
                question=data.get("question", ""),
                referenced_spec_sections=data.get("referenced_spec_sections") or [],
                referenced_drawing_sheets=data.get("referenced_drawing_sheets") or [],
                date_submitted=data.get("date_submitted"),
                response_requested_by=data.get("response_requested_by"),
                attachments_analyzed=data.get("attachments_analyzed") or [],
                raw_response=response.content,
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            logger.error(
                f"[{task_id}] Failed to parse RFI extraction response: {e}\n"
                f"Raw (first 500 chars): {response.content[:500]}"
            )
            raise RFIExtractionParseError(f"Invalid extraction JSON from AI: {e}") from e
