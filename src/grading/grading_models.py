"""Data models for the auto-grading system with human comparison.

Provides Pydantic models for:
- Grading criteria and scores
- AI and human grades
- Divergence analysis
- Grade logging and reporting
"""
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field, field_validator


class GradingCriterion(str, Enum):
    """Evaluation criteria for model responses."""
    ACCURACY = "accuracy"              # Factual correctness against document content
    COMPLETENESS = "completeness"      # Coverage of key document elements
    RELEVANCE = "relevance"            # Alignment with analysis query/purpose
    CITATION_QUALITY = "citation_quality"  # Proper references to document sections


class GradeSource(str, Enum):
    """Source of the grade."""
    AI_JUDGE = "ai_judge"              # Auto-graded by Claude
    HUMAN = "human"                    # Graded by human reviewer


class DivergenceLevel(str, Enum):
    """Categorization of divergence between AI and human grades."""
    NONE = "none"                      # No meaningful difference (0-0.5 points)
    LOW = "low"                        # Minor difference (0.5-1.0 points)
    MEDIUM = "medium"                  # Moderate difference (1.0-2.0 points)
    HIGH = "high"                      # Significant difference (2.0+ points)


class CriterionScore(BaseModel):
    """Score for a single grading criterion."""
    criterion: GradingCriterion = Field(description="The criterion being scored")
    score: float = Field(
        ge=0.0, le=10.0,
        description="Score on a 0-10 scale"
    )
    reasoning: str = Field(
        default="",
        description="Explanation for the score"
    )
    evidence: List[str] = Field(
        default_factory=list,
        description="Specific examples or quotes supporting the score"
    )
    
    @field_validator('score')
    @classmethod
    def round_score(cls, v: float) -> float:
        """Round score to 1 decimal place."""
        return round(v, 1)


class GradingWeights(BaseModel):
    """Weights for computing overall score from criteria scores."""
    accuracy: float = Field(default=0.30, ge=0.0, le=1.0)
    completeness: float = Field(default=0.25, ge=0.0, le=1.0)
    relevance: float = Field(default=0.25, ge=0.0, le=1.0)
    citation_quality: float = Field(default=0.20, ge=0.0, le=1.0)
    
    def validate_sum(self) -> bool:
        """Check that weights sum to 1.0."""
        total = self.accuracy + self.completeness + self.relevance + self.citation_quality
        return abs(total - 1.0) < 0.001
    
    def to_dict(self) -> Dict[GradingCriterion, float]:
        """Convert to dictionary keyed by criterion."""
        return {
            GradingCriterion.ACCURACY: self.accuracy,
            GradingCriterion.COMPLETENESS: self.completeness,
            GradingCriterion.RELEVANCE: self.relevance,
            GradingCriterion.CITATION_QUALITY: self.citation_quality,
        }


class ModelGrade(BaseModel):
    """Complete grade for a single model's response."""
    grade_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this grade"
    )
    model_id: str = Field(description="Identifier of the model being graded")
    model_name: str = Field(description="Display name of the model (e.g., 'Claude Opus 4.6')")
    tier: int = Field(ge=1, le=3, description="Model tier (1, 2, or 3)")
    source: GradeSource = Field(description="Who assigned this grade")
    
    # Individual criterion scores
    accuracy: Optional[CriterionScore] = None
    completeness: Optional[CriterionScore] = None
    relevance: Optional[CriterionScore] = None
    citation_quality: Optional[CriterionScore] = None
    
    # Overall computed score
    overall_score: float = Field(
        default=0.0, ge=0.0, le=10.0,
        description="Weighted overall score (0-10)"
    )
    
    # Metadata
    grader_id: Optional[str] = Field(
        default=None,
        description="ID of human grader or 'claude-judge' for AI"
    )
    graded_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    notes: str = Field(default="", description="Additional notes from grader")
    
    def compute_overall(self, weights: Optional[GradingWeights] = None) -> float:
        """Compute weighted overall score from criteria scores."""
        if weights is None:
            weights = GradingWeights()
        
        w = weights.to_dict()
        total = 0.0
        
        if self.accuracy:
            total += self.accuracy.score * w[GradingCriterion.ACCURACY]
        if self.completeness:
            total += self.completeness.score * w[GradingCriterion.COMPLETENESS]
        if self.relevance:
            total += self.relevance.score * w[GradingCriterion.RELEVANCE]
        if self.citation_quality:
            total += self.citation_quality.score * w[GradingCriterion.CITATION_QUALITY]
        
        self.overall_score = round(total, 1)
        return self.overall_score
    
    def get_criterion_score(self, criterion: GradingCriterion) -> Optional[CriterionScore]:
        """Get score for a specific criterion."""
        mapping = {
            GradingCriterion.ACCURACY: self.accuracy,
            GradingCriterion.COMPLETENESS: self.completeness,
            GradingCriterion.RELEVANCE: self.relevance,
            GradingCriterion.CITATION_QUALITY: self.citation_quality,
        }
        return mapping.get(criterion)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "grade_id": self.grade_id,
            "model_id": self.model_id,
            "model_name": self.model_name,
            "tier": self.tier,
            "source": self.source.value,
            "accuracy": self.accuracy.model_dump() if self.accuracy else None,
            "completeness": self.completeness.model_dump() if self.completeness else None,
            "relevance": self.relevance.model_dump() if self.relevance else None,
            "citation_quality": self.citation_quality.model_dump() if self.citation_quality else None,
            "overall_score": self.overall_score,
            "grader_id": self.grader_id,
            "graded_at": self.graded_at.isoformat(),
            "notes": self.notes,
        }


class CriterionDivergence(BaseModel):
    """Divergence analysis for a single criterion."""
    criterion: GradingCriterion
    ai_score: float
    human_score: float
    difference: float = Field(description="human_score - ai_score")
    level: DivergenceLevel
    notes: str = Field(default="", description="Analysis of why divergence occurred")


class DivergenceAnalysis(BaseModel):
    """Analysis of divergence between AI and human grades."""
    analysis_id: str = Field(
        default_factory=lambda: str(uuid.uuid4())
    )
    session_id: str = Field(description="Analysis session this belongs to")
    model_id: str = Field(description="Model whose grades are being compared")
    model_name: str
    
    # Grade references
    ai_grade_id: str
    human_grade_id: str
    
    # Criterion-level divergence
    criterion_divergences: List[CriterionDivergence] = Field(default_factory=list)
    
    # Overall divergence
    overall_ai_score: float
    overall_human_score: float
    overall_difference: float
    overall_level: DivergenceLevel
    
    # Analysis metadata
    analyzed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    calibration_notes: str = Field(
        default="",
        description="Notes for calibrating future AI grading"
    )
    action_items: List[str] = Field(
        default_factory=list,
        description="Suggested actions based on divergence"
    )
    
    @classmethod
    def compute_level(cls, difference: float) -> DivergenceLevel:
        """Determine divergence level from score difference."""
        abs_diff = abs(difference)
        if abs_diff <= 0.5:
            return DivergenceLevel.NONE
        elif abs_diff <= 1.0:
            return DivergenceLevel.LOW
        elif abs_diff <= 2.0:
            return DivergenceLevel.MEDIUM
        else:
            return DivergenceLevel.HIGH
    
    @classmethod
    def from_grades(
        cls,
        session_id: str,
        ai_grade: ModelGrade,
        human_grade: ModelGrade
    ) -> "DivergenceAnalysis":
        """Create divergence analysis by comparing AI and human grades."""
        criterion_divergences = []
        
        for criterion in GradingCriterion:
            ai_crit = ai_grade.get_criterion_score(criterion)
            human_crit = human_grade.get_criterion_score(criterion)
            
            if ai_crit and human_crit:
                diff = human_crit.score - ai_crit.score
                criterion_divergences.append(CriterionDivergence(
                    criterion=criterion,
                    ai_score=ai_crit.score,
                    human_score=human_crit.score,
                    difference=round(diff, 1),
                    level=cls.compute_level(diff),
                ))
        
        overall_diff = human_grade.overall_score - ai_grade.overall_score
        
        return cls(
            session_id=session_id,
            model_id=ai_grade.model_id,
            model_name=ai_grade.model_name,
            ai_grade_id=ai_grade.grade_id,
            human_grade_id=human_grade.grade_id,
            criterion_divergences=criterion_divergences,
            overall_ai_score=ai_grade.overall_score,
            overall_human_score=human_grade.overall_score,
            overall_difference=round(overall_diff, 1),
            overall_level=cls.compute_level(overall_diff),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "analysis_id": self.analysis_id,
            "session_id": self.session_id,
            "model_id": self.model_id,
            "model_name": self.model_name,
            "ai_grade_id": self.ai_grade_id,
            "human_grade_id": self.human_grade_id,
            "criterion_divergences": [
                {
                    "criterion": cd.criterion.value,
                    "ai_score": cd.ai_score,
                    "human_score": cd.human_score,
                    "difference": cd.difference,
                    "level": cd.level.value,
                    "notes": cd.notes,
                }
                for cd in self.criterion_divergences
            ],
            "overall_ai_score": self.overall_ai_score,
            "overall_human_score": self.overall_human_score,
            "overall_difference": self.overall_difference,
            "overall_level": self.overall_level.value,
            "analyzed_at": self.analyzed_at.isoformat(),
            "calibration_notes": self.calibration_notes,
            "action_items": self.action_items,
        }


class GradingSession(BaseModel):
    """Complete grading session for a multi-model analysis."""
    session_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this grading session"
    )
    analysis_id: str = Field(
        description="Reference to the MultiModelAnalysisResult being graded"
    )
    document_id: Optional[str] = None
    document_name: Optional[str] = None
    
    # AI grades (one per model)
    ai_grades: Dict[str, ModelGrade] = Field(
        default_factory=dict,
        description="AI grades keyed by model_id"
    )
    
    # Human grades (one per model)
    human_grades: Dict[str, ModelGrade] = Field(
        default_factory=dict,
        description="Human grades keyed by model_id"
    )
    
    # Divergence analyses
    divergence_analyses: Dict[str, DivergenceAnalysis] = Field(
        default_factory=dict,
        description="Divergence analyses keyed by model_id"
    )
    
    # Session metadata
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    completed_at: Optional[datetime] = None
    status: str = Field(
        default="pending",
        description="Session status: pending, ai_graded, human_graded, complete"
    )
    
    # Grading weights used
    weights: GradingWeights = Field(default_factory=GradingWeights)
    
    def add_ai_grade(self, grade: ModelGrade) -> None:
        """Add an AI grade for a model."""
        self.ai_grades[grade.model_id] = grade
        self._update_status()
    
    def add_human_grade(self, grade: ModelGrade) -> None:
        """Add a human grade for a model."""
        self.human_grades[grade.model_id] = grade
        self._compute_divergence(grade.model_id)
        self._update_status()
    
    def _compute_divergence(self, model_id: str) -> None:
        """Compute divergence when both AI and human grades exist."""
        if model_id in self.ai_grades and model_id in self.human_grades:
            analysis = DivergenceAnalysis.from_grades(
                session_id=self.session_id,
                ai_grade=self.ai_grades[model_id],
                human_grade=self.human_grades[model_id],
            )
            self.divergence_analyses[model_id] = analysis
    
    def _update_status(self) -> None:
        """Update session status based on grades."""
        has_ai = len(self.ai_grades) > 0
        has_human = len(self.human_grades) > 0
        all_divergence_computed = (
            len(self.divergence_analyses) == len(self.ai_grades) == len(self.human_grades) > 0
        )
        
        if all_divergence_computed:
            self.status = "complete"
            self.completed_at = datetime.now(timezone.utc)
        elif has_human:
            self.status = "human_graded"
        elif has_ai:
            self.status = "ai_graded"
        else:
            self.status = "pending"
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of grading session."""
        return {
            "session_id": self.session_id,
            "analysis_id": self.analysis_id,
            "document_name": self.document_name,
            "status": self.status,
            "models_ai_graded": len(self.ai_grades),
            "models_human_graded": len(self.human_grades),
            "divergence_computed": len(self.divergence_analyses),
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "session_id": self.session_id,
            "analysis_id": self.analysis_id,
            "document_id": self.document_id,
            "document_name": self.document_name,
            "ai_grades": {k: v.to_dict() for k, v in self.ai_grades.items()},
            "human_grades": {k: v.to_dict() for k, v in self.human_grades.items()},
            "divergence_analyses": {k: v.to_dict() for k, v in self.divergence_analyses.items()},
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status,
            "weights": self.weights.model_dump(),
        }


class DivergenceReport(BaseModel):
    """Aggregated divergence report across multiple sessions."""
    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    
    # Filters applied
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    model_filter: Optional[str] = None
    
    # Statistics
    total_sessions: int = 0
    total_grades_compared: int = 0
    
    # Overall divergence stats
    avg_overall_divergence: float = 0.0
    max_overall_divergence: float = 0.0
    min_overall_divergence: float = 0.0
    
    # Per-criterion stats
    criterion_stats: Dict[str, Dict[str, float]] = Field(
        default_factory=dict,
        description="Stats per criterion: avg, max, min divergence"
    )
    
    # Distribution of divergence levels
    level_distribution: Dict[str, int] = Field(
        default_factory=lambda: {
            "none": 0, "low": 0, "medium": 0, "high": 0
        }
    )
    
    # Per-model statistics
    model_stats: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="Per-model divergence statistics"
    )
    
    # Trend data (for time-series analysis)
    trend_data: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Time-series divergence data"
    )
    
    # Calibration recommendations
    recommendations: List[str] = Field(
        default_factory=list,
        description="Recommendations for improving AI grading accuracy"
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return self.model_dump()
