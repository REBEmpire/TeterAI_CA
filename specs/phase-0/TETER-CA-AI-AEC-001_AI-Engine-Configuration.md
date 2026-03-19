# TETER-CA-AI-AEC-001 — AI Engine Configuration

| Field | Value |
|-------|-------|
| Document ID | TETER-CA-AI-AEC-001 |
| Version | v0.1.0 |
| Status | In Progress |
| Phase | Phase 0 — Foundation |
| Last Updated | 2026-03-18 |

---

## 1. Purpose & Scope

This specification defines the AI Engine layer — the core abstraction that sits between all agents and the underlying large language model (LLM) providers. The AI Engine provides:

- A **Model Registry** mapping capability classes to specific models per provider
- **Capability Classes** that encode the nature of each AI task
- A **3-Tier Fallback Chain** ensuring high availability without service interruption
- **Hot-swap** capability to change models without redeploying agents
- **LiteLLM integration** for unified provider abstraction

All agents interact exclusively through the AI Engine; no agent calls an LLM provider directly.

**Out of scope:** Agent logic, prompt templates (owned by individual agents), billing/cost tracking (future phase).

---

## 2. Dependencies

| Dependency | Type | Notes |
|-----------|------|-------|
| LiteLLM | Python library | Unified LLM interface |
| Google Secret Manager | GCP service | Stores API keys per provider |
| TETER-CA-AI-SEC-001 | Internal spec | Secret access patterns |
| TETER-CA-AI-AUDIT-001 | Internal spec | All AI calls must be logged |

---

## 3. Architecture Overview

```
Agent
  │
  ▼
AI Engine
  ├── Capability Resolver      ← maps task type to capability class
  ├── Model Registry           ← maps capability class to model configs
  ├── Provider Selector        ← selects Tier 1 / 2 / 3 based on availability
  └── LiteLLM Client           ← unified call to Claude / Google AI / xAI
        │
        ├── Tier 1: Primary Provider
        ├── Tier 2: Secondary Provider (fallback)
        └── Tier 3: Tertiary Provider (last resort)
```

---

## 4. Capability Classes

The AI Engine defines six capability classes. Each agent specifies which class its task requires; the engine routes to the appropriate model.

| Class | Description | Typical Use |
|-------|-------------|-------------|
| `REASON_DEEP` | Complex multi-step reasoning, long context | RFI response drafting, contract analysis |
| `REASON_STANDARD` | Standard reasoning, moderate context | Response generation, summarization |
| `CLASSIFY` | Classification and routing decisions | Email classification, document type detection |
| `GENERATE_DOC` | Structured document generation | RFI logs, meeting minutes, formal letters |
| `EXTRACT` | Information extraction from documents | Parsing emails, extracting spec section numbers |
| `MULTIMODAL` | Vision + text (drawings, photos, scans) | Drawing cross-reference, submittal review |

---

## 5. Model Registry

The Model Registry is a versioned configuration (stored in Firestore collection `ai_engine/model_registry`) mapping each capability class to a prioritized list of model configurations.

### 5.1 Registry Schema

```json
{
  "version": "1.0.0",
  "updated_at": "2026-03-18T00:00:00Z",
  "capability_classes": {
    "REASON_DEEP": {
      "tier_1": { "provider": "anthropic", "model": "claude-opus-4-6", "max_tokens": 8192 },
      "tier_2": { "provider": "google", "model": "gemini-2.0-pro", "max_tokens": 8192 },
      "tier_3": { "provider": "xai", "model": "grok-3", "max_tokens": 8192 }
    },
    "REASON_STANDARD": {
      "tier_1": { "provider": "anthropic", "model": "claude-sonnet-4-6", "max_tokens": 4096 },
      "tier_2": { "provider": "google", "model": "gemini-2.0-flash", "max_tokens": 4096 },
      "tier_3": { "provider": "xai", "model": "grok-3-mini", "max_tokens": 4096 }
    },
    "CLASSIFY": {
      "tier_1": { "provider": "google", "model": "gemini-2.5-flash",        "max_tokens": 1024 },
      "tier_2": { "provider": "xai",    "model": "grok-4-1-fast-reasoning", "max_tokens": 1024 },
      "tier_3": { "provider": "google", "model": "gemini-3-flash-preview",  "max_tokens": 1024 }
    },
    "GENERATE_DOC": {
      "tier_1": { "provider": "anthropic", "model": "claude-sonnet-4-6", "max_tokens": 8192 },
      "tier_2": { "provider": "google", "model": "gemini-2.0-pro", "max_tokens": 8192 },
      "tier_3": { "provider": "xai", "model": "grok-3", "max_tokens": 8192 }
    },
    "EXTRACT": {
      "tier_1": { "provider": "anthropic", "model": "claude-haiku-4-5-20251001", "max_tokens": 2048 },
      "tier_2": { "provider": "google", "model": "gemini-2.0-flash", "max_tokens": 2048 },
      "tier_3": { "provider": "xai", "model": "grok-3-mini", "max_tokens": 2048 }
    },
    "MULTIMODAL": {
      "tier_1": { "provider": "anthropic", "model": "claude-opus-4-6", "max_tokens": 4096 },
      "tier_2": { "provider": "google", "model": "gemini-2.0-pro-vision", "max_tokens": 4096 },
      "tier_3": null
    }
  }
}
```

### 5.2 Hot-Swap Mechanism

The registry is read from Firestore on each request (cached with a 60-second TTL). To swap a model:
1. Update the Firestore document `ai_engine/model_registry`
2. Within 60 seconds, all agents are using the new model
3. No service restart required
4. Previous registry version retained as `ai_engine/model_registry_history/{timestamp}`

---

## 6. 3-Tier Fallback Chain

### 6.1 Fallback Logic

```
attempt Tier 1
  ├── success → return result
  └── failure (timeout, rate limit, error) →
        log warning + attempt Tier 2
          ├── success → return result + log fallback used
          └── failure →
                log warning + attempt Tier 3
                  ├── success → return result + log fallback used
                  └── failure → raise AIEngineExhaustedError + log critical
```

### 6.2 Failure Conditions Triggering Fallback

- HTTP 429 (rate limit)
- HTTP 5xx (provider error)
- Connection timeout (configurable, default 30s)
- Response timeout (configurable, default 120s)
- Malformed/empty response

### 6.3 Fallback Metadata

Every response includes metadata:

```json
{
  "tier_used": 1,
  "provider": "anthropic",
  "model": "claude-opus-4-6",
  "fallback_triggered": false,
  "latency_ms": 1842,
  "input_tokens": 3200,
  "output_tokens": 512
}
```

---

## 7. Interface Contract (Agent → AI Engine)

### 7.1 Request

```python
class AIRequest:
    capability_class: CapabilityClass      # e.g., CapabilityClass.REASON_DEEP
    system_prompt: str
    user_prompt: str
    attachments: list[Attachment] | None   # for MULTIMODAL only
    temperature: float = 0.2               # low for determinism
    calling_agent: str                     # agent ID for audit logging
    task_id: str                           # workflow task ID for audit trail
```

### 7.2 Response

```python
class AIResponse:
    content: str                           # model output text
    metadata: AIMetadata                   # tier_used, model, latency, tokens
    success: bool
    error: str | None
```

---

## 8. Configuration & Environment Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `ANTHROPIC_API_KEY` | Secret Manager: `ai-engine/anthropic-key` | Claude API key |
| `GOOGLE_AI_API_KEY` | Secret Manager: `ai-engine/google-ai-key` | Google AI Studio key |
| `XAI_API_KEY` | Secret Manager: `ai-engine/xai-key` | xAI/Grok API key |
| `AI_ENGINE_CACHE_TTL_SECONDS` | Env var (default: 60) | Registry cache TTL |
| `AI_ENGINE_TIER1_TIMEOUT_SECONDS` | Env var (default: 30) | Tier 1 connection timeout |
| `AI_ENGINE_RESPONSE_TIMEOUT_SECONDS` | Env var (default: 120) | Response timeout |

---

## 9. Error Handling

| Error | Behavior |
|-------|----------|
| Single tier failure | Log warning, try next tier silently |
| All tiers exhausted | Raise `AIEngineExhaustedError`, task moves to human queue with error flag |
| Registry unavailable | Fall back to last known cached registry; alert ops |
| Invalid capability class | Raise `InvalidCapabilityClassError` immediately (no fallback) |

---

## 10. Testing Requirements

- Unit: test fallback chain triggers correctly on mocked provider errors
- Unit: test registry cache TTL refresh
- Unit: test hot-swap (update registry → verify next call uses new model)
- Integration: live call to each capability class across all three providers
- Integration: verify audit log entries are written per call (per AUDIT-001)
- Load: verify fallback under sustained rate-limit simulation

---

## 11. Open Questions

| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | Should `MULTIMODAL` Tier 3 be required, or is 2-tier acceptable for Phase 0? | Tech Lead | Open |
| 2 | What is the acceptable latency SLA per capability class? | Product | Open |
| 3 | Should we implement per-agent rate limiting at the AI Engine layer? | Tech Lead | Open |

---

## 12. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v0.1.0 | 2026-03-18 | TeterAI Team | Initial draft |
