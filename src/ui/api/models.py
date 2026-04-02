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
