import pytest
from unittest.mock import patch, MagicMock

from ai_engine.models import AIRequest, CapabilityClass, AIEngineExhaustedError
from ai_engine.engine import AIEngine

@pytest.fixture
def test_request():
    return AIRequest(
        capability_class=CapabilityClass.CLASSIFY,
        system_prompt="You are a classifier. Respond with exactly one word: INVOICE, RFI, or OTHER.",
        user_prompt="Please find the attached invoice for services rendered in March.",
        calling_agent="test_agent",
        task_id="test_task_123"
    )

def test_ai_engine_live_call(test_request):
    engine = AIEngine()
    response = engine.generate_response(test_request)

    assert response.success is True
    assert response.metadata.tier_used >= 1
    assert "INVOICE" in response.content.upper()
    assert response.metadata.latency_ms > 0
    assert response.metadata.input_tokens > 0

@patch('litellm.completion')
def test_fallback_logic(mock_completion, test_request):
    engine = AIEngine()

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "INVOICE"
    mock_response.usage.prompt_tokens = 10
    mock_response.usage.completion_tokens = 2

    mock_completion.side_effect = [
        Exception("Anthropic rate limit"),
        Exception("Google timeout"),
        mock_response
    ]

    response = engine.generate_response(test_request)

    assert mock_completion.call_count == 3

    assert response.success is True
    assert response.metadata.tier_used == 3
    assert response.metadata.fallback_triggered is True
    assert response.content == "INVOICE"

@patch('litellm.completion')
def test_all_tiers_exhausted(mock_completion, test_request):
    engine = AIEngine()

    mock_completion.side_effect = Exception("API down")

    with pytest.raises(AIEngineExhaustedError):
        engine.generate_response(test_request)

    assert mock_completion.call_count == 3
