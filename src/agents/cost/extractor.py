import json
import logging

from ai_engine.engine import AIEngine
from ai_engine.models import AIRequest, CapabilityClass

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Cost Analyzer Agent for Teter Engineering's Construction Administration system.
Extract structured information from a PCO (Proposed Change Order) or change order document.
Respond ONLY with valid JSON — no markdown, no explanation.

Return JSON exactly matching this schema (no extra keys):
{
  "scope_description": "<text describing the scope of work in the change order>",
  "justification": "<contractor's stated reason / basis for the change>",
  "total_amount": "<total dollar amount as string, e.g. '$12,450.00', or UNKNOWN>",
  "line_items": [
    {
      "description": "<description of this line item>",
      "qty": "<quantity as string, or null>",
      "unit": "<unit of measure, e.g. LF, SF, HR, LS, or null>",
      "unit_price": "<unit price as string, e.g. '$85.00', or null>",
      "total": "<line item total as string, e.g. '$1,700.00', or null>"
    }
  ]
}"""


class CostExtractor:
    def __init__(self, ai_engine: AIEngine):
        self._engine = ai_engine

    def extract(self, document_text: str, task_id: str) -> dict:
        """
        Extract structured cost data from PCO/change order document text.

        Args:
            document_text: Raw text of the PCO or change order document.
            task_id: Task ID for audit logging.

        Returns:
            Dict with keys: scope_description, justification, total_amount, line_items.
        """
        user_prompt = (
            f"DOCUMENT TEXT:\n{document_text[:4000]}"
        )

        request = AIRequest(
            capability_class=CapabilityClass.EXTRACT,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.0,
            calling_agent="AGENT-COST-001",
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
                "scope_description": data.get("scope_description", ""),
                "justification": data.get("justification", ""),
                "total_amount": data.get("total_amount", "UNKNOWN"),
                "line_items": data.get("line_items") or [],
            }
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            logger.error(
                f"[{task_id}] Failed to parse cost extraction response: {e}\n"
                f"Raw (first 500 chars): {response.content[:500]}"
            )
            raise ValueError(f"Invalid cost extraction JSON from AI: {e}") from e
