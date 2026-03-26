import copy
import json
import logging
from enum import Enum
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class CritiqueSeverity(str, Enum):
    AGREE = "AGREE"
    MINOR_REVISION = "MINOR_REVISION"
    MAJOR_REVISION = "MAJOR_REVISION"
    REJECT = "REJECT"


class CritiqueItem(BaseModel):
    field: str                          # which field/aspect was critiqued
    original: str                       # the original value from Pass 1
    critique: str                       # the senior's critique reasoning
    severity: CritiqueSeverity
    revised_value: str | None = None    # the revised value (required for MAJOR_REVISION/REJECT)


class RedTeamResult(BaseModel):
    critique_items: list[CritiqueItem]
    summary: str                        # 2-3 sentence summary of overall quality assessment
    overall_severity: CritiqueSeverity  # worst severity found


class RedTeamMixin:
    """
    Mixin providing two-pass Red Team critique for any agent.

    The "intern" (Pass 1) does the initial expert-level review.
    The "senior architect" (Red Team, Pass 2) critiques it adversarially.
    Results are stored so reviewers can see the full audit trail.

    Usage:
        class MyAgent(RedTeamMixin): ...

        # In your agent's run() method:
        initial_output = {...}  # your Pass 1 result dict
        critique = self.run_red_team(ai_engine, initial_output, domain_context, task_id)
        final_output = self.apply_critique(initial_output, critique)

        # Store all three for the audit trail:
        record["initial_review"] = initial_output
        record["red_team_critique"] = critique.model_dump()
        record["final_output"] = final_output
    """

    RED_TEAM_SYSTEM_PROMPT = (
        "You are a senior licensed architect with 20+ years of experience in construction "
        "administration. You are reviewing the work of a junior staff member. Your job is to "
        "be thorough, rigorous, and constructively critical.\n\n"
        "For each aspect of the review, assess whether the junior's work is correct, complete, "
        "and professional. Be specific about what is wrong and why. Do not be vague.\n\n"
        "You must respond with valid JSON matching the RedTeamResult schema."
    )

    def run_red_team(
        self,
        ai_engine,
        initial_output: dict,
        domain_context: str,
        task_id: str,
        agent_id: str = "red_team",
    ) -> RedTeamResult:
        """
        Run Red Team critique on the initial agent output.

        Args:
            ai_engine: AIEngine instance
            initial_output: The Pass 1 result dict to critique
            domain_context: Domain-specific instructions (e.g. "This is a PCO review.
                            Focus on: pricing reasonableness, scope validity, spec compliance.")
            task_id: Task ID for audit logging
            agent_id: Agent identifier for audit logging

        Returns:
            RedTeamResult with structured critique items
        """
        from ai_engine.models import AIRequest, CapabilityClass

        prompt = (
            f"{domain_context}\n\n"
            "INITIAL REVIEW OUTPUT TO CRITIQUE:\n"
            f"{json.dumps(initial_output, indent=2)}\n\n"
            "Review this output as a senior architect reviewing a junior's work. "
            "For each significant aspect:\n"
            "1. Identify the field/aspect you are critiquing\n"
            "2. State what the original said\n"
            "3. Provide your critique\n"
            "4. Rate severity: AGREE (correct), MINOR_REVISION (small improvement needed), "
            "MAJOR_REVISION (significant change needed), REJECT (wrong/incomplete, must redo)\n"
            "5. If MAJOR_REVISION or REJECT, provide the revised value\n\n"
            "Return JSON with this exact schema:\n"
            "{\n"
            '  "critique_items": [\n'
            "    {\n"
            '      "field": "string - which aspect",\n'
            '      "original": "string - what original said",\n'
            '      "critique": "string - your critique reasoning",\n'
            '      "severity": "AGREE|MINOR_REVISION|MAJOR_REVISION|REJECT",\n'
            '      "revised_value": "string or null - revised content if MAJOR_REVISION or REJECT"\n'
            "    }\n"
            "  ],\n"
            '  "summary": "string - 2-3 sentence overall assessment",\n'
            '  "overall_severity": "AGREE|MINOR_REVISION|MAJOR_REVISION|REJECT"\n'
            "}"
        )

        request = AIRequest(
            capability_class=CapabilityClass.RED_TEAM_CRITIQUE,
            system_prompt=self.RED_TEAM_SYSTEM_PROMPT,
            user_prompt=prompt,
            temperature=0.2,
            calling_agent=agent_id,
            task_id=task_id,
        )

        response = ai_engine.generate_response(request)
        raw = response.content

        try:
            text = raw.strip()
            if text.startswith("```"):
                lines = text.splitlines()
                # Remove opening fence line
                lines = lines[1:] if lines[0].startswith("```") else lines
                # Remove closing fence line
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines).strip()
            data = json.loads(text)
            return RedTeamResult(**data)
        except Exception as e:
            logger.warning("[%s] Red Team critique parse error: %s", task_id, e)
            return RedTeamResult(
                critique_items=[],
                summary=f"Red Team critique parse error: {e}",
                overall_severity=CritiqueSeverity.AGREE,
            )

    def apply_critique(self, initial_output: dict, critique: RedTeamResult) -> dict:
        """
        Applies Red Team critique to the initial output dict.

        MAJOR_REVISION and REJECT items have their revised_value applied to
        the matching top-level key. AGREE and MINOR_REVISION items carry through.

        For nested structures (e.g. list-of-line-items), agents should override
        this method with domain-specific reconciliation logic.
        """
        result = copy.deepcopy(initial_output)

        for item in critique.critique_items:
            if item.severity in (CritiqueSeverity.MAJOR_REVISION, CritiqueSeverity.REJECT):
                if item.revised_value is not None and item.field in result:
                    result[item.field] = item.revised_value

        return result
