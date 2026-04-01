"""
AI Engine — the single gateway for all LLM calls in TeterAI_CA.

Architecture
------------
Every AI call goes through ``AIEngine.generate_response(AIRequest)``.  The engine
looks up the requested ``CapabilityClass`` in the model registry (Firestore-backed,
falls back to ``default_registry.json``), then iterates through up to three tiers:

  Tier 1 → Tier 2 → Tier 3

Before falling through to the next tier the engine retries the current tier up to
``_TIER_MAX_RETRIES`` times (default 2) with exponential back-off + jitter.  This
keeps expensive fallback models as a true last resort rather than being triggered by
transient 503s or rate-limit spikes.

Rate Limiting
-------------
An optional token-bucket rate limiter (``_TokenBucket``) controls total RPM across
all calls in a process.  Set ``AI_ENGINE_RATE_LIMIT_RPM`` env var to enable it.
Default 0 = disabled (recommended when already managed by per-model quotas).

Key Classes / Functions
-----------------------
- ``AIEngine``                   – main engine class (singleton ``engine`` at module bottom)
- ``generate_response()``        – primary entry point for text generation
- ``generate_embedding()``       – Vertex AI text-embedding-004 (768-dim)
- ``generate_all_models()``      – parallel multi-model calls (used by SubmittalReviewAgent)
- ``_is_retryable(exc)``         – True for 429/500/502/503/504, ServiceUnavailable, etc.
- ``_TokenBucket``               – thread-safe token bucket rate limiter

Environment Variables
---------------------
AI_ENGINE_RATE_LIMIT_RPM        Max AI calls per minute (0 = disabled, default 0)
AI_ENGINE_TIER_MAX_RETRIES      Per-tier retry attempts before fallthrough (default 2)
AI_ENGINE_TIER_RETRY_BASE_DELAY Base delay seconds for retry back-off (default 1.5)
"""
import os
import time
import random
import logging
import threading
import litellm
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# ---------------------------------------------------------------------------
# Retry config — applied per-tier before falling through to the next tier
# ---------------------------------------------------------------------------
_TIER_MAX_RETRIES = int(os.environ.get("AI_ENGINE_TIER_MAX_RETRIES", "2"))
_TIER_RETRY_BASE_DELAY = float(os.environ.get("AI_ENGINE_TIER_RETRY_BASE_DELAY", "1.5"))  # seconds
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# ---------------------------------------------------------------------------
# Token-bucket rate limiter (shared across all engine calls in a process)
# ---------------------------------------------------------------------------
_RATE_LIMIT_RPM = int(os.environ.get("AI_ENGINE_RATE_LIMIT_RPM", "0"))  # 0 = disabled


class _TokenBucket:
    """Thread-safe token bucket rate limiter."""

    def __init__(self, rpm: int):
        self._rpm = rpm
        self._tokens = float(rpm)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self):
        """Block until a token is available."""
        if self._rpm <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(
                    self._rpm,
                    self._tokens + elapsed * (self._rpm / 60.0),
                )
                self._last_refill = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            time.sleep(0.1)


_rate_limiter = _TokenBucket(_RATE_LIMIT_RPM)


def _is_retryable(exc: Exception) -> bool:
    """Return True if this exception should trigger a same-tier retry."""
    msg = str(exc).lower()
    if any(str(code) in msg for code in _RETRYABLE_STATUS_CODES):
        return True
    # litellm wraps these as ServiceUnavailableError / RateLimitError
    retryable_types = (
        "serviceunavailableerror",
        "ratelimiterror",
        "timeout",
        "overloaded",
    )
    return any(t in type(exc).__name__.lower() or t in msg for t in retryable_types)


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
            model_label = f"Tier {tier_num} ({tier_config.provider}/{tier_config.model})"
            if tier_num > 1:
                fallback_triggered = True
                logger.warning(f"Fallback triggered: attempting {model_label}")

            # Per-tier retry loop with exponential backoff + jitter
            for attempt in range(1, _TIER_MAX_RETRIES + 2):  # +2: attempts 1..N+1
                try:
                    _rate_limiter.acquire()
                    response = self._call_model(request, tier_config)

                    response.metadata.tier_used = tier_num
                    response.metadata.fallback_triggered = fallback_triggered

                    try:
                        from audit.logger import audit_logger
                        from audit.models import AICallLog
                        audit_logger.log(AICallLog(
                            ai_call_id=response.metadata.ai_call_id,
                            task_id=request.task_id,
                            calling_agent=request.calling_agent,
                            capability_class=request.capability_class.value,
                            tier_used=response.metadata.tier_used,
                            provider=response.metadata.provider,
                            model=response.metadata.model,
                            fallback_triggered=response.metadata.fallback_triggered,
                            input_tokens=response.metadata.input_tokens,
                            output_tokens=response.metadata.output_tokens,
                            latency_ms=response.metadata.latency_ms,
                            status="SUCCESS",
                        ))
                    except Exception:
                        pass  # audit failure must never interrupt AI calls

                    return response

                except Exception as e:
                    last_error = e
                    is_last_attempt = attempt > _TIER_MAX_RETRIES
                    if _is_retryable(e) and not is_last_attempt:
                        delay = _TIER_RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 1)
                        logger.warning(
                            f"{model_label} attempt {attempt} failed (retryable): {type(e).__name__}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(f"{model_label} failed: {e}")
                        break  # move to next tier

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


    def generate_all_models(self, request: "AIRequest") -> dict[int, "AIResponse | Exception"]:
        """
        Call all configured tiers in parallel (not as fallback).
        Returns a dict keyed by tier number (1, 2, 3) with either an AIResponse or an Exception.
        Used by the Submittal Review Agent to get all model outputs for comparison.
        """
        registry = self._get_registry()

        if request.capability_class not in registry.capability_classes:
            raise InvalidCapabilityClassError(
                f"Capability class {request.capability_class} not found in registry."
            )

        config = registry.capability_classes[request.capability_class]

        tiers: list[tuple[int, object]] = []
        if config.tier_1: tiers.append((1, config.tier_1))
        if config.tier_2: tiers.append((2, config.tier_2))
        if config.tier_3: tiers.append((3, config.tier_3))

        if not tiers:
            raise RuntimeError(f"No model tiers configured for {request.capability_class}")

        results: dict[int, object] = {}

        def _call_tier(tier_num: int, tier_config) -> tuple[int, object]:
            try:
                response = self._call_model(request, tier_config)
                response.metadata.tier_used = tier_num
                response.metadata.fallback_triggered = False
                try:
                    from audit.logger import audit_logger
                    from audit.models import AICallLog
                    audit_logger.log(AICallLog(
                        ai_call_id=response.metadata.ai_call_id,
                        task_id=request.task_id,
                        calling_agent=request.calling_agent,
                        capability_class=request.capability_class.value,
                        tier_used=tier_num,
                        provider=response.metadata.provider,
                        model=response.metadata.model,
                        fallback_triggered=False,
                        input_tokens=response.metadata.input_tokens,
                        output_tokens=response.metadata.output_tokens,
                        latency_ms=response.metadata.latency_ms,
                        status="SUCCESS",
                    ))
                except Exception:
                    pass
                return tier_num, response
            except Exception as e:
                logger.error(f"Tier {tier_num} failed in generate_all_models: {e}")
                return tier_num, e

        with ThreadPoolExecutor(max_workers=len(tiers)) as executor:
            futures = {executor.submit(_call_tier, tn, tc): tn for tn, tc in tiers}
            for future in as_completed(futures):
                tier_num, result = future.result()
                results[tier_num] = result

        return results

    def generate_embedding(self, text: str) -> list[float]:
        """
        Generates a vector embedding for the given text.
        Primary: Google (vertex_ai/text-embedding-004)
        Fallback 1: Google (gemini/gemini-embedding-2-preview)
        Fallback 2: xAI (xai/v1/embeddings) or litellm supported embedding.
        """
        timeout = int(os.environ.get("AI_ENGINE_RESPONSE_TIMEOUT_SECONDS", 120))

        # We define a simple fallback chain for embeddings.
        models_to_try = [
            ("google", "vertex_ai/text-embedding-004"),
            ("google", "gemini/gemini-embedding-2-preview"),
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
