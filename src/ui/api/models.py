"""
Pydantic models for the TeterAI web API request/response payloads.
"""
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserInfo"


class UserInfo(BaseModel):
    uid: str
    email: str
    display_name: str
    role: str  # CA_STAFF | ADMIN | REVIEWER


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

class TaskSummary(BaseModel):
    task_id: str
    status: str
    urgency: str
    document_type: str
    document_number: Optional[str] = None
    project_number: Optional[str] = None
    sender_name: Optional[str] = None
    subject: Optional[str] = None
    created_at: Optional[datetime] = None
    response_due: Optional[datetime] = None
    classification_confidence: Optional[float] = None
    assigned_agent: Optional[str] = None


class TaskDetail(TaskSummary):
    draft_content: Optional[str] = None
    draft_version: Optional[str] = None
    agent_id: Optional[str] = None
    agent_version: Optional[str] = None
    confidence_score: Optional[float] = None
    citations: list[str] = []
    thought_chain_file_id: Optional[str] = None
    source_email: Optional[dict[str, Any]] = None
    attachments: list[dict[str, Any]] = []
    phase: Optional[str] = None
    rejection_reason: Optional[str] = None
    rejection_notes: Optional[str] = None
    delivered_path: Optional[str] = None


class ApproveRequest(BaseModel):
    edited_draft: Optional[str] = None  # None = approved as-is


class RejectRequest(BaseModel):
    reason: str  # CitationError | ContentError | ToneStyle | MissingInfo | ScopeIssue | Other
    notes: Optional[str] = None


class EscalateRequest(BaseModel):
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

class ProjectSummary(BaseModel):
    project_id: str
    project_number: str
    name: str
    phase: str
    active: bool
    created_at: Optional[datetime] = None


class CreateProjectRequest(BaseModel):
    project_number: str
    name: str
    phase: str = "construction"
    known_senders: list[str] = []


class ScanProjectsResponse(BaseModel):
    imported: list[ProjectSummary]
    skipped: int
    errors: list[str]


class UpdateProjectRequest(BaseModel):
    phase: Optional[str] = None
    active: Optional[bool] = None
    name: Optional[str] = None


# ---------------------------------------------------------------------------
# Closeout
# ---------------------------------------------------------------------------

class CloseoutChecklistItem(BaseModel):
    item_id: str
    project_id: str
    spec_section: str
    spec_title: str
    document_type: str
    label: str
    urgency: str
    status: str
    responsible_party: Optional[str] = None
    document_path: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    deficiency_notes: Optional[str] = None
    notes: Optional[str] = None

class UpdateChecklistItemRequest(BaseModel):
    status: Optional[str] = None
    document_path: Optional[str] = None
    responsible_party: Optional[str] = None
    notes: Optional[str] = None

class CreateDeficiencyRequest(BaseModel):
    description: str
    severity: str = "MEDIUM"

class CloseoutDeficiency(BaseModel):
    deficiency_id: str
    item_id: str
    project_id: str
    description: str
    severity: str
    status: str
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    notes: Optional[str] = None

class CloseoutSummary(BaseModel):
    project_id: str
    project_name: str
    total_items: int
    not_received: int
    received: int
    under_review: int
    accepted: int
    deficient: int
    completion_pct: float
    items: list[CloseoutChecklistItem]
    deficiencies: list[CloseoutDeficiency] = []

class CloseoutScanResult(BaseModel):
    matched: list[dict]
    unmatched: list[str]

class AddChecklistItemRequest(BaseModel):
    spec_section: str
    spec_title: str
    document_type: str
    urgency: str = "MEDIUM"
    responsible_party: Optional[str] = None


# ---------------------------------------------------------------------------
# Users (Admin)
# ---------------------------------------------------------------------------

class UserSummary(BaseModel):
    uid: str
    email: str
    display_name: str
    role: str
    active: bool


class UpdateRoleRequest(BaseModel):
    role: str  # CA_STAFF | ADMIN | REVIEWER


# ---------------------------------------------------------------------------
# Model Registry (Admin)
# ---------------------------------------------------------------------------

class ModelRegistryEntry(BaseModel):
    capability_class: str
    tier_1: str
    tier_2: Optional[str] = None
    tier_3: Optional[str] = None


class UpdateModelRequest(BaseModel):
    tier: int  # 1, 2, or 3
    model: str


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

class AuditEntrySummary(BaseModel):
    log_id: str
    log_type: str
    timestamp: Optional[datetime] = None
    task_id: Optional[str] = None
    agent_id: Optional[str] = None
    reviewer_uid: Optional[str] = None
    action: Optional[str] = None
    status: Optional[str] = None
    details: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Document Analysis
# ---------------------------------------------------------------------------

class DocumentAnalysisRequest(BaseModel):
    """Request to analyze a document using multi-model analysis."""
    content: Optional[str] = None  # Pre-extracted content
    analysis_prompt: Optional[str] = None  # Custom prompt
    use_construction_prompt: bool = False  # Use construction-specific prompt
    document_name: Optional[str] = None
    document_type: Optional[str] = None


class ModelResponseSummary(BaseModel):
    """Summary of a single model's analysis response."""
    tier: int
    model_name: str
    provider: str
    status: str
    latency_ms: int
    tokens_used: int
    summary: Optional[str] = None
    key_findings: list[str] = []
    recommendations: list[str] = []
    confidence_score: Optional[float] = None
    error: Optional[str] = None


class DocumentAnalysisResponse(BaseModel):
    """Response from multi-model document analysis."""
    analysis_id: str
    document_name: Optional[str] = None
    document_type: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    total_latency_ms: int
    successful_models: int
    failed_models: int
    models: dict[str, ModelResponseSummary] = {}


class ComparisonViewResponse(BaseModel):
    """Side-by-side comparison view of all model outputs."""
    analysis_id: str
    document: dict[str, Any]
    timing: dict[str, Any]
    summary: dict[str, Any]
    columns: list[dict[str, Any]]




# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

class GradeAnalysisRequest(BaseModel):
    """Request to auto-grade a multi-model analysis result."""
    analysis_id: str
    document_content: str
    analysis_purpose: str = "General document analysis"


class CriterionScoreInput(BaseModel):
    """Input for a single criterion score."""
    score: float  # 0-10
    reasoning: str = ""
    evidence: list[str] = []


class HumanGradeRequest(BaseModel):
    """Request to submit human grades for a model."""
    session_id: str
    model_id: str
    grader_id: str
    scores: dict[str, CriterionScoreInput]  # accuracy, completeness, relevance, citation_quality
    notes: str = ""


class CriterionScoreResponse(BaseModel):
    """Response containing a criterion score."""
    criterion: str
    score: float
    reasoning: str
    evidence: list[str] = []


class ModelGradeResponse(BaseModel):
    """Response containing a model's grade."""
    grade_id: str
    model_id: str
    model_name: str
    tier: int
    source: str  # ai_judge or human
    accuracy: Optional[CriterionScoreResponse] = None
    completeness: Optional[CriterionScoreResponse] = None
    relevance: Optional[CriterionScoreResponse] = None
    citation_quality: Optional[CriterionScoreResponse] = None
    overall_score: float
    grader_id: Optional[str] = None
    graded_at: Optional[datetime] = None
    notes: str = ""


class CriterionDivergenceResponse(BaseModel):
    """Response containing divergence for a single criterion."""
    criterion: str
    ai_score: float
    human_score: float
    difference: float
    level: str  # none, low, medium, high
    notes: str = ""


class DivergenceAnalysisResponse(BaseModel):
    """Response containing divergence analysis."""
    analysis_id: str
    session_id: str
    model_id: str
    model_name: str
    criterion_divergences: list[CriterionDivergenceResponse]
    overall_ai_score: float
    overall_human_score: float
    overall_difference: float
    overall_level: str
    analyzed_at: Optional[datetime] = None
    calibration_notes: str = ""
    action_items: list[str] = []


class GradingSessionResponse(BaseModel):
    """Response containing grading session details."""
    session_id: str
    analysis_id: str
    document_id: Optional[str] = None
    document_name: Optional[str] = None
    status: str  # pending, ai_graded, human_graded, complete
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    ai_grades: dict[str, ModelGradeResponse] = {}
    human_grades: dict[str, ModelGradeResponse] = {}
    divergence_analyses: dict[str, DivergenceAnalysisResponse] = {}


class GradingSessionSummary(BaseModel):
    """Summary of a grading session for list views."""
    session_id: str
    analysis_id: str
    document_name: Optional[str] = None
    status: str
    models_ai_graded: int
    models_human_graded: int
    divergence_computed: int
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class DivergenceReportResponse(BaseModel):
    """Response containing aggregated divergence report."""
    report_id: str
    generated_at: Optional[datetime] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    model_filter: Optional[str] = None
    total_sessions: int
    total_grades_compared: int
    avg_overall_divergence: float
    max_overall_divergence: float
    min_overall_divergence: float
    criterion_stats: dict[str, dict[str, float]] = {}
    level_distribution: dict[str, int] = {}
    model_stats: dict[str, dict[str, Any]] = {}
    trend_data: list[dict[str, Any]] = []
    recommendations: list[str] = []


class AddDivergenceNotesRequest(BaseModel):
    """Request to add calibration notes to divergence analysis."""
    calibration_notes: str
    action_items: list[str] = []
