from enum import Enum
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field

class TaskStatus(str, Enum):
    PENDING_CLASSIFICATION = "PENDING_CLASSIFICATION"
    CLASSIFYING = "CLASSIFYING"
    ASSIGNED_TO_AGENT = "ASSIGNED_TO_AGENT"
    PROCESSING = "PROCESSING"
    STAGED_FOR_REVIEW = "STAGED_FOR_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DELIVERED = "DELIVERED"
    ESCALATED_TO_HUMAN = "ESCALATED_TO_HUMAN"
    ERROR = "ERROR"

class Urgency(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class TriggerType(str, Enum):
    AGENT = "AGENT"
    HUMAN = "HUMAN"
    SCHEDULER = "SCHEDULER"
    SYSTEM = "SYSTEM"

class StatusHistoryEntry(BaseModel):
    from_status: str
    to_status: str
    triggered_by: str
    trigger_type: TriggerType
    timestamp: datetime
    notes: Optional[str] = None

class Task(BaseModel):
    task_id: str
    ingest_id: str
    project_id: Optional[str] = None
    project_number: Optional[str] = None
    document_type: Optional[str] = None
    document_number: Optional[str] = None
    phase: Optional[str] = None
    urgency: Urgency = Urgency.LOW
    status: TaskStatus
    assigned_agent: Optional[str] = None
    assigned_reviewer: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    status_history: List[StatusHistoryEntry] = Field(default_factory=list)
    draft_drive_path: Optional[str] = None
    final_drive_path: Optional[str] = None
    classification_confidence: Optional[float] = None
    error_message: Optional[str] = None
    correction_captured: bool = False

class CorrectionCapture(BaseModel):
    task_id: str
    agent_id: str
    original_draft: str
    edited_draft: str
    correction_type: str
    reviewer_uid: str
    timestamp: datetime
