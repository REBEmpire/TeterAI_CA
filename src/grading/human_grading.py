"""Human grading interface and divergence comparison.

Provides:
- Interface for human grade input
- Comparison between AI and human grades
- Divergence analysis and logging
- Calibration support
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from .grading_models import (
    GradingSession,
    ModelGrade,
    GradeSource,
    GradingCriterion,
    CriterionScore,
    DivergenceAnalysis,
    DivergenceReport,
    GradingWeights,
)
from .grading_storage import get_grading_storage, GradingStorage

logger = logging.getLogger(__name__)


class HumanGradingInterface:
    """Interface for human graders to input grades and compare with AI."""
    
    def __init__(
        self,
        storage: Optional[GradingStorage] = None,
        weights: Optional[GradingWeights] = None,
    ):
        """Initialize human grading interface.
        
        Args:
            storage: Storage backend for persisting grades
            weights: Custom weights for overall score computation
        """
        self._storage = storage or get_grading_storage()
        self._weights = weights or GradingWeights()
    
    def submit_human_grade(
        self,
        session_id: str,
        model_id: str,
        grader_id: str,
        scores: Dict[str, Dict[str, Any]],
        notes: str = "",
    ) -> Dict[str, Any]:
        """Submit a human grade for a model in a session.
        
        Args:
            session_id: The grading session ID
            model_id: The model being graded
            grader_id: ID of the human grader
            scores: Dict with criterion scores:
                {
                    "accuracy": {"score": 8.0, "reasoning": "..."},
                    "completeness": {"score": 7.5, "reasoning": "..."},
                    ...
                }
            notes: Additional notes from the grader
            
        Returns:
            Dict with grade details and divergence analysis if AI grade exists
        """
        # Get the session
        session = self._storage.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        # Get AI grade to extract model info
        ai_grade = session.ai_grades.get(model_id)
        if not ai_grade:
            # Try to find by model name
            for mid, grade in session.ai_grades.items():
                if grade.model_id == model_id or grade.model_name.lower() in model_id.lower():
                    ai_grade = grade
                    model_id = mid
                    break
        
        if not ai_grade:
            raise ValueError(f"No AI grade found for model {model_id} in session {session_id}")
        
        # Create human grade
        human_grade = ModelGrade(
            model_id=ai_grade.model_id,
            model_name=ai_grade.model_name,
            tier=ai_grade.tier,
            source=GradeSource.HUMAN,
            grader_id=grader_id,
            notes=notes,
        )
        
        # Parse criterion scores
        for criterion_name, score_data in scores.items():
            try:
                criterion = GradingCriterion(criterion_name)
                score = CriterionScore(
                    criterion=criterion,
                    score=float(score_data.get("score", 0)),
                    reasoning=score_data.get("reasoning", ""),
                    evidence=score_data.get("evidence", []),
                )
                setattr(human_grade, criterion_name, score)
            except (ValueError, KeyError) as e:
                logger.warning(f"Invalid criterion {criterion_name}: {e}")
        
        # Compute overall score
        human_grade.compute_overall(self._weights)
        
        # Save human grade
        self._storage.save_grade(session_id, human_grade)
        
        # Compute and save divergence analysis
        divergence = DivergenceAnalysis.from_grades(
            session_id=session_id,
            ai_grade=ai_grade,
            human_grade=human_grade,
        )
        self._storage.save_divergence(divergence)
        
        # Update session status
        session.add_human_grade(human_grade)
        self._storage.update_session_status(session_id, session.status)
        
        logger.info(
            f"Human grade submitted for {ai_grade.model_name} by {grader_id}. "
            f"AI: {ai_grade.overall_score}, Human: {human_grade.overall_score}, "
            f"Divergence: {divergence.overall_difference} ({divergence.overall_level.value})"
        )
        
        return {
            "human_grade": human_grade.to_dict(),
            "divergence": divergence.to_dict(),
            "ai_grade_summary": {
                "overall_score": ai_grade.overall_score,
                "accuracy": ai_grade.accuracy.score if ai_grade.accuracy else None,
                "completeness": ai_grade.completeness.score if ai_grade.completeness else None,
                "relevance": ai_grade.relevance.score if ai_grade.relevance else None,
                "citation_quality": ai_grade.citation_quality.score if ai_grade.citation_quality else None,
            },
        }
    
    def get_ai_grade_for_review(
        self,
        session_id: str,
        model_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get AI grade details for human review.
        
        Returns formatted grade data suitable for displaying to human grader.
        """
        session = self._storage.get_session(session_id)
        if not session:
            return None
        
        ai_grade = session.ai_grades.get(model_id)
        if not ai_grade:
            return None
        
        return {
            "session_id": session_id,
            "model_id": ai_grade.model_id,
            "model_name": ai_grade.model_name,
            "tier": ai_grade.tier,
            "overall_score": ai_grade.overall_score,
            "criteria": {
                "accuracy": {
                    "score": ai_grade.accuracy.score if ai_grade.accuracy else None,
                    "reasoning": ai_grade.accuracy.reasoning if ai_grade.accuracy else "",
                    "evidence": ai_grade.accuracy.evidence if ai_grade.accuracy else [],
                },
                "completeness": {
                    "score": ai_grade.completeness.score if ai_grade.completeness else None,
                    "reasoning": ai_grade.completeness.reasoning if ai_grade.completeness else "",
                    "evidence": ai_grade.completeness.evidence if ai_grade.completeness else [],
                },
                "relevance": {
                    "score": ai_grade.relevance.score if ai_grade.relevance else None,
                    "reasoning": ai_grade.relevance.reasoning if ai_grade.relevance else "",
                    "evidence": ai_grade.relevance.evidence if ai_grade.relevance else [],
                },
                "citation_quality": {
                    "score": ai_grade.citation_quality.score if ai_grade.citation_quality else None,
                    "reasoning": ai_grade.citation_quality.reasoning if ai_grade.citation_quality else "",
                    "evidence": ai_grade.citation_quality.evidence if ai_grade.citation_quality else [],
                },
            },
            "ai_notes": ai_grade.notes,
            "graded_at": ai_grade.graded_at.isoformat(),
        }
    
    def get_session_for_grading(
        self,
        session_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get full session details for human grading interface."""
        session = self._storage.get_session(session_id)
        if not session:
            return None
        
        models_to_grade = []
        for model_id, ai_grade in session.ai_grades.items():
            human_grade = session.human_grades.get(model_id)
            divergence = session.divergence_analyses.get(model_id)
            
            models_to_grade.append({
                "model_id": model_id,
                "model_name": ai_grade.model_name,
                "tier": ai_grade.tier,
                "ai_score": ai_grade.overall_score,
                "human_score": human_grade.overall_score if human_grade else None,
                "is_graded": human_grade is not None,
                "divergence_level": divergence.overall_level.value if divergence else None,
            })
        
        return {
            "session_id": session.session_id,
            "analysis_id": session.analysis_id,
            "document_name": session.document_name,
            "status": session.status,
            "created_at": session.created_at.isoformat(),
            "models": models_to_grade,
        }
    
    def add_divergence_notes(
        self,
        session_id: str,
        model_id: str,
        calibration_notes: str,
        action_items: Optional[List[str]] = None,
    ) -> bool:
        """Add calibration notes to a divergence analysis.
        
        Used by reviewers to document why divergence occurred and
        suggest improvements for AI grading.
        """
        session = self._storage.get_session(session_id)
        if not session:
            return False
        
        divergence = session.divergence_analyses.get(model_id)
        if not divergence:
            return False
        
        divergence.calibration_notes = calibration_notes
        if action_items:
            divergence.action_items = action_items
        
        self._storage.save_divergence(divergence)
        logger.info(f"Added calibration notes for {model_id} in session {session_id}")
        return True
    
    def get_divergence_report(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        model_filter: Optional[str] = None,
    ) -> DivergenceReport:
        """Generate a divergence analysis report.
        
        Args:
            start_date: Start of date range filter
            end_date: End of date range filter
            model_filter: Filter to specific model ID
            
        Returns:
            DivergenceReport with aggregated statistics and recommendations
        """
        return self._storage.generate_divergence_report(
            start_date=start_date,
            end_date=end_date,
            model_filter=model_filter,
        )
    
    def get_pending_sessions(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get sessions awaiting human grading."""
        return self._storage.list_sessions(status="ai_graded", limit=limit)
    
    def get_completed_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get fully graded sessions."""
        return self._storage.list_sessions(status="complete", limit=limit)


# Module-level singleton
_human_grading: Optional[HumanGradingInterface] = None


def get_human_grading_interface() -> HumanGradingInterface:
    """Get or create the human grading interface singleton."""
    global _human_grading
    if _human_grading is None:
        _human_grading = HumanGradingInterface()
    return _human_grading
