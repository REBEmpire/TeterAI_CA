import sys
import os

# Ensure the src directory is in the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from ai_engine.engine import engine
from ai_engine.models import AIRequest

def verify_models():
    registry = engine._get_registry()
    if not registry:
        print("Failed to get registry.")
        return

    # Extract all unique models
    models_to_test = []
    seen = set()

    for cap_class, config in registry.capability_classes.items():
        for tier in [config.tier_1, config.tier_2, config.tier_3]:
            if tier:
                key = (tier.provider, tier.model)
                if key not in seen:
                    seen.add(key)
                    models_to_test.append(tier)

    print(f"Found {len(models_to_test)} unique models to test.")

    test_request = AIRequest(
        task_id="test_verification",
        capability_class="REASON_STANDARD",
        calling_agent="test_agent",  # Dummy, not used here
        system_prompt="You are a helpful assistant.",
        user_prompt="Say 'hello world' in 1 sentence. Nothing else."
    )

    all_success = True

    for model_config in models_to_test:
        print(f"Testing {model_config.provider} / {model_config.model}...", end=" ", flush=True)
        try:
            response = engine._call_model(test_request, model_config)
            print(f"SUCCESS (Latency: {response.metadata.latency_ms}ms, Content: {response.content.strip()[:30]}...)")
        except Exception as e:
            print(f"FAILED. Error: {e}")
            all_success = False

    if all_success:
        print("\nAll models verified successfully!")
    else:
        print("\nSome models failed verification.")
        sys.exit(1)

if __name__ == "__main__":
    verify_models()
