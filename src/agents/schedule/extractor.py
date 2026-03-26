import json
import logging

from ai_engine.engine import AIEngine
from ai_engine.models import AIRequest, CapabilityClass

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Schedule Review Agent for Teter Engineering's Construction Administration system.
Extract structured information from a construction schedule document (PDF export of P6, Primavera, or MS Project).
Respond ONLY with valid JSON — no markdown, no explanation.

Return JSON exactly matching this schema (no extra keys):
{
  "project_name": "<name of the project, or UNKNOWN>",
  "data_date": "<schedule data date as YYYY-MM-DD, or null>",
  "activities": [
    {
      "id": "<activity ID, e.g. A1010>",
      "name": "<activity name>",
      "planned_start": "<YYYY-MM-DD or null>",
      "planned_finish": "<YYYY-MM-DD or null>",
      "actual_start": "<YYYY-MM-DD or null>",
      "actual_finish": "<YYYY-MM-DD or null>",
      "duration_days": <integer number of planned duration days, or null>,
      "is_critical": <true if on critical path, false otherwise>
    }
  ],
  "milestones": [
    {
      "name": "<milestone name>",
      "planned_date": "<YYYY-MM-DD or null>",
      "actual_date": "<YYYY-MM-DD or null>",
      "status": "<NOT_STARTED | IN_PROGRESS | COMPLETE | UNKNOWN>"
    }
  ]
}"""


class ScheduleExtractor:
    def __init__(self, ai_engine: AIEngine):
        self._engine = ai_engine

    def extract(self, document_text: str, task_id: str) -> dict:
        """
        Extract structured schedule data from a schedule document.

        Args:
            document_text: Raw text of the schedule document.
            task_id: Task ID for audit logging.

        Returns:
            Dict with keys: project_name, data_date, activities, milestones.
        """
        user_prompt = (
            f"DOCUMENT TEXT:\n{document_text[:4000]}"
        )

        request = AIRequest(
            capability_class=CapabilityClass.EXTRACT,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.0,
            calling_agent="AGENT-SCHEDULE-001",
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
                "project_name": data.get("project_name", "UNKNOWN"),
                "data_date": data.get("data_date"),
                "activities": data.get("activities") or [],
                "milestones": data.get("milestones") or [],
            }
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            logger.error(
                f"[{task_id}] Failed to parse schedule extraction response: {e}\n"
                f"Raw (first 500 chars): {response.content[:500]}"
            )
            raise ValueError(f"Invalid schedule extraction JSON from AI: {e}") from e
