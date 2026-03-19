import os
import time
import logging
import litellm
from typing import Optional

from .models import (
    AIRequest,
    AIResponse,
    AIMetadata,
    ModelRegistry,
    InvalidCapabilityClassError,
    AIEngineExhaustedError,
    ModelConfig
)
from .gcp import gcp_integration

logger = logging.getLogger(__name__)

class AIEngine:
    def __init__(self):
        self._registry_cache: Optional[ModelRegistry] = None
        self._cache_time: float = 0
        self._cache_ttl: int = int(os.environ.get("AI_ENGINE_CACHE_TTL_SECONDS", 60))

        gcp_integration.load_secrets_to_env()

    def _get_registry(self) -> ModelRegistry:
        now = time.time()
        if self._registry_cache and (now - self._cache_time) < self._cache_ttl:
            return self._registry_cache

        registry = gcp_integration.get_model_registry()
        if not registry:
            if self._registry_cache:
                logger.warning("Failed to fetch registry from Firestore, using stale cache.")
                return self._registry_cache
            raise RuntimeError("Failed to fetch model registry and no cache available.")

        self._registry_cache = registry
        self._cache_time = now
        return registry

    def generate_response(self, request: AIRequest) -> AIResponse:
        registry = self._get_registry()

        if request.capability_class not in registry.capability_classes:
            raise InvalidCapabilityClassError(f"Capability class {request.capability_class} not found in registry.")

        config = registry.capability_classes[request.capability_class]

        tiers = []
        if config.tier_1: tiers.append((1, config.tier_1))
        if config.tier_2: tiers.append((2, config.tier_2))
        if config.tier_3: tiers.append((3, config.tier_3))

        if not tiers:
            raise RuntimeError(f"No model tiers configured for {request.capability_class}")

        fallback_triggered = False
        last_error = None

        for tier_num, tier_config in tiers:
            try:
                if tier_num > 1:
                    fallback_triggered = True
                    logger.warning(f"Fallback triggered: attempting Tier {tier_num} ({tier_config.provider}/{tier_config.model})")

                response = self._call_model(request, tier_config)

                response.metadata.tier_used = tier_num
                response.metadata.fallback_triggered = fallback_triggered
                return response

            except Exception as e:
                logger.error(f"Tier {tier_num} ({tier_config.provider}/{tier_config.model}) failed: {e}")
                last_error = e

        logger.critical(f"All AI Engine tiers exhausted for task {request.task_id}.")
        raise AIEngineExhaustedError(f"All tiers exhausted. Last error: {last_error}")

    def _call_model(self, request: AIRequest, config: ModelConfig) -> AIResponse:
        messages = [
            {"role": "system", "content": request.system_prompt},
            {"role": "user", "content": request.user_prompt}
        ]

        if config.provider == "google":
            model_name = f"gemini/{config.model}"
        elif config.provider == "anthropic":
            model_name = f"anthropic/{config.model}"
        elif config.provider == "xai":
            model_name = f"xai/{config.model}"
        else:
            model_name = config.model

        start_time = time.time()
        timeout = int(os.environ.get("AI_ENGINE_RESPONSE_TIMEOUT_SECONDS", 120))

        litellm_response = litellm.completion(
            model=model_name,
            messages=messages,
            temperature=request.temperature,
            max_tokens=config.max_tokens,
            timeout=timeout
        )

        latency_ms = int((time.time() - start_time) * 1000)

        input_tokens = getattr(litellm_response.usage, "prompt_tokens", 0)
        output_tokens = getattr(litellm_response.usage, "completion_tokens", 0)

        return AIResponse(
            content=litellm_response.choices[0].message.content,
            metadata=AIMetadata(
                tier_used=0,
                provider=config.provider,
                model=config.model,
                fallback_triggered=False,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens
            ),
            success=True
        )


    def generate_embedding(self, text: str) -> list[float]:
        """
        Generates a vector embedding for the given text.
        Primary: Google (gemini/text-embedding-004)
        Fallback: xAI (xai/v1/embeddings) or litellm supported embedding.
        """
        timeout = int(os.environ.get("AI_ENGINE_RESPONSE_TIMEOUT_SECONDS", 120))

        # We define a simple fallback chain for embeddings.
        models_to_try = [
            ("google", "gemini/text-embedding-004"),
            ("xai", "xai/v1/embeddings")
        ]

        last_error = None

        for provider, model_name in models_to_try:
            try:
                response = litellm.embedding(
                    model=model_name,
                    input=[text],
                    timeout=timeout
                )
                return response.data[0]["embedding"]
            except Exception as e:
                logger.warning(f"Embedding failed for {provider}/{model_name}: {e}")
                last_error = e

        logger.critical(f"All embedding tiers exhausted.")
        raise AIEngineExhaustedError(f"All embedding tiers exhausted. Last error: {last_error}")

engine = AIEngine()
