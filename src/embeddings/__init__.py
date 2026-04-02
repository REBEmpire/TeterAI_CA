# src/embeddings/__init__.py
"""
Embeddings module for TeterAI_CA.

Provides a unified EmbeddingService with multiple provider support:
- Voyage-3 (1536-dim) - recommended for technical/legal documents
- Google text-embedding-004 (768-dim) - production fallback
- Google Gemini embeddings - next-gen Google embeddings
- HuggingFace BGE-large (1024-dim) - local/self-hosted option
"""

from .service import EmbeddingService, get_embedding_service
from .models import (
    EmbeddingProvider,
    EmbeddingConfig,
    EmbeddingResult,
    BatchEmbeddingResult,
)
from .providers import (
    BaseEmbeddingProvider,
    VoyageProvider,
    GoogleVertexProvider,
    GeminiProvider,
    HuggingFaceProvider,
)

__all__ = [
    # Service
    "EmbeddingService",
    "get_embedding_service",
    # Models
    "EmbeddingProvider",
    "EmbeddingConfig",
    "EmbeddingResult",
    "BatchEmbeddingResult",
    # Providers
    "BaseEmbeddingProvider",
    "VoyageProvider",
    "GoogleVertexProvider",
    "GeminiProvider",
    "HuggingFaceProvider",
]
