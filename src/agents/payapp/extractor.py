import json
import logging

from ai_engine.engine import AIEngine
from ai_engine.models import AIRequest, CapabilityClass

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Pay App Review Agent for Teter Engineering's Construction Administration system.
Extract structured information from a Pay Application (AIA G702/G703 or similar format).
Respond ONLY with valid JSON — no markdown, no explanation.

Return JSON exactly matching this schema (no extra keys):
{
  "application_number": "<pay application number as string, or UNKNOWN>",
  "period_to": "<billing period end date as YYYY-MM-DD, or null>",
  "retainage_pct": "<retainage percentage as string, e.g. '10%', or null>",
  "total_claimed": "<total amount claimed this period as string, e.g. '$45,000.00', or UNKNOWN>",
  "line_items": [
    {
      "description": "<description of this schedule of values line item>",
      "scheduled_value": "<scheduled value as string, e.g. '$120,000.00', or null>",
      "previous_billings": "<previous billings total as string, or null>",
      "this_period_pct": "<percent complete claimed this period as string, e.g. '25%', or null>",
      "this_period_amount": "<dollar amount claimed this period as string, or null>",
      "stored_materials": "<stored materials amount as string, or null>"
    }
  ]
}"""


class PayAppExtractor:
    def __init__(self, ai_engine: AIEngine):
        self._engine = ai_engine

    def extract(self, document_text: str, task_id: str) -> dict:
        """
        Extract structured pay application data from document text.

        Args:
            document_text: Raw text of the pay application document.
            task_id: Task ID for audit logging.

        Returns:
            Dict with keys: application_number, period_to, retainage_pct,
                            total_claimed, line_items.
        """
        user_prompt = (
            f"DOCUMENT TEXT:\n{document_text[:4000]}"
        )

        request = AIRequest(
            capability_class=CapabilityClass.EXTRACT,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.0,
            calling_agent="AGENT-PAYAPP-001",
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
            return {
                "application_number": data.get("application_number", "UNKNOWN"),
                "period_to": data.get("period_to"),
                "retainage_pct": data.get("retainage_pct"),
                "total_claimed": data.get("total_claimed", "UNKNOWN"),
                "line_items": data.get("line_items") or [],
            }
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            logger.error(
                f"[{task_id}] Failed to parse pay app extraction response: {e}\n"
                f"Raw (first 500 chars): {response.content[:500]}"
            )
            raise ValueError(f"Invalid pay app extraction JSON from AI: {e}") from e
