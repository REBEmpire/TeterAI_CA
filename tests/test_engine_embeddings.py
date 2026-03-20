import pytest
from unittest.mock import patch, MagicMock

from ai_engine.engine import AIEngine
from ai_engine.models import AIEngineExhaustedError

@patch('litellm.embedding')
def test_generate_embedding_success(mock_embedding):
    engine = AIEngine()

    mock_response = MagicMock()
    mock_response.data = [{"embedding": [0.1, 0.2, 0.3]}]
    mock_embedding.return_value = mock_response

    embedding = engine.generate_embedding("test text")

    assert mock_embedding.call_count == 1
    assert mock_embedding.call_args[1]['model'] == 'vertex_ai/text-embedding-004'
    assert embedding == [0.1, 0.2, 0.3]

@patch('litellm.embedding')
def test_generate_embedding_fallback(mock_embedding):
    engine = AIEngine()

    mock_response = MagicMock()
    mock_response.data = [{"embedding": [0.4, 0.5, 0.6]}]

    # First call fails, second succeeds
    mock_embedding.side_effect = [
        Exception("Google API error"),
        mock_response
    ]

    embedding = engine.generate_embedding("test text fallback")

    assert mock_embedding.call_count == 2
    assert mock_embedding.call_args_list[0][1]['model'] == 'vertex_ai/text-embedding-004'
    assert mock_embedding.call_args_list[1][1]['model'] == 'xai/v1/embeddings'
    assert embedding == [0.4, 0.5, 0.6]

@patch('litellm.embedding')
def test_generate_embedding_exhausted(mock_embedding):
    engine = AIEngine()

    mock_embedding.side_effect = Exception("All APIs down")

    with pytest.raises(AIEngineExhaustedError):
        engine.generate_embedding("test fail")

    assert mock_embedding.call_count == 2
