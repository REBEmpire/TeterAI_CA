import json
import logging
from datetime import datetime, timezone

from ai_engine.engine import AIEngine
from ai_engine.models import AIRequest, CapabilityClass
from agents.mixins.red_team import RedTeamMixin

logger = logging.getLogger(__name__)

AGENT_ID = "AGENT-PAYAPP-001"

_RED_TEAM_DOMAIN_CONTEXT = (
    "This is a Pay Application review. "
    "Focus critique on: Are any line items claiming an unusually high percentage of completion "
    "compared to what would be expected? Is the stored materials documentation adequate? "
    "Are there mathematical errors in retainage? "
    "What specific line items would you push back on and why?"
)

SYSTEM_PROMPT = """You are the Pay App Review Agent for Teter Engineering's Construction Administration system.
Review the extracted Pay Application data and produce a structured payment recommendation.
Respond ONLY with valid JSON — no markdown, no explanation.

Evaluate:
1. Percent complete claims — are they reasonable for this stage of construction?
2. Retainage math — does the retainage calculation match the stated retainage percentage?
3. Items claiming >100% completion — flag immediately.
4. Stored materials — is documentation adequate or is it an unsupported claim?
5. Overbilling patterns — front-loading, unexpected jumps in completion percentage.

Return JSON exactly matching this schema (no extra keys):
{
  "line_items": [
    {
      "description": "<line item description>",
      "claimed_pct": "<claimed percent complete as string, e.g. '75%'>",
      "recommended_pct": "<recommended percent to pay as string, e.g. '65%'>",
      "flag": "<OK | FLAG | OVERBILLING>",
      "flag_reason": "<reason for flag, or null if OK>"
    }
  ],
  "total_claimed": "<total dollar amount claimed as string>",
  "total_recommended": "<total dollar amount recommended for payment as string>",
  "delta": "<difference between claimed and recommended as string, e.g. '-$5,200.00'>",
  "retainage_correct": <true if retainage math is correct, false otherwise>,
  "flags": ["<summary flag description>"],
  "recommendation": "<specific actionable recommendation for the owner's representative>"
}"""


class PayAppReviewer(RedTeamMixin):
    def __init__(self, ai_engine: AIEngine):
        self._engine = ai_engine

    def review(self, extraction: dict, task_id: str, project_id: str = "UNKNOWN") -> dict:
        """
        Review extracted Pay Application data. Runs Pass 1 (REASON_STANDARD),
        then Pass 2 (RED_TEAM_CRITIQUE).

        Args:
            extraction: Dict returned by PayAppExtractor.extract().
            task_id: Task ID for audit logging.
            project_id: Project identifier.

        Returns:
            Dict with keys: initial_review, red_team_critique, final_output.
        """
        # --- Pass 1: Initial review (REASON_STANDARD) ---
        user_prompt = (
            f"PROJECT: {project_id}\n\n"
            f"PAY APPLICATION EXTRACTION:\n{json.dumps(extraction, indent=2)}\n\n"
            "Perform a detailed pay application review and return only the JSON output."
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
            logger.error(f"[{task_id}] Failed to parse pay app review JSON: {e}")
            return {
                "line_items": [],
                "total_claimed": "UNKNOWN",
                "total_recommended": "UNKNOWN",
                "delta": "UNKNOWN",
                "retainage_correct": False,
                "flags": [f"Parse error — model did not return valid JSON: {e}"],
                "recommendation": f"[Parse error — model did not return valid JSON: {e}]",
                "parse_error": str(e),
            }

        return {
            "line_items": data.get("line_items") or [],
            "total_claimed": data.get("total_claimed", "UNKNOWN"),
            "total_recommended": data.get("total_recommended", "UNKNOWN"),
            "delta": data.get("delta", "UNKNOWN"),
            "retainage_correct": data.get("retainage_correct", False),
            "flags": data.get("flags") or [],
            "recommendation": data.get("recommendation", ""),
        }


def write_payapp_review(db, task_id: str, project_id: str, review_result: dict) -> None:
    """
    Persist pay application review results to Firestore payapp_reviews/{task_id}.

    Args:
        db: Firestore client.
        task_id: Task ID (used as document ID).
        project_id: Project identifier.
        review_result: Dict returned by PayAppReviewer.review().
    """
    try:
        db.collection("payapp_reviews").document(task_id).set({
            "task_id": task_id,
            "project_id": project_id,
            "initial_review": review_result["initial_review"],
            "red_team_critique": review_result["red_team_critique"],
            "final_output": review_result["final_output"],
            "status": "PENDING_REVIEW",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"[{task_id}] Pay app review stored to Firestore.")
    except Exception as e:
        logger.error(f"[{task_id}] Failed to store pay app review: {e}")
        raise
