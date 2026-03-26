import json
import logging

from ai_engine.engine import AIEngine
from ai_engine.models import AIRequest, CapabilityClass

from .models import ClassificationResult, DimensionResult, ClassificationParseError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Dispatcher Agent for Teter Engineering's Construction Administration system.
Classify the incoming email across exactly 4 dimensions. Respond ONLY with valid JSON — no markdown, no explanation.

DOCUMENT TYPES: RFI, SUBMITTAL, SUBSTITUTION, CHANGE_ORDER, PAY_APP, MEETING_MINUTES, GENERAL, UNKNOWN,
  COST_ANALYSIS, PAY_APP_REVIEW, SCHEDULE_REVIEW

Document type keyword guidance:
  COST_ANALYSIS  — keywords: "pco", "proposed change", "change order", "cost proposal", "cr-"
  PAY_APP_REVIEW — keywords: "pay application", "pay app", "application for payment", "g702", "schedule of values"
  SCHEDULE_REVIEW — keywords: "schedule", "look-ahead", "progress schedule", "p6", "primavera", "baseline"

PHASES: bid, construction, closeout, UNKNOWN
URGENCY RULES:
  HIGH   — explicit deadline within 5 business days, or phrases like "urgent", "ASAP", "holding work", "cannot proceed"
  MEDIUM — routine request, no stated deadline
  LOW    — informational, FYI, no action needed

PROJECT ID — extract the Teter project identifier from subject hints or email body (e.g. "2024-001", "TEC-205").
Use "UNKNOWN" if no project identifier is determinable.

Return JSON exactly matching this schema (no extra keys):
{
  "project_id":    {"value": "<id or UNKNOWN>", "confidence": 0.00, "reasoning": "<1 sentence>"},
  "phase":         {"value": "<phase>",          "confidence": 0.00, "reasoning": "<1 sentence>"},
  "document_type": {"value": "<type>",           "confidence": 0.00, "reasoning": "<1 sentence>"},
  "urgency":       {"value": "<urgency>",        "confidence": 0.00, "reasoning": "<1 sentence>"}
}"""


class EmailClassifier:
    def __init__(self, ai_engine: AIEngine):
        self._engine = ai_engine

    def classify(self, ingest: dict) -> ClassificationResult:
        ingest_id = ingest.get("ingest_id", "unknown")
        subject = ingest.get("subject", "")
        sender_name = ingest.get("sender_name", "")
        sender_email = ingest.get("sender_email", "")
        body_text = ingest.get("body_text") or ""
        subject_hints = ingest.get("subject_hints") or {}
        attachment_paths = ingest.get("attachment_drive_paths") or []

        if not body_text:
            logger.warning(f"[{ingest_id}] Empty body_text — classifying from subject only.")

        attachment_names = [p.split("/")[-1] for p in attachment_paths] if attachment_paths else []
        attachments_str = ", ".join(attachment_names) if attachment_names else "none"

        user_prompt = (
            f"FROM: {sender_name} <{sender_email}>\n"
            f"SUBJECT: {subject}\n"
            f"SUBJECT HINTS: doc_type={subject_hints.get('doc_type_hint', 'none')}, "
            f"doc_number={subject_hints.get('doc_number_hint', 'none')}, "
            f"project={subject_hints.get('project_number_hint', 'none')}, "
            f"is_reply={subject_hints.get('is_reply', False)}\n"
            f"ATTACHMENTS: {attachments_str}\n"
            f"BODY:\n{body_text[:2000]}"
        )

        request = AIRequest(
            capability_class=CapabilityClass.CLASSIFY,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.0,
            calling_agent="AGENT-DISPATCH-001",
            task_id=ingest_id,
        )

        response = self._engine.generate_response(request)

        try:
            raw = response.content.strip()
            # Strip markdown code fences if model wraps output despite instructions
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            data = json.loads(raw)
            return ClassificationResult(
                project_id=DimensionResult(**data["project_id"]),
                phase=DimensionResult(**data["phase"]),
                document_type=DimensionResult(**data["document_type"]),
                urgency=DimensionResult(**data["urgency"]),
                raw_response=response.content,
                ai_call_id=response.metadata.ai_call_id,
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            logger.error(
                f"[{ingest_id}] Failed to parse classification response: {e}\n"
                f"Raw (first 500 chars): {response.content[:500]}"
            )
            raise ClassificationParseError(f"Invalid classification JSON from AI: {e}") from e
