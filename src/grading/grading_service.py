"""Main auto-grading service using Claude as the AI judge.

Provides:
- Auto-grading of multi-model analysis results
- Structured evaluation against defined criteria
- Integration with document content for accuracy verification
"""
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import uuid

from .grading_models import (
    GradingSession,
    ModelGrade,
    GradeSource,
    GradingCriterion,
    CriterionScore,
    GradingWeights,
)
from .grading_storage import get_grading_storage, GradingStorage

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Grading Prompts
# -----------------------------------------------------------------------------

_GRADING_SYSTEM_PROMPT = """You are an expert document analysis evaluator. Your task is to grade AI model responses based on their analysis of construction/engineering documents.

You will evaluate responses on four criteria, each scored from 0-10:

1. ACCURACY (30% weight): Factual correctness against the source document
   - Are statements verifiable in the document?
   - Are there any factual errors or misinterpretations?
   - Are numbers, dates, and specifications correct?

2. COMPLETENESS (25% weight): Coverage of key document elements
   - Are all major sections/topics addressed?
   - Are important details captured?
   - Is anything significant missing?

3. RELEVANCE (25% weight): Alignment with analysis purpose
   - Does the analysis address the intended purpose?
   - Is the information actionable and useful?
   - Is irrelevant information minimized?

4. CITATION QUALITY (20% weight): References to document sections
   - Are sources properly cited?
   - Can claims be traced to specific document sections?
   - Are page numbers/section references accurate?

Scoring Guidelines:
- 9-10: Excellent - Exceptional quality, no issues
- 7-8: Good - Strong performance with minor issues
- 5-6: Adequate - Meets basic requirements but has notable gaps
- 3-4: Poor - Significant issues or omissions
- 1-2: Very Poor - Major problems, largely inadequate
- 0: Fail - Completely inadequate or wrong

You must respond with ONLY a valid JSON object in the following format:
{
  "accuracy": {
    "score": <0-10>,
    "reasoning": "<explanation>",
    "evidence": ["<specific examples>"]
  },
  "completeness": {
    "score": <0-10>,
    "reasoning": "<explanation>",
    "evidence": ["<specific examples>"]
  },
  "relevance": {
    "score": <0-10>,
    "reasoning": "<explanation>",
    "evidence": ["<specific examples>"]
  },
  "citation_quality": {
    "score": <0-10>,
    "reasoning": "<explanation>",
    "evidence": ["<specific examples>"]
  },
  "overall_notes": "<brief overall assessment>"
}"""

_GRADING_USER_PROMPT_TEMPLATE = """Please evaluate the following AI model response against the source document content.

=== SOURCE DOCUMENT (truncated for evaluation) ===
{document_content}

=== ANALYSIS PURPOSE/QUERY ===
{analysis_purpose}

=== MODEL RESPONSE TO EVALUATE ===
Model: {model_name}
Tier: {tier}

{model_response}

=== END OF RESPONSE ===

Please provide your detailed evaluation as a JSON object with scores and reasoning for each criterion."""


class AutoGrader:
    """Auto-grades model responses using Claude as the AI judge."""
    
    def __init__(
        self,
        storage: Optional[GradingStorage] = None,
        weights: Optional[GradingWeights] = None,
    ):
        """Initialize the auto-grader.
        
        Args:
            storage: Storage backend for persisting grades
            weights: Custom weights for overall score computation
        """
        self._storage = storage or get_grading_storage()
        self._weights = weights or GradingWeights()
        self._ai_engine = None
    
    def _get_engine(self):
        """Lazy load AI engine."""
        if self._ai_engine is None:
            from ai_engine import ai_engine
            self._ai_engine = ai_engine
        return self._ai_engine
    
    def grade_analysis(
        self,
        analysis_result: Any,  # MultiModelAnalysisResult
        document_content: str,
        analysis_purpose: str = "General document analysis",
    ) -> GradingSession:
        """Auto-grade all model responses in an analysis result.
        
        Args:
            analysis_result: The MultiModelAnalysisResult to grade
            document_content: Original document content for verification
            analysis_purpose: Purpose of the analysis for relevance scoring
            
        Returns:
            GradingSession with AI grades for all models
        """
        # Create grading session
        session = GradingSession(
            analysis_id=analysis_result.analysis_id,
            document_id=analysis_result.document_id,
            document_name=analysis_result.document_name,
            weights=self._weights,
        )
        
        # Save session first
        self._storage.create_session(session)
        
        # Truncate document for prompt (keep first ~8000 chars)
        doc_preview = document_content[:8000]
        if len(document_content) > 8000:
            doc_preview += "\n\n[... document truncated for evaluation ...]"
        
        # Grade each model's response
        model_configs = [
            (1, "tier_1_response", "Claude Opus 4.6"),
            (2, "tier_2_response", "Gemini 3.1 Pro"),
            (3, "tier_3_response", "Grok 4.2"),
        ]
        
        for tier, attr_name, model_name in model_configs:
            response = getattr(analysis_result, attr_name, None)
            if response is None or not response.is_success:
                logger.info(f"Skipping {model_name} - no successful response")
                continue
            
            try:
                grade = self._grade_single_response(
                    model_response=response,
                    model_name=model_name,
                    tier=tier,
                    document_content=doc_preview,
                    analysis_purpose=analysis_purpose,
                )
                
                # Save grade and add to session
                self._storage.save_grade(session.session_id, grade)
                session.add_ai_grade(grade)
                logger.info(f"Graded {model_name}: {grade.overall_score}/10")
                
            except Exception as e:
                logger.error(f"Failed to grade {model_name}: {e}")
        
        # Update session status
        self._storage.update_session_status(session.session_id, session.status)
        
        return session
    
    def _grade_single_response(
        self,
        model_response: Any,  # ModelAnalysisResponse
        model_name: str,
        tier: int,
        document_content: str,
        analysis_purpose: str,
    ) -> ModelGrade:
        """Grade a single model's response using Claude as judge."""
        from ai_engine.models import AIRequest, CapabilityClass
        
        # Build the response text to evaluate
        response_text = model_response.content or ""
        if model_response.summary:
            response_text = f"Summary: {model_response.summary}\n\n" + response_text
        if model_response.key_findings:
            response_text += f"\n\nKey Findings:\n" + "\n".join(
                f"- {f}" for f in model_response.key_findings
            )
        if model_response.recommendations:
            response_text += f"\n\nRecommendations:\n" + "\n".join(
                f"- {r}" for r in model_response.recommendations
            )
        
        # Create grading prompt
        user_prompt = _GRADING_USER_PROMPT_TEMPLATE.format(
            document_content=document_content,
            analysis_purpose=analysis_purpose,
            model_name=model_name,
            tier=tier,
            model_response=response_text,
        )
        
        # Call Claude to grade (use REASON_DEEP for careful evaluation)
        engine = self._get_engine()
        request = AIRequest(
            capability_class=CapabilityClass.REASON_DEEP,
            system_prompt=_GRADING_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
        
        ai_response = engine.generate_response(request)
        
        # Parse the grading response
        return self._parse_grading_response(
            response_content=ai_response.content,
            model_id=model_response.metadata.model_id if model_response.metadata else str(uuid.uuid4()),
            model_name=model_name,
            tier=tier,
        )
    
    def _parse_grading_response(
        self,
        response_content: str,
        model_id: str,
        model_name: str,
        tier: int,
    ) -> ModelGrade:
        """Parse Claude's grading response into a ModelGrade."""
        # Try to extract JSON from response
        try:
            # Find JSON object in response
            json_match = re.search(r'\{[\s\S]*\}', response_content)
            if json_match:
                data = json.loads(json_match.group())
            else:
                raise ValueError("No JSON found in response")
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse grading response: {e}")
            # Return a default grade indicating parsing failure
            return self._create_fallback_grade(model_id, model_name, tier)
        
        # Build the grade object
        grade = ModelGrade(
            model_id=model_id,
            model_name=model_name,
            tier=tier,
            source=GradeSource.AI_JUDGE,
            grader_id="claude-judge",
        )
        
        # Parse each criterion
        for criterion_name in ["accuracy", "completeness", "relevance", "citation_quality"]:
            if criterion_name in data:
                crit_data = data[criterion_name]
                criterion = GradingCriterion(criterion_name)
                
                score = CriterionScore(
                    criterion=criterion,
                    score=float(crit_data.get("score", 5.0)),
                    reasoning=crit_data.get("reasoning", ""),
                    evidence=crit_data.get("evidence", []),
                )
                
                setattr(grade, criterion_name, score)
        
        # Add overall notes
        if "overall_notes" in data:
            grade.notes = data["overall_notes"]
        
        # Compute weighted overall score
        grade.compute_overall(self._weights)
        
        return grade
    
    def _create_fallback_grade(
        self,
        model_id: str,
        model_name: str,
        tier: int,
    ) -> ModelGrade:
        """Create a fallback grade when parsing fails."""
        grade = ModelGrade(
            model_id=model_id,
            model_name=model_name,
            tier=tier,
            source=GradeSource.AI_JUDGE,
            grader_id="claude-judge",
            notes="Grading response parsing failed - default scores assigned",
        )
        
        # Assign neutral scores
        for criterion in GradingCriterion:
            setattr(grade, criterion.value, CriterionScore(
                criterion=criterion,
                score=5.0,
                reasoning="Unable to parse grading response",
            ))
        
        grade.compute_overall(self._weights)
        return grade
    
    def get_session(self, session_id: str) -> Optional[GradingSession]:
        """Retrieve a grading session."""
        return self._storage.get_session(session_id)
    
    def list_sessions(self, **kwargs) -> List[Dict[str, Any]]:
        """List grading sessions."""
        return self._storage.list_sessions(**kwargs)


# Module-level singleton
_auto_grader: Optional[AutoGrader] = None


def get_auto_grader() -> AutoGrader:
    """Get or create the auto-grader singleton."""
    global _auto_grader
    if _auto_grader is None:
        _auto_grader = AutoGrader()
    return _auto_grader


def grade_analysis(
    analysis_result: Any,
    document_content: str,
    analysis_purpose: str = "General document analysis",
) -> GradingSession:
    """Convenience function to auto-grade an analysis result."""
    return get_auto_grader().grade_analysis(
        analysis_result=analysis_result,
        document_content=document_content,
        analysis_purpose=analysis_purpose,
    )
