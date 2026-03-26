import json
import logging
from datetime import datetime, timezone

from ai_engine.engine import AIEngine
from ai_engine.models import AIRequest, CapabilityClass
from agents.mixins.red_team import RedTeamMixin

logger = logging.getLogger(__name__)

AGENT_ID = "AGENT-COST-001"

_RED_TEAM_DOMAIN_CONTEXT = (
    "This is a PCO (Proposed Change Order) review for a construction project. "
    "Focus your critique on: Are any line items obviously overpriced or missing documentation? "
    "Is the scope description actually outside the original contract? "
    "Are there any items that should be challenged? "
    "Is the recommendation actionable and specific enough for the owner's representative?"
)

SYSTEM_PROMPT = """You are the Cost Analyzer Agent for Teter Engineering's Construction Administration system.
Review the extracted PCO data and produce a structured cost analysis.
Respond ONLY with valid JSON — no markdown, no explanation.

Evaluate:
1. Scope validity — is this work truly outside the original contract scope?
2. Unit price reasonableness — are labor rates and material costs market-appropriate?
3. Spec compliance — do the proposed materials and methods comply with project specifications?
4. Flags — suspicious pricing (unusually high labor rates), missing backup documentation,
   scope items that appear contractual obligations.

Return JSON exactly matching this schema (no extra keys):
{
  "scope_verdict": "<VALID | QUESTIONABLE | IN_CONTRACT>",
  "line_items": [
    {
      "description": "<line item description>",
      "claimed_amount": "<dollar amount as string>",
      "flag": "<OK | FLAG>",
      "flag_reason": "<reason for flag, or null if OK>"
    }
  ],
  "negotiation_points": ["<specific negotiation point>"],
  "overall_confidence": <float 0.0-1.0>,
  "recommendation": "<specific actionable recommendation for the owner's representative>"
}"""


class CostReviewer(RedTeamMixin):
    def __init__(self, ai_engine: AIEngine):
        self._engine = ai_engine

    def review(self, extraction: dict, task_id: str, project_id: str = "UNKNOWN") -> dict:
        """
        Review extracted PCO data. Runs Pass 1 (REASON_STANDARD), then Pass 2 (RED_TEAM_CRITIQUE).

        Args:
            extraction: Dict returned by CostExtractor.extract().
            task_id: Task ID for audit logging.
            project_id: Project identifier.

        Returns:
            Dict with keys: initial_review, red_team_critique, final_output.
        """
        # --- Pass 1: Initial review (REASON_STANDARD) ---
        user_prompt = (
            f"PROJECT: {project_id}\n\n"
            f"PCO EXTRACTION:\n{json.dumps(extraction, indent=2)}\n\n"
            "Perform a detailed cost review and return only the JSON output."
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
            logger.error(f"[{task_id}] Failed to parse cost review JSON: {e}")
            return {
                "scope_verdict": "QUESTIONABLE",
                "line_items": [],
                "negotiation_points": [],
                "overall_confidence": 0.0,
                "recommendation": f"[Parse error — model did not return valid JSON: {e}]",
                "parse_error": str(e),
            }

        return {
            "scope_verdict": data.get("scope_verdict", "QUESTIONABLE"),
            "line_items": data.get("line_items") or [],
            "negotiation_points": data.get("negotiation_points") or [],
            "overall_confidence": data.get("overall_confidence", 0.5),
            "recommendation": data.get("recommendation", ""),
        }


def write_cost_analysis(db, task_id: str, project_id: str, review_result: dict) -> None:
    """
    Persist cost analysis results to Firestore cost_analyses/{task_id}.

    Args:
        db: Firestore client.
        task_id: Task ID (used as document ID).
        project_id: Project identifier.
        review_result: Dict returned by CostReviewer.review().
    """
    try:
        db.collection("cost_analyses").document(task_id).set({
            "task_id": task_id,
            "project_id": project_id,
            "initial_review": review_result["initial_review"],
            "red_team_critique": review_result["red_team_critique"],
            "final_output": review_result["final_output"],
            "status": "PENDING_REVIEW",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"[{task_id}] Cost analysis stored to Firestore.")
    except Exception as e:
        logger.error(f"[{task_id}] Failed to store cost analysis: {e}")
        raise
