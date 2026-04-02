# src/embeddings/service.py
"""
EmbeddingService — unified embedding gateway with multi-provider fallback.

This service provides a consistent interface for generating embeddings across
multiple providers, with automatic fallback when primary providers fail.

Provider Priority (default):
1. Voyage-3 (1536-dim) — best for technical/legal documents
2. Gemini text-embedding-005 (768-dim) — fast, reliable
3. Google Vertex AI text-embedding-004 (768-dim) — production fallback
4. HuggingFace BGE-large (1024-dim) — local/self-hosted option
5. OpenAI text-embedding-3-large (3072-dim) — if available

Usage:
    from embeddings import get_embedding_service
    
    service = get_embedding_service()
    result = service.embed("Construction RFI regarding window flashing")
    print(result.embedding)  # [0.123, -0.456, ...]
    print(result.dimensions)  # 1536
    print(result.provider)    # "voyage"
"""
import logging
import os
import threading
from typing import Optional

from .models import (
    EmbeddingConfig,
    EmbeddingProvider,
    EmbeddingResult,
    BatchEmbeddingResult,
    DEFAULT_CONFIGS,
)
from .providers import (
    BaseEmbeddingProvider,
    VoyageProvider,
    GeminiProvider,
    GoogleVertexProvider,
    HuggingFaceProvider,
    OpenAIProvider,
    create_provider,
)

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Unified embedding service with multi-provider fallback support.
    
    Features:
    - Automatic provider selection based on availability and priority
    - Fallback chain when primary provider fails
    - Dimension normalization for cross-provider compatibility
    - Batch embedding support with automatic chunking
    - Thread-safe singleton pattern
    
    Configuration via environment variables:
    - EMBEDDING_PRIMARY_PROVIDER: Override primary provider (voyage/gemini/google_vertex/huggingface)
    - EMBEDDING_FALLBACK_PROVIDERS: Comma-separated fallback order
    - EMBEDDING_DISABLE_FALLBACK: Set to "true" to disable fallback
    - VOYAGE_API_KEY: API key for Voyage
    - GOOGLE_AI_API_KEY: API key for Gemini
    - HUGGINGFACE_TOKEN: Token for HuggingFace
    """

    def __init__(
        self,
        primary_provider: Optional[EmbeddingProvider] = None,
        fallback_providers: Optional[list[EmbeddingProvider]] = None,
        custom_configs: Optional[dict[EmbeddingProvider, EmbeddingConfig]] = None,
    ):
        """
        Initialize the embedding service.
        
        Args:
            primary_provider: Override the primary provider
            fallback_providers: Override the fallback chain
            custom_configs: Custom configurations per provider
        """
        self._providers: dict[EmbeddingProvider, BaseEmbeddingProvider] = {}
        self._configs = custom_configs or {}
        
        # Read config from environment
        env_primary = os.environ.get("EMBEDDING_PRIMARY_PROVIDER", "").lower()
        env_fallback = os.environ.get("EMBEDDING_FALLBACK_PROVIDERS", "")
        
        # Determine primary provider
        if primary_provider:
            self._primary = primary_provider
        elif env_primary:
            try:
                self._primary = EmbeddingProvider(env_primary)
            except ValueError:
                logger.warning(f"Invalid EMBEDDING_PRIMARY_PROVIDER: {env_primary}")
                self._primary = None
        else:
            self._primary = None
        
        # Determine fallback chain
        if fallback_providers:
            self._fallback_chain = fallback_providers
        elif env_fallback:
            self._fallback_chain = []
            for p in env_fallback.split(","):
                try:
                    self._fallback_chain.append(EmbeddingProvider(p.strip().lower()))
                except ValueError:
                    logger.warning(f"Invalid provider in fallback chain: {p}")
        else:
            self._fallback_chain = None
        
        self._disable_fallback = os.environ.get("EMBEDDING_DISABLE_FALLBACK", "").lower() == "true"
        self._active_provider: Optional[EmbeddingProvider] = None
        self._init_lock = threading.Lock()
        self._initialized = False

    def _init_providers(self) -> None:
        """Initialize available providers."""
        with self._init_lock:
            if self._initialized:
                return
            
            # Define provider chain in priority order
            if self._primary and self._fallback_chain:
                provider_chain = [self._primary] + self._fallback_chain
            elif self._primary:
                # Primary specified, default fallback
                provider_chain = [self._primary] + [
                    p for p in [
                        EmbeddingProvider.VOYAGE,
                        EmbeddingProvider.GEMINI,
                        EmbeddingProvider.GOOGLE_VERTEX,
                        EmbeddingProvider.HUGGINGFACE,
                    ]
                    if p != self._primary
                ]
            elif self._fallback_chain:
                provider_chain = self._fallback_chain
            else:
                # Default priority order
                provider_chain = [
                    EmbeddingProvider.VOYAGE,
                    EmbeddingProvider.GEMINI,
                    EmbeddingProvider.GOOGLE_VERTEX,
                    EmbeddingProvider.HUGGINGFACE,
                    EmbeddingProvider.OPENAI,
                ]
            
            # Initialize each provider
            for provider_type in provider_chain:
                config = self._configs.get(provider_type)
                try:
                    provider = create_provider(provider_type, config)
                    if provider.is_available():
                        self._providers[provider_type] = provider
                        logger.debug(f"Initialized {provider_type.value} provider")
                    else:
                        logger.debug(f"{provider_type.value} provider not available")
                except Exception as e:
                    logger.warning(f"Failed to initialize {provider_type.value}: {e}")
            
            # Set active provider to first available
            if self._providers:
                self._active_provider = list(self._providers.keys())[0]
                logger.info(f"Primary embedding provider: {self._active_provider.value}")
            else:
                logger.error("No embedding providers available!")
            
            self._initialized = True

    def _get_provider(self, provider: Optional[EmbeddingProvider] = None) -> BaseEmbeddingProvider:
        """Get a specific or the active provider."""
        self._init_providers()
        
        if provider:
            if provider in self._providers:
                return self._providers[provider]
            raise ValueError(f"Provider {provider} not available")
        
        if self._active_provider and self._active_provider in self._providers:
            return self._providers[self._active_provider]
        
        if self._providers:
            return next(iter(self._providers.values()))
        
        raise RuntimeError("No embedding providers available")

    def embed(
        self,
        text: str,
        provider: Optional[EmbeddingProvider] = None,
    ) -> EmbeddingResult:
        """
        Embed a single text with automatic fallback.
        
        Args:
            text: The text to embed
            provider: Optional specific provider to use
        
        Returns:
            EmbeddingResult with the embedding vector and metadata
        """
        self._init_providers()
        
        if provider:
            # Use specific provider, no fallback
            return self._get_provider(provider).embed(text)
        
        # Try each provider in order
        errors = []
        for prov_type, prov in self._providers.items():
            try:
                result = prov.embed(text)
                return result
            except Exception as e:
                errors.append((prov_type.value, str(e)))
                logger.warning(f"Embed failed with {prov_type.value}: {e}")
                if self._disable_fallback:
                    break
        
        error_details = "; ".join(f"{p}: {e}" for p, e in errors)
        raise RuntimeError(f"All embedding providers failed: {error_details}")

    def embed_batch(
        self,
        texts: list[str],
        provider: Optional[EmbeddingProvider] = None,
    ) -> BatchEmbeddingResult:
        """
        Embed a batch of texts with automatic fallback.
        
        Args:
            texts: List of texts to embed
            provider: Optional specific provider to use
        
        Returns:
            BatchEmbeddingResult with embeddings and metadata
        """
        self._init_providers()
        
        if provider:
            return self._get_provider(provider).embed_batch(texts)
        
        # Try each provider in order
        errors = []
        for prov_type, prov in self._providers.items():
            try:
                result = prov.embed_batch(texts)
                return result
            except Exception as e:
                errors.append((prov_type.value, str(e)))
                logger.warning(f"Batch embed failed with {prov_type.value}: {e}")
                if self._disable_fallback:
                    break
        
        error_details = "; ".join(f"{p}: {e}" for p, e in errors)
        raise RuntimeError(f"All embedding providers failed: {error_details}")

    def get_available_providers(self) -> list[EmbeddingProvider]:
        """Get list of available providers."""
        self._init_providers()
        return list(self._providers.keys())

    def get_active_provider(self) -> Optional[EmbeddingProvider]:
        """Get the currently active (primary) provider."""
        self._init_providers()
        return self._active_provider

    def get_dimensions(self, provider: Optional[EmbeddingProvider] = None) -> int:
        """Get embedding dimensions for a provider."""
        prov = self._get_provider(provider)
        return prov.config.dimensions

    def set_primary_provider(self, provider: EmbeddingProvider) -> None:
        """Set the primary provider to use."""
        self._init_providers()
        if provider not in self._providers:
            raise ValueError(f"Provider {provider} not available")
        self._active_provider = provider
        logger.info(f"Primary provider changed to: {provider.value}")


# Singleton instance
_embedding_service: Optional[EmbeddingService] = None
_service_lock = threading.Lock()


def get_embedding_service(
    reset: bool = False,
    **kwargs,
) -> EmbeddingService:
    """
    Get the singleton EmbeddingService instance.
    
    Args:
        reset: If True, create a new instance
        **kwargs: Passed to EmbeddingService constructor if creating new instance
    
    Returns:
        The EmbeddingService singleton
    """
    global _embedding_service
    
    with _service_lock:
        if reset or _embedding_service is None:
            _embedding_service = EmbeddingService(**kwargs)
        return _embedding_service


# Convenience function for direct embedding
def embed(text: str, provider: Optional[EmbeddingProvider] = None) -> list[float]:
    """
    Convenience function to embed a single text.
    
    Returns just the embedding vector for simple use cases.
    """
    result = get_embedding_service().embed(text, provider)
    return result.embedding
