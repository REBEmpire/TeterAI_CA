# src/embeddings/providers.py
"""
Embedding provider implementations.

Each provider wraps a specific embedding API and normalizes the interface
for consistent use across the EmbeddingService.
"""
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

from .models import (
    EmbeddingConfig,
    EmbeddingProvider,
    EmbeddingResult,
    BatchEmbeddingResult,
    DEFAULT_CONFIGS,
)

logger = logging.getLogger(__name__)


class BaseEmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    def __init__(self, config: Optional[EmbeddingConfig] = None):
        self.config = config or self._default_config()
        self._api_key: Optional[str] = None

    @abstractmethod
    def _default_config(self) -> EmbeddingConfig:
        """Return default configuration for this provider."""
        pass

    @abstractmethod
    def _embed_texts(self, texts: list[str]) -> tuple[list[list[float]], int]:
        """
        Internal method to embed texts.
        Returns: (embeddings, total_tokens)
        """
        pass

    def _get_api_key(self) -> str:
        """Get API key from environment."""
        if self._api_key is None:
            self._api_key = os.environ.get(self.config.api_key_env, "")
        return self._api_key

    def _normalize(self, embedding: list[float]) -> list[float]:
        """L2 normalize an embedding vector."""
        if not self.config.normalize:
            return embedding
        arr = np.array(embedding, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        return arr.tolist()

    def _truncate_text(self, text: str) -> tuple[str, bool]:
        """
        Truncate text if it exceeds max tokens (approximation).
        Returns: (truncated_text, was_truncated)
        """
        if not self.config.truncate:
            return text, False
        # Rough approximation: 4 chars per token
        max_chars = self.config.max_tokens * 4
        if len(text) > max_chars:
            return text[:max_chars], True
        return text, False

    def is_available(self) -> bool:
        """Check if this provider is available (has API key, etc.)."""
        return bool(self._get_api_key())

    def embed(self, text: str) -> EmbeddingResult:
        """Embed a single text."""
        text, truncated = self._truncate_text(text)
        start = time.time()
        embeddings, tokens = self._embed_texts([text])
        latency_ms = int((time.time() - start) * 1000)

        embedding = self._normalize(embeddings[0]) if embeddings else []

        return EmbeddingResult(
            embedding=embedding,
            dimensions=len(embedding),
            provider=self.config.provider.value,
            model=self.config.model_name,
            tokens_used=tokens,
            latency_ms=latency_ms,
            truncated=truncated,
        )

    def embed_batch(self, texts: list[str]) -> BatchEmbeddingResult:
        """Embed a batch of texts."""
        processed_texts = []
        truncated_count = 0
        for text in texts:
            t, was_truncated = self._truncate_text(text)
            processed_texts.append(t)
            if was_truncated:
                truncated_count += 1

        start = time.time()
        all_embeddings = []
        total_tokens = 0
        failed_indices = []

        # Process in batches
        for i in range(0, len(processed_texts), self.config.max_batch_size):
            batch = processed_texts[i:i + self.config.max_batch_size]
            try:
                embeddings, tokens = self._embed_texts(batch)
                all_embeddings.extend([self._normalize(e) for e in embeddings])
                total_tokens += tokens
            except Exception as e:
                logger.warning(f"Batch {i // self.config.max_batch_size} failed: {e}")
                failed_indices.extend(range(i, i + len(batch)))
                all_embeddings.extend([[0.0] * self.config.dimensions] * len(batch))

        latency_ms = int((time.time() - start) * 1000)

        return BatchEmbeddingResult(
            embeddings=all_embeddings,
            dimensions=self.config.dimensions,
            provider=self.config.provider.value,
            model=self.config.model_name,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            truncated_count=truncated_count,
            failed_indices=failed_indices,
        )


class VoyageProvider(BaseEmbeddingProvider):
    """
    Voyage-3 embeddings via voyageai SDK.
    1536 dimensions, optimized for technical/legal documents.
    """

    def _default_config(self) -> EmbeddingConfig:
        return DEFAULT_CONFIGS[EmbeddingProvider.VOYAGE]

    def is_available(self) -> bool:
        """Check if Voyage is available."""
        try:
            import voyageai
            return bool(self._get_api_key())
        except ImportError:
            logger.debug("voyageai not installed")
            return False

    def _embed_texts(self, texts: list[str]) -> tuple[list[list[float]], int]:
        import voyageai

        client = voyageai.Client(api_key=self._get_api_key())
        result = client.embed(
            texts=texts,
            model=self.config.model_name,
            input_type="document",
        )
        embeddings = [e for e in result.embeddings]
        tokens = result.total_tokens if hasattr(result, "total_tokens") else 0
        return embeddings, tokens


class GeminiProvider(BaseEmbeddingProvider):
    """
    Google Gemini embeddings via google-generativeai SDK.
    text-embedding-005 with 768 dimensions.
    """

    def _default_config(self) -> EmbeddingConfig:
        return DEFAULT_CONFIGS[EmbeddingProvider.GEMINI]

    def is_available(self) -> bool:
        """Check if Gemini is available."""
        try:
            import google.generativeai
            return bool(self._get_api_key())
        except ImportError:
            logger.debug("google-generativeai not installed")
            return False

    def _embed_texts(self, texts: list[str]) -> tuple[list[list[float]], int]:
        import google.generativeai as genai

        genai.configure(api_key=self._get_api_key())
        
        embeddings = []
        total_tokens = 0
        
        for text in texts:
            result = genai.embed_content(
                model=f"models/{self.config.model_name}",
                content=text,
                task_type="retrieval_document",
            )
            embeddings.append(result["embedding"])
            # Gemini doesn't return token counts directly
            total_tokens += len(text) // 4  # approximation

        return embeddings, total_tokens


class GoogleVertexProvider(BaseEmbeddingProvider):
    """
    Google Vertex AI text-embedding-004.
    768 dimensions, production-grade embeddings.
    """

    def _default_config(self) -> EmbeddingConfig:
        return DEFAULT_CONFIGS[EmbeddingProvider.GOOGLE_VERTEX]

    def is_available(self) -> bool:
        """Check if Vertex AI is available (via litellm)."""
        try:
            import litellm
            # Check if Google credentials are available
            return bool(os.environ.get("GOOGLE_API_KEY") or 
                       os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
        except ImportError:
            return False

    def _embed_texts(self, texts: list[str]) -> tuple[list[list[float]], int]:
        import litellm

        response = litellm.embedding(
            model=f"vertex_ai/{self.config.model_name}",
            input=texts,
        )
        
        embeddings = [item["embedding"] for item in response.data]
        tokens = getattr(response.usage, "total_tokens", 0) if hasattr(response, "usage") else 0
        
        return embeddings, tokens


class HuggingFaceProvider(BaseEmbeddingProvider):
    """
    HuggingFace embeddings via sentence-transformers or HF Inference API.
    
    Supports models like:
    - BAAI/bge-large-en-v1.5 (1024-dim)
    - intfloat/e5-large-v2 (1024-dim)
    - BAAI/bge-m3 (1024-dim, multilingual)
    """

    def __init__(self, config: Optional[EmbeddingConfig] = None, use_local: bool = False):
        super().__init__(config)
        self.use_local = use_local
        self._model = None

    def _default_config(self) -> EmbeddingConfig:
        return DEFAULT_CONFIGS[EmbeddingProvider.HUGGINGFACE]

    def is_available(self) -> bool:
        """Check if HuggingFace is available."""
        if self.use_local:
            try:
                from sentence_transformers import SentenceTransformer
                return True
            except ImportError:
                logger.debug("sentence-transformers not installed")
                return False
        else:
            return bool(self._get_api_key())

    def _get_local_model(self):
        """Lazy load the local model."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.config.model_name)
        return self._model

    def _embed_texts(self, texts: list[str]) -> tuple[list[list[float]], int]:
        if self.use_local:
            return self._embed_local(texts)
        else:
            return self._embed_api(texts)

    def _embed_local(self, texts: list[str]) -> tuple[list[list[float]], int]:
        """Embed using local sentence-transformers model."""
        model = self._get_local_model()
        embeddings = model.encode(
            texts,
            normalize_embeddings=self.config.normalize,
            show_progress_bar=False,
        )
        return embeddings.tolist(), sum(len(t) // 4 for t in texts)

    def _embed_api(self, texts: list[str]) -> tuple[list[list[float]], int]:
        """Embed using HuggingFace Inference API."""
        import requests

        api_url = f"https://api-inference.huggingface.co/pipeline/feature-extraction/{self.config.model_name}"
        headers = {"Authorization": f"Bearer {self._get_api_key()}"}
        
        response = requests.post(
            api_url,
            headers=headers,
            json={"inputs": texts, "options": {"wait_for_model": True}},
        )
        response.raise_for_status()
        
        embeddings = response.json()
        # HF returns nested arrays for some models
        if embeddings and isinstance(embeddings[0][0], list):
            # Mean pooling over token embeddings
            embeddings = [np.mean(e, axis=0).tolist() for e in embeddings]
        
        return embeddings, sum(len(t) // 4 for t in texts)


class OpenAIProvider(BaseEmbeddingProvider):
    """
    OpenAI text-embedding-3-large (3072 dimensions).
    Fallback option if OpenAI API key is available.
    """

    def _default_config(self) -> EmbeddingConfig:
        return DEFAULT_CONFIGS[EmbeddingProvider.OPENAI]

    def is_available(self) -> bool:
        """Check if OpenAI is available."""
        try:
            import litellm
            return bool(os.environ.get("OPENAI_API_KEY"))
        except ImportError:
            return False

    def _embed_texts(self, texts: list[str]) -> tuple[list[list[float]], int]:
        import litellm

        response = litellm.embedding(
            model=f"openai/{self.config.model_name}",
            input=texts,
        )
        
        embeddings = [item["embedding"] for item in response.data]
        tokens = getattr(response.usage, "total_tokens", 0) if hasattr(response, "usage") else 0
        
        return embeddings, tokens


# Provider factory
def create_provider(
    provider: EmbeddingProvider,
    config: Optional[EmbeddingConfig] = None,
    **kwargs,
) -> BaseEmbeddingProvider:
    """
    Factory function to create an embedding provider.
    
    Args:
        provider: The provider type
        config: Optional custom configuration
        **kwargs: Additional arguments passed to provider constructor
    
    Returns:
        Configured provider instance
    """
    providers = {
        EmbeddingProvider.VOYAGE: VoyageProvider,
        EmbeddingProvider.GEMINI: GeminiProvider,
        EmbeddingProvider.GOOGLE_VERTEX: GoogleVertexProvider,
        EmbeddingProvider.HUGGINGFACE: HuggingFaceProvider,
        EmbeddingProvider.OPENAI: OpenAIProvider,
    }
    
    provider_class = providers.get(provider)
    if not provider_class:
        raise ValueError(f"Unknown provider: {provider}")
    
    return provider_class(config=config, **kwargs)
