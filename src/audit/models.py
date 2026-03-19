import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field


class LogType(str, Enum):
    AGENT_ACTION = "AGENT_ACTION"
    AI_CALL = "AI_CALL"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    SYSTEM_EVENT = "SYSTEM_EVENT"
    ERROR = "ERROR"


class ErrorSeverity(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class HumanReviewAction(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EDITED_AND_APPROVED = "EDITED_AND_APPROVED"
    ESCALATED = "ESCALATED"


class BaseAuditEntry(BaseModel):
    log_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    log_type: LogType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentActionLog(BaseAuditEntry):
    log_type: Literal[LogType.AGENT_ACTION] = LogType.AGENT_ACTION
    agent_id: str
    task_id: str
    action: str
    input_summary: str
    output_summary: str
    confidence_score: Optional[float] = None
    ai_call_ids: list[str] = Field(default_factory=list)
    duration_ms: int
    status: str  # SUCCESS | ERROR


class AICallLog(BaseAuditEntry):
    log_type: Literal[LogType.AI_CALL] = LogType.AI_CALL
    ai_call_id: str
    task_id: str
    calling_agent: str
    capability_class: str
    tier_used: int
    provider: str
    model: str
    fallback_triggered: bool
    input_tokens: int
    output_tokens: int
    latency_ms: int
    status: str  # SUCCESS | ERROR


class HumanReviewLog(BaseAuditEntry):
    log_type: Literal[LogType.HUMAN_REVIEW] = LogType.HUMAN_REVIEW
    task_id: str
    reviewer_uid: str
    reviewer_name: str
    action: HumanReviewAction
    original_draft_version: str
    edits_made: bool
    edit_summary: Optional[str] = None
    correction_type: Optional[str] = None
    duration_seconds: int
    delivery_triggered: bool


class SystemEventLog(BaseAuditEntry):
    log_type: Literal[LogType.SYSTEM_EVENT] = LogType.SYSTEM_EVENT
    event: str
    component: str
    details: dict[str, Any] = Field(default_factory=dict)
    status: str  # SUCCESS | ERROR


class ErrorLog(BaseAuditEntry):
    log_type: Literal[LogType.ERROR] = LogType.ERROR
    component: str
    task_id: Optional[str] = None
    error_code: str
    error_message: str
    fallback_action: Optional[str] = None
    severity: ErrorSeverity


AuditEntry = Union[AgentActionLog, AICallLog, HumanReviewLog, SystemEventLog, ErrorLog]


class ThoughtChain(BaseModel):
    task_id: str
    agent_id: str
    step: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    system_prompt: str
    user_prompt: str
    model_response: str
    knowledge_graph_queries: list[dict[str, Any]] = Field(default_factory=list)
    confidence_score: Optional[float] = None
