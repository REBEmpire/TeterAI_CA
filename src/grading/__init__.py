"""Auto-grading system with human comparison capability.

This module provides:
- AutoGrader: AI-powered grading using Claude as judge
- HumanGradingInterface: Human grade input and comparison
- GradingStorage: Persistence layer for grades and divergence data
- Data models for grades, criteria, and divergence analysis

Usage:
    from grading import (
        grade_analysis,
        get_auto_grader,
        get_human_grading_interface,
    )
    
    # Auto-grade a multi-model analysis result
    session = grade_analysis(analysis_result, document_content)
    
    # Submit human grades
    human_grading = get_human_grading_interface()
    result = human_grading.submit_human_grade(
        session_id=session.session_id,
        model_id="model_123",
        grader_id="user_456",
        scores={...},
    )
    
    # Generate divergence report
    report = human_grading.get_divergence_report()
"""

from .grading_models import (
    GradingCriterion,
    GradeSource,
    DivergenceLevel,
    CriterionScore,
    GradingWeights,
    ModelGrade,
    CriterionDivergence,
    DivergenceAnalysis,
    GradingSession,
    DivergenceReport,
)

from .grading_storage import (
    GradingStorage,
    get_grading_storage,
)

from .grading_service import (
    AutoGrader,
    get_auto_grader,
    grade_analysis,
)

from .human_grading import (
    HumanGradingInterface,
    get_human_grading_interface,
)

__all__ = [
    # Models
    "GradingCriterion",
    "GradeSource",
    "DivergenceLevel",
    "CriterionScore",
    "GradingWeights",
    "ModelGrade",
    "CriterionDivergence",
    "DivergenceAnalysis",
    "GradingSession",
    "DivergenceReport",
    # Storage
    "GradingStorage",
    "get_grading_storage",
    # Auto-grading
    "AutoGrader",
    "get_auto_grader",
    "grade_analysis",
    # Human grading
    "HumanGradingInterface",
    "get_human_grading_interface",
]
