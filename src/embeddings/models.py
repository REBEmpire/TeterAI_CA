# src/embeddings/models.py
"""
Pydantic models for the embedding service.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class EmbeddingProvider(str, Enum):
    """Available embedding providers."""
    VOYAGE = "voyage"            # Voyage-3 (1536-dim) - best for technical docs
    GOOGLE_VERTEX = "google_vertex"  # text-embedding-004 (768-dim)
    GEMINI = "gemini"            # text-embedding-005
    HUGGINGFACE = "huggingface"  # BGE-large, E5, etc. (local/HF API)
    OPENAI = "openai"            # text-embedding-3-large (if available)


@dataclass
class EmbeddingConfig:
    """Configuration for an embedding provider."""
    provider: EmbeddingProvider
    model_name: str
    dimensions: int
    # Optional config
    api_key_env: str = ""       # Environment variable name for API key
    max_batch_size: int = 32    # Max texts per batch request
    max_tokens: int = 8192      # Max input tokens per text
    normalize: bool = True      # L2 normalize embeddings
    truncate: bool = True       # Truncate long texts
    priority: int = 1           # Lower = higher priority (for fallback ordering)

    def __post_init__(self):
        if not self.api_key_env:
            # Default env var names by provider
            defaults = {
                EmbeddingProvider.VOYAGE: "VOYAGE_API_KEY",
                EmbeddingProvider.GOOGLE_VERTEX: "GOOGLE_API_KEY",
                EmbeddingProvider.GEMINI: "GOOGLE_AI_API_KEY",
                EmbeddingProvider.HUGGINGFACE: "HUGGINGFACE_TOKEN",
                EmbeddingProvider.OPENAI: "OPENAI_API_KEY",
            }
            self.api_key_env = defaults.get(self.provider, "")


class EmbeddingResult(BaseModel):
    """Result from a single embedding call."""
    embedding: list[float] = Field(description="The embedding vector")
    dimensions: int = Field(description="Number of dimensions")
    provider: str = Field(description="Provider used")
    model: str = Field(description="Model used")
    tokens_used: int = Field(default=0, description="Input tokens consumed")
    latency_ms: int = Field(default=0, description="Latency in milliseconds")
    truncated: bool = Field(default=False, description="Whether input was truncated")
    cached: bool = Field(default=False, description="Whether result was cached")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class BatchEmbeddingResult(BaseModel):
    """Result from a batch embedding call."""
    embeddings: list[list[float]] = Field(description="List of embedding vectors")
    dimensions: int = Field(description="Number of dimensions")
    provider: str = Field(description="Provider used")
    model: str = Field(description="Model used")
    total_tokens: int = Field(default=0, description="Total tokens consumed")
    latency_ms: int = Field(default=0, description="Total latency in milliseconds")
    truncated_count: int = Field(default=0, description="Number of truncated inputs")
    failed_indices: list[int] = Field(default_factory=list, description="Indices that failed")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


# Default configurations for each provider
DEFAULT_CONFIGS: dict[EmbeddingProvider, EmbeddingConfig] = {
    EmbeddingProvider.VOYAGE: EmbeddingConfig(
        provider=EmbeddingProvider.VOYAGE,
        model_name="voyage-3",
        dimensions=1536,
        max_batch_size=128,
        max_tokens=16000,
        priority=1,  # Primary - best for technical/legal documents
    ),
    EmbeddingProvider.GEMINI: EmbeddingConfig(
        provider=EmbeddingProvider.GEMINI,
        model_name="text-embedding-005",
        dimensions=768,
        max_batch_size=100,
        max_tokens=2048,
        priority=2,  # Secondary fallback
    ),
    EmbeddingProvider.GOOGLE_VERTEX: EmbeddingConfig(
        provider=EmbeddingProvider.GOOGLE_VERTEX,
        model_name="text-embedding-004",
        dimensions=768,
        max_batch_size=100,
        max_tokens=2048,
        priority=3,  # Tertiary fallback
    ),
    EmbeddingProvider.HUGGINGFACE: EmbeddingConfig(
        provider=EmbeddingProvider.HUGGINGFACE,
        model_name="BAAI/bge-large-en-v1.5",
        dimensions=1024,
        max_batch_size=32,
        max_tokens=512,
        priority=4,  # Local fallback
    ),
    EmbeddingProvider.OPENAI: EmbeddingConfig(
        provider=EmbeddingProvider.OPENAI,
        model_name="text-embedding-3-large",
        dimensions=3072,
        max_batch_size=100,
        max_tokens=8192,
        priority=5,  # If available
    ),
}
