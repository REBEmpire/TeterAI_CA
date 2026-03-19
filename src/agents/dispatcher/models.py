from enum import Enum
from typing import Optional, Literal
from pydantic import BaseModel


class Phase(str, Enum):
    BID = "bid"
    CONSTRUCTION = "construction"
    CLOSEOUT = "closeout"
    UNKNOWN = "UNKNOWN"


class DocumentType(str, Enum):
    RFI = "RFI"
    SUBMITTAL = "SUBMITTAL"
    SUBSTITUTION = "SUBSTITUTION"
    CHANGE_ORDER = "CHANGE_ORDER"
    PAY_APP = "PAY_APP"
    MEETING_MINUTES = "MEETING_MINUTES"
    GENERAL = "GENERAL"
    UNKNOWN = "UNKNOWN"


class Urgency(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class TaskStatus(str, Enum):
    PENDING_CLASSIFICATION = "PENDING_CLASSIFICATION"
    CLASSIFYING = "CLASSIFYING"
    ASSIGNED_TO_AGENT = "ASSIGNED_TO_AGENT"
    ESCALATED_TO_HUMAN = "ESCALATED_TO_HUMAN"
    ERROR = "ERROR"


class DimensionResult(BaseModel):
    value: str
    confidence: float  # 0.0–1.0
    reasoning: str


class ClassificationResult(BaseModel):
    project_id: DimensionResult
    phase: DimensionResult
    document_type: DimensionResult
    urgency: DimensionResult
    raw_response: str  # original AI output for audit


class RoutingDecision(BaseModel):
    action: Literal["ASSIGN_TO_AGENT", "ESCALATE_TO_HUMAN"]
    assigned_agent: Optional[str] = None  # e.g. "AGENT-RFI-001" or None
    reason: str
    all_confident: bool


class ClassificationParseError(Exception):
    pass
