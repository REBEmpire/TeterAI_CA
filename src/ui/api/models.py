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
