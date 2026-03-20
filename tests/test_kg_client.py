import pytest
from unittest.mock import patch, MagicMock

@pytest.fixture
def mock_driver():
    with patch('neo4j.GraphDatabase.driver') as mock_db:
        driver = MagicMock()
        mock_db.return_value = driver
        yield driver

@patch('os.environ.get')
def test_kg_client_init(mock_env, mock_driver):
    mock_env.side_effect = lambda k, default=None: "value" if k in ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"] else default
    from src.knowledge_graph.client import KnowledgeGraphClient
    client = KnowledgeGraphClient()
    assert client._driver is not None

@patch('os.environ.get')
def test_kg_get_document_workflow(mock_env, mock_driver):
    mock_env.side_effect = lambda k, default=None: "value" if k in ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"] else default
    from src.knowledge_graph.client import KnowledgeGraphClient
    client = KnowledgeGraphClient()

    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_result = MagicMock()

    mock_record1 = MagicMock()
    mock_record1.data.return_value = {"step_id": "RFI-01", "name": "Receive"}
    mock_record2 = MagicMock()
    mock_record2.data.return_value = {"step_id": "RFI-02", "name": "Review"}

    mock_result.__iter__.return_value = [mock_record1, mock_record2]
    mock_session.run.return_value = mock_result

    steps = client.get_document_workflow("RFI")
    assert len(steps) == 2
    assert steps[0]["step_id"] == "RFI-01"
    assert steps[1]["name"] == "Review"

@patch('src.knowledge_graph.client.engine.generate_embedding')
@patch('os.environ.get')
def test_kg_search_spec_sections(mock_env, mock_embed, mock_driver):
    mock_env.side_effect = lambda k, default=None: "value" if k in ["NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"] else default
    from src.knowledge_graph.client import KnowledgeGraphClient
    client = KnowledgeGraphClient()

    mock_embed.return_value = [0.1, 0.2, 0.3]

    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_result = MagicMock()

    mock_record = MagicMock()
    mock_record.data.return_value = {"csi_division": "03", "title": "Concrete"}
    mock_result.__iter__.return_value = [mock_record]
    mock_session.run.return_value = mock_result

    results = client.search_spec_sections("concrete", top_k=1)

    mock_embed.assert_called_with("concrete")
    assert len(results) == 1
    assert results[0]["title"] == "Concrete"
