import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.workflow.models import TaskStatus, TriggerType, Urgency
from src.workflow.router import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.stale_processing_timeout_minutes = 10
    engine.high_urgency_review_hours = 24
    engine.medium_urgency_review_hours = 48
    engine._db = MagicMock()
    engine._now.return_value = datetime.now(timezone.utc)
    return engine

def test_queue_review_sweeps_stale_tasks(mock_engine):
    from src.workflow.router import get_workflow_engine
    app.dependency_overrides[get_workflow_engine] = lambda: mock_engine

    mock_db = mock_engine._db

    mock_doc = MagicMock()
    mock_doc.id = "task-stale"

    # We need to simulate only the classifying and processing tasks returning our stale doc
    def side_effect(field, op, val):
        mock = MagicMock()
        if field == "status" and val in [TaskStatus.CLASSIFYING.value, TaskStatus.PROCESSING.value]:
            m2 = MagicMock()
            m2.stream.return_value = [mock_doc]
            mock.where.return_value = m2
        else:
            if field == "status":
                m2 = MagicMock()
                m2.where.return_value.stream.return_value = []
                return m2
            mock.stream.return_value = []
        return mock

    mock_db.collection.return_value.where.side_effect = side_effect

    response = client.post("/queue-review")

    assert response.status_code == 200
    data = response.json()
    assert data["stale_tasks_flagged"] == 2  # CLASSIFYING + PROCESSING

def test_queue_review_requeues_rejected(mock_engine):
    from src.workflow.router import get_workflow_engine
    app.dependency_overrides[get_workflow_engine] = lambda: mock_engine

    mock_db = mock_engine._db

    mock_doc = MagicMock()
    mock_doc.id = "task-rejected"

    # We need specific behavior based on where clauses to simulate rejected only
    def side_effect(field, op, val):
        mock = MagicMock()
        if field == "status" and val == TaskStatus.REJECTED.value:
            mock.stream.return_value = [mock_doc]
        else:
            if field == "status":
                m2 = MagicMock()
                m2.where.return_value.stream.return_value = []
                return m2
            mock.stream.return_value = []
        return mock

    mock_db.collection.return_value.where.side_effect = side_effect

    response = client.post("/queue-review")

    assert response.status_code == 200
    data = response.json()
    assert data["rejected_tasks_requeued"] == 1
