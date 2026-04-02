"""Structured response classes for multi-model document analysis.

Provides Pydantic models for:
- Individual model responses with metadata
- Combined multi-model analysis results
- Error handling for partial failures
"""
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


class AnalysisStatus(str, Enum):
    """Status of an individual model's analysis."""
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"


class AnalysisMetadata(BaseModel):
    """Metadata about a single model's analysis."""
    model_id: str = Field(description="Unique identifier for this model call")
    provider: str = Field(description="AI provider (anthropic, google, xai)")
    model: str = Field(description="Model name/version")
    tier: int = Field(description="Tier number (1, 2, or 3)")
    latency_ms: int = Field(description="Response time in milliseconds")
    input_tokens: int = Field(default=0, description="Number of input tokens")
    output_tokens: int = Field(default=0, description="Number of output tokens")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    @property
    def total_tokens(self) -> int:
        """Total tokens used."""
        return self.input_tokens + self.output_tokens
    
    @property
    def tokens_per_second(self) -> float:
        """Output tokens per second throughput."""
        if self.latency_ms <= 0:
            return 0.0
        return (self.output_tokens * 1000) / self.latency_ms


class ModelAnalysisResponse(BaseModel):
    """Response from a single AI model's document analysis."""
    status: AnalysisStatus = Field(description="Status of this model's analysis")
    content: Optional[str] = Field(default=None, description="Analysis content/output")
    metadata: Optional[AnalysisMetadata] = Field(default=None, description="Call metadata")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    
    # Structured analysis fields (populated by parsing the content)
    summary: Optional[str] = Field(default=None, description="Executive summary")
    key_findings: List[str] = Field(default_factory=list, description="Key findings list")
    recommendations: List[str] = Field(default_factory=list, description="Recommendations")
    confidence_score: Optional[float] = Field(
        default=None, 
        ge=0.0, 
        le=1.0, 
        description="Model's confidence in its analysis (0-1)"
    )
    
    @property
    def is_success(self) -> bool:
        """Whether this model call succeeded."""
        return self.status == AnalysisStatus.SUCCESS
    
    @classmethod
    def from_error(cls, error: str, provider: str = "", model: str = "", tier: int = 0) -> "ModelAnalysisResponse":
        """Create a failed response from an error."""
        return cls(
            status=AnalysisStatus.FAILED,
            error=error,
            metadata=AnalysisMetadata(
                model_id=str(uuid.uuid4()),
                provider=provider,
                model=model,
                tier=tier,
                latency_ms=0,
                input_tokens=0,
                output_tokens=0,
            ) if provider else None
        )


class MultiModelAnalysisResult(BaseModel):
    """Combined result from all three models analyzing the same document."""
    analysis_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this analysis session"
    )
    document_id: Optional[str] = Field(default=None, description="Source document ID")
    document_name: Optional[str] = Field(default=None, description="Source document name")
    document_type: Optional[str] = Field(default=None, description="Document type (PDF, Word, etc.)")
    
    # Timestamps
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = Field(default=None)
    
    # Model responses keyed by tier
    tier_1_response: Optional[ModelAnalysisResponse] = Field(
        default=None, 
        description="Claude Opus 4.6 response"
    )
    tier_2_response: Optional[ModelAnalysisResponse] = Field(
        default=None, 
        description="Gemini 3.1 Pro response"
    )
    tier_3_response: Optional[ModelAnalysisResponse] = Field(
        default=None, 
        description="Grok 4.2 response"
    )
    
    # Aggregate metrics
    total_latency_ms: int = Field(default=0, description="Total wall-clock time")
    successful_models: int = Field(default=0, description="Count of successful model calls")
    failed_models: int = Field(default=0, description="Count of failed model calls")
    
    @property
    def is_complete(self) -> bool:
        """Whether all models have responded."""
        return all([
            self.tier_1_response is not None,
            self.tier_2_response is not None,
            self.tier_3_response is not None,
        ])
    
    @property
    def has_at_least_one_success(self) -> bool:
        """Whether at least one model succeeded."""
        return self.successful_models > 0
    
    @property
    def all_models_succeeded(self) -> bool:
        """Whether all three models succeeded."""
        return self.successful_models == 3
    
    def get_responses_dict(self) -> Dict[str, Optional[ModelAnalysisResponse]]:
        """Get all responses as a dictionary keyed by tier."""
        return {
            "tier_1": self.tier_1_response,
            "tier_2": self.tier_2_response,
            "tier_3": self.tier_3_response,
        }
    
    def get_successful_responses(self) -> List[ModelAnalysisResponse]:
        """Get list of successful responses only."""
        responses = []
        for resp in [self.tier_1_response, self.tier_2_response, self.tier_3_response]:
            if resp and resp.is_success:
                responses.append(resp)
        return responses
    
    def to_summary_dict(self) -> Dict[str, Any]:
        """Convert to a summary dictionary for API responses."""
        return {
            "analysis_id": self.analysis_id,
            "document_id": self.document_id,
            "document_name": self.document_name,
            "document_type": self.document_type,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "total_latency_ms": self.total_latency_ms,
            "successful_models": self.successful_models,
            "failed_models": self.failed_models,
            "models": {
                "tier_1": self._response_summary(self.tier_1_response, "Claude Opus 4.6"),
                "tier_2": self._response_summary(self.tier_2_response, "Gemini 3.1 Pro"),
                "tier_3": self._response_summary(self.tier_3_response, "Grok 4.2"),
            }
        }
    
    def _response_summary(self, resp: Optional[ModelAnalysisResponse], display_name: str) -> Dict[str, Any]:
        """Create summary dict for a single response."""
        if resp is None:
            return {"display_name": display_name, "status": "pending"}
        return {
            "display_name": display_name,
            "status": resp.status.value,
            "latency_ms": resp.metadata.latency_ms if resp.metadata else 0,
            "tokens_used": resp.metadata.total_tokens if resp.metadata else 0,
            "error": resp.error,
        }
