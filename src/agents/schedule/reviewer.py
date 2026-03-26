import json
import logging
from datetime import datetime, timezone

from ai_engine.engine import AIEngine
from ai_engine.models import AIRequest, CapabilityClass
from agents.mixins.red_team import RedTeamMixin

logger = logging.getLogger(__name__)

AGENT_ID = "AGENT-SCHEDULE-001"

_RED_TEAM_DOMAIN_CONTEXT = (
    "This is a construction schedule review. "
    "Focus your critique on: Are any critical path activities being understated in terms of delay? "
    "Are the milestone forecasts optimistic given current progress? "
    "What sequencing risks or resource conflicts are apparent? "
    "Is the overall health rating accurate given the data?"
)

SYSTEM_PROMPT = """You are the Schedule Review Agent for Teter Engineering's Construction Administration system.
Review the extracted construction schedule data and produce a structured schedule analysis.
Respond ONLY with valid JSON — no markdown, no explanation.

Evaluate:
1. Planned vs. actual progress — compare planned_start/finish to actual_start/finish for each activity.
2. Critical path risk — flag activities on the critical path that are behind by more than 5 days.
3. Schedule Performance Index (SPI) — estimate SPI where possible (SPI = earned value / planned value).
   If insufficient data, omit or estimate conservatively.
4. Milestone status — forecast revised completion dates based on current trajectory.
5. Overall health — GREEN (on track), YELLOW (minor delays, recoverable), RED (significant delay risk).

Return JSON exactly matching this schema (no extra keys):
{
  "activities": [
    {
      "id": "<activity ID>",
      "name": "<activity name>",
      "status": "<ON_TRACK | AT_RISK | BEHIND>",
      "variance_days": <integer — positive means behind schedule, negative means ahead>,
      "is_critical": <true if on critical path, false otherwise>
    }
  ],
  "critical_path_risks": ["<description of critical path risk>"],
  "milestone_status": [
    {
      "name": "<milestone name>",
      "planned_date": "<YYYY-MM-DD or null>",
      "forecast_date": "<YYYY-MM-DD or null — revised forecast based on current progress>",
      "status": "<ON_TRACK | AT_RISK | BEHIND | COMPLETE>"
    }
  ],
  "overall_health": "<GREEN | YELLOW | RED>",
  "spi_estimate": <float — Schedule Performance Index estimate, or null if insufficient data>,
  "recommendation": "<specific actionable recommendation for the owner's representative>"
}"""


class ScheduleReviewer(RedTeamMixin):
    def __init__(self, ai_engine: AIEngine):
        self._engine = ai_engine

    def review(self, extraction: dict, task_id: str, project_id: str = "UNKNOWN") -> dict:
        """
        Review extracted schedule data. Runs Pass 1 (REASON_STANDARD),
        then Pass 2 (RED_TEAM_CRITIQUE).

        Args:
            extraction: Dict returned by ScheduleExtractor.extract().
            task_id: Task ID for audit logging.
            project_id: Project identifier.

        Returns:
            Dict with keys: initial_review, red_team_critique, final_output.
        """
        # --- Pass 1: Initial review (REASON_STANDARD) ---
        user_prompt = (
            f"PROJECT: {project_id}\n\n"
            f"SCHEDULE EXTRACTION:\n{json.dumps(extraction, indent=2)}\n\n"
            "Perform a detailed schedule review and return only the JSON output."
        )

        request = AIRequest(
            capability_class=CapabilityClass.REASON_STANDARD,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
            calling_agent=AGENT_ID,
            task_id=task_id,
        )

        response = self._engine.generate_response(request)
        initial_review = self._parse_review(response.content, task_id)

        # --- Pass 2: Red Team critique (RED_TEAM_CRITIQUE) ---
        critique = self.run_red_team(
            ai_engine=self._engine,
            initial_output=initial_review,
            domain_context=_RED_TEAM_DOMAIN_CONTEXT,
            task_id=task_id,
            agent_id=AGENT_ID,
        )

        # --- Apply critique to produce final output ---
        final_output = self.apply_critique(initial_review, critique)

        return {
            "initial_review": initial_review,
            "red_team_critique": critique.model_dump(),
            "final_output": final_output,
        }

    def _parse_review(self, raw_content: str, task_id: str) -> dict:
        """Parse the model's raw JSON response into a review dict."""
        text = raw_content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            lines = lines[1:] if lines[0].startswith("```") else lines
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"[{task_id}] Failed to parse schedule review JSON: {e}")
            return {
                "activities": [],
                "critical_path_risks": [f"Parse error — model did not return valid JSON: {e}"],
                "milestone_status": [],
                "overall_health": "RED",
                "spi_estimate": None,
                "recommendation": f"[Parse error — model did not return valid JSON: {e}]",
                "parse_error": str(e),
            }

        return {
            "activities": data.get("activities") or [],
            "critical_path_risks": data.get("critical_path_risks") or [],
            "milestone_status": data.get("milestone_status") or [],
            "overall_health": data.get("overall_health", "RED"),
            "spi_estimate": data.get("spi_estimate"),
            "recommendation": data.get("recommendation", ""),
        }


def write_schedule_review(db, task_id: str, project_id: str, review_result: dict) -> None:
    """
    Persist schedule review results to Firestore schedule_reviews/{task_id}.

    Args:
        db: Firestore client.
        task_id: Task ID (used as document ID).
        project_id: Project identifier.
        review_result: Dict returned by ScheduleReviewer.review().
    """
    try:
        db.collection("schedule_reviews").document(task_id).set({
            "task_id": task_id,
            "project_id": project_id,
            "initial_review": review_result["initial_review"],
            "red_team_critique": review_result["red_team_critique"],
            "final_output": review_result["final_output"],
            "status": "PENDING_REVIEW",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"[{task_id}] Schedule review stored to Firestore.")
    except Exception as e:
        logger.error(f"[{task_id}] Failed to store schedule review: {e}")
        raise
