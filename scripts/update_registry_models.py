import json
import sys
import os

# Ensure the src directory is in the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from ai_engine.gcp import GCPIntegration
from ai_engine.models import ModelRegistry, CapabilityConfig, ModelConfig, CapabilityClass

def update_models():
    gcp = GCPIntegration()
    if not gcp.firestore_client:
        print("Failed to initialize GCP integration.")
        return

    registry = ModelRegistry(
        version="1.2.0",
        updated_at="2026-03-18T02:00:00Z",
        capability_classes={
            CapabilityClass.REASON_DEEP: CapabilityConfig(
                tier_1=ModelConfig(provider="anthropic", model="claude-opus-4-6", max_tokens=8192),
                tier_2=ModelConfig(provider="google", model="gemini-3.1-pro-preview", max_tokens=8192),
                tier_3=ModelConfig(provider="xai", model="grok-4.20-multi-agent-beta-0309", max_tokens=8192)
            ),
            CapabilityClass.REASON_STANDARD: CapabilityConfig(
                tier_1=ModelConfig(provider="anthropic", model="claude-sonnet-4-6", max_tokens=4096),
                tier_2=ModelConfig(provider="google", model="gemini-3-flash-preview", max_tokens=4096),
                tier_3=ModelConfig(provider="xai", model="grok-4-1-fast-reasoning", max_tokens=4096)
            ),
            CapabilityClass.CLASSIFY: CapabilityConfig(
                tier_1=ModelConfig(provider="anthropic", model="claude-haiku-4-5-20251001", max_tokens=1024),
                tier_2=ModelConfig(provider="google", model="gemini-2.5-flash", max_tokens=1024),
                tier_3=ModelConfig(provider="xai", model="grok-4-1-fast-non-reasoning", max_tokens=1024)
            ),
            CapabilityClass.GENERATE_DOC: CapabilityConfig(
                tier_1=ModelConfig(provider="anthropic", model="claude-sonnet-4-6", max_tokens=8192),
                tier_2=ModelConfig(provider="google", model="gemini-3.1-pro-preview", max_tokens=8192),
                tier_3=ModelConfig(provider="xai", model="grok-4-1-fast-reasoning", max_tokens=8192)
            ),
            CapabilityClass.EXTRACT: CapabilityConfig(
                tier_1=ModelConfig(provider="anthropic", model="claude-haiku-4-5-20251001", max_tokens=2048),
                tier_2=ModelConfig(provider="google", model="gemini-3-flash-preview", max_tokens=2048),
                tier_3=ModelConfig(provider="xai", model="grok-4-1-fast-non-reasoning", max_tokens=2048)
            ),
            CapabilityClass.MULTIMODAL: CapabilityConfig(
                tier_1=ModelConfig(provider="anthropic", model="claude-opus-4-6", max_tokens=4096),
                tier_2=ModelConfig(provider="google", model="gemini-3.1-pro-preview", max_tokens=4096),
                tier_3=ModelConfig(provider="xai", model="grok-4.20-multi-agent-beta-0309", max_tokens=4096)
            )
        }
    )

    doc_ref = gcp.firestore_client.collection("ai_engine").document("model_registry")

    try:
        doc_ref.set(json.loads(registry.model_dump_json()))
        print("Updated registry with correct live models successfully!")
    except Exception as e:
        print(f"Failed to update registry: {e}")

if __name__ == "__main__":
    update_models()
