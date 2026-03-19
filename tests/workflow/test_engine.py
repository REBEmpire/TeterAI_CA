import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from workflow.engine import WorkflowEngine, InvalidTransitionError
from workflow.models import TaskStatus, TriggerType, Urgency

@pytest.fixture
def mock_gcp():
    gcp = MagicMock()
    return gcp

@pytest.fixture
def mock_kg():
    return MagicMock()

def test_create_task(mock_gcp, mock_kg):
    with patch("workflow.engine.AuditLogger"):
        engine = WorkflowEngine(mock_gcp, mock_kg)

        mock_db = engine._db
        mock_doc_ref = MagicMock()
        mock_db.collection.return_value.document.return_value = mock_doc_ref

        task = engine.create_task("ingest-123")

        assert task.ingest_id == "ingest-123"
        assert task.status == TaskStatus.PENDING_CLASSIFICATION
        assert task.urgency == Urgency.LOW

        mock_db.collection.assert_called_with("tasks")
        mock_doc_ref.set.assert_called_once()
        assert mock_doc_ref.set.call_args[0][0]["status"] == "PENDING_CLASSIFICATION"

def test_transition_valid(mock_gcp, mock_kg):
    with patch("workflow.engine.AuditLogger"):
        with patch("google.cloud.firestore.transactional", lambda f: f):
            engine = WorkflowEngine(mock_gcp, mock_kg)

            mock_db = engine._db
            mock_transaction = MagicMock()
            mock_db.transaction.return_value = mock_transaction

            mock_doc_ref = MagicMock()
            mock_db.collection.return_value.document.return_value = mock_doc_ref

            mock_snapshot = MagicMock()
            mock_snapshot.exists = True
            mock_snapshot.to_dict.return_value = {
                "task_id": "task-1",
                "ingest_id": "ingest-1",
                "status": TaskStatus.PENDING_CLASSIFICATION.value,
                "urgency": Urgency.LOW.value,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "status_history": [],
                "correction_captured": False
            }
            mock_doc_ref.get.return_value = mock_snapshot

            task = engine.transition("task-1", TaskStatus.CLASSIFYING, "dispatcher", TriggerType.AGENT, "starting")

            assert task.status == TaskStatus.CLASSIFYING
            mock_transaction.update.assert_called_once()
            updated_data = mock_transaction.update.call_args[0][1]
            assert updated_data["status"] == TaskStatus.CLASSIFYING.value
            assert len(updated_data["status_history"]) == 1
            assert updated_data["status_history"][0]["to_status"] == TaskStatus.CLASSIFYING.value
            assert updated_data["status_history"][0]["notes"] == "starting"

def test_transition_invalid(mock_gcp, mock_kg):
    with patch("workflow.engine.AuditLogger"):
        with patch("google.cloud.firestore.transactional", lambda f: f):
            engine = WorkflowEngine(mock_gcp, mock_kg)

            mock_db = engine._db
            mock_transaction = MagicMock()
            mock_db.transaction.return_value = mock_transaction

            mock_doc_ref = MagicMock()
            mock_db.collection.return_value.document.return_value = mock_doc_ref

            mock_snapshot = MagicMock()
            mock_snapshot.exists = True
            mock_snapshot.to_dict.return_value = {
                "task_id": "task-1",
                "ingest_id": "ingest-1",
                "status": TaskStatus.PENDING_CLASSIFICATION.value,
                "urgency": Urgency.LOW.value,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "status_history": [],
                "correction_captured": False
            }
            mock_doc_ref.get.return_value = mock_snapshot

            with pytest.raises(InvalidTransitionError):
                engine.transition("task-1", TaskStatus.APPROVED, "human", TriggerType.HUMAN)
