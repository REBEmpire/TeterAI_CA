import uuid
from enum import Enum
from typing import Optional, Dict, List, Any
from pydantic import BaseModel, Field

class CapabilityClass(str, Enum):
    REASON_DEEP = "REASON_DEEP"
    REASON_STANDARD = "REASON_STANDARD"
    CLASSIFY = "CLASSIFY"
    GENERATE_DOC = "GENERATE_DOC"
    EXTRACT = "EXTRACT"
    MULTIMODAL = "MULTIMODAL"
    SUBMITTAL_REVIEW = "SUBMITTAL_REVIEW"
    RED_TEAM_CRITIQUE = "RED_TEAM_CRITIQUE"

class Attachment(BaseModel):
    file_type: str
    content: str

class AIRequest(BaseModel):
    capability_class: CapabilityClass
    system_prompt: str
    user_prompt: str
    attachments: Optional[List[Attachment]] = None
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    calling_agent: str
    task_id: str

class AIMetadata(BaseModel):
    ai_call_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tier_used: int
    provider: str
    model: str
    fallback_triggered: bool
    latency_ms: int
    input_tokens: int
    output_tokens: int

class AIResponse(BaseModel):
    content: str
    metadata: AIMetadata
    success: bool
    error: Optional[str] = None

class ModelConfig(BaseModel):
    provider: str
    model: str
    max_tokens: int

class CapabilityConfig(BaseModel):
    tier_1: Optional[ModelConfig] = None
    tier_2: Optional[ModelConfig] = None
    tier_3: Optional[ModelConfig] = None

class ModelRegistry(BaseModel):
    version: str
    updated_at: str
    capability_classes: Dict[CapabilityClass, CapabilityConfig]

class InvalidCapabilityClassError(Exception):
    pass

class AIEngineExhaustedError(Exception):
    pass
