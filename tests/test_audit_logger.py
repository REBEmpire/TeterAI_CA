"""
Audit Logger Tests
==================
Unit tests (mocked) — these pass without network access.

Tests cover:
- Writing all 5 log entry types to Firestore
- Task index (audit_logs_by_task) updates
- Fail-silent behavior on Firestore errors
- Query methods: get_task_timeline, get_agent_activity, get_reviewer_history
- AI Engine integration: AI_CALL log emitted per generate_response()
- Dispatcher Agent integration: AGENT_ACTION + SYSTEM_EVENT + ERROR logs
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call

import pytest

from audit.models import (
    AgentActionLog,
    AICallLog,
    ErrorLog,
    ErrorSeverity,
    HumanReviewAction,
    HumanReviewLog,
    LogType,
    SystemEventLog,
    ThoughtChain,
)
from audit.logger import AuditLogger, _deserialize_entry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_mock_gcp(firestore_available=True):
    gcp = MagicMock()
    if firestore_available:
        gcp.firestore_client = MagicMock()
    else:
        gcp.firestore_client = None
    return gcp


def make_audit_logger(firestore_available=True):
    gcp = make_mock_gcp(firestore_available)
    return AuditLogger(gcp), gcp


# ---------------------------------------------------------------------------
# Model construction tests
# ---------------------------------------------------------------------------

class TestAuditModels:
    def test_agent_action_log_defaults(self):
        entry = AgentActionLog(
            agent_id="AGENT-TEST",
            task_id="TASK-001",
            action="TEST_ACTION",
            input_summary="input",
            output_summary="output",
            duration_ms=100,
            status="SUCCESS",
        )
        assert entry.log_type == LogType.AGENT_ACTION
        assert entry.log_id  # auto-generated uuid
        assert entry.timestamp is not None
        assert entry.ai_call_ids == []

    def test_ai_call_log_fields(self):
        entry = AICallLog(
            ai_call_id="aicall-123",
            task_id="TASK-001",
            calling_agent="AGENT-TEST",
            capability_class="CLASSIFY",
            tier_used=1,
            provider="google",
            model="gemini-2.5-flash",
            fallback_triggered=False,
            input_tokens=500,
            output_tokens=100,
            latency_ms=800,
            status="SUCCESS",
        )
        assert entry.log_type == LogType.AI_CALL
        assert entry.provider == "google"

    def test_human_review_log_fields(self):
        entry = HumanReviewLog(
            task_id="TASK-001",
            reviewer_uid="uid-staff1",
            reviewer_name="Jane Smith",
            action=HumanReviewAction.APPROVED,
            original_draft_version="v1",
            edits_made=False,
            duration_seconds=120,
            delivery_triggered=True,
        )
        assert entry.log_type == LogType.HUMAN_REVIEW
        assert entry.action == HumanReviewAction.APPROVED

    def test_system_event_log_fields(self):
        entry = SystemEventLog(
            event="EMAIL_POLL_COMPLETED",
            component="AGENT-DISPATCH-001",
            details={"tasks_created": 3},
            status="SUCCESS",
        )
        assert entry.log_type == LogType.SYSTEM_EVENT
        assert entry.details["tasks_created"] == 3

    def test_error_log_optional_task_id(self):
        entry = ErrorLog(
            component="AI_ENGINE",
            error_code="TIMEOUT",
            error_message="Request timed out",
            severity=ErrorSeverity.WARNING,
        )
        assert entry.log_type == LogType.ERROR
        assert entry.task_id is None


# ---------------------------------------------------------------------------
# AuditLogger.log() tests
# ---------------------------------------------------------------------------

class TestAuditLoggerWrite:
    def test_log_agent_action_writes_to_firestore(self):
        audit, gcp = make_audit_logger()
        entry = AgentActionLog(
            agent_id="AGENT-TEST",
            task_id="TASK-001",
            action="CLASSIFY_AND_ROUTE",
            input_summary="test input",
            output_summary="test output",
            duration_ms=500,
            status="SUCCESS",
        )
        returned_id = audit.log(entry)

        assert returned_id == entry.log_id
        # collection() is called for audit_logs and audit_logs_by_task
        collection_calls = [c[0][0] for c in gcp.firestore_client.collection.call_args_list]
        assert "audit_logs" in collection_calls
        # document() is called at least once with the log_id
        doc_calls = [c[0][0] for c in gcp.firestore_client.collection().document.call_args_list]
        assert entry.log_id in doc_calls

    def test_log_ai_call_writes_correct_fields(self):
        audit, gcp = make_audit_logger()
        entry = AICallLog(
            ai_call_id="aicall-xyz",
            task_id="TASK-002",
            calling_agent="AGENT-RFI-001",
            capability_class="REASON_DEEP",
            tier_used=1,
            provider="anthropic",
            model="claude-opus-4-6",
            fallback_triggered=False,
            input_tokens=3200,
            output_tokens=512,
            latency_ms=1842,
            status="SUCCESS",
        )
        audit.log(entry)

        # First set() call is the audit_logs write; second is audit_logs_by_task
        set_calls = gcp.firestore_client.collection().document().set.call_args_list
        set_call_args = set_calls[0][0][0]
        assert set_call_args["log_type"] == "AI_CALL"
        assert set_call_args["ai_call_id"] == "aicall-xyz"
        assert set_call_args["provider"] == "anthropic"
        assert set_call_args["tier_used"] == 1

    def test_log_updates_task_index(self):
        audit, gcp = make_audit_logger()
        entry = AgentActionLog(
            agent_id="AGENT-TEST",
            task_id="TASK-001",
            action="TEST",
            input_summary="in",
            output_summary="out",
            duration_ms=100,
            status="SUCCESS",
        )
        audit.log(entry)

        # Should have called audit_logs_by_task collection
        calls = [str(c) for c in gcp.firestore_client.collection.call_args_list]
        assert any("audit_logs_by_task" in c for c in calls)

    def test_log_no_task_index_when_no_task_id(self):
        audit, gcp = make_audit_logger()
        entry = ErrorLog(
            component="AI_ENGINE",
            error_code="TIMEOUT",
            error_message="timed out",
            severity=ErrorSeverity.WARNING,
        )
        audit.log(entry)

        # Should NOT call audit_logs_by_task since task_id is None
        calls = [str(c) for c in gcp.firestore_client.collection.call_args_list]
        assert not any("audit_logs_by_task" in c for c in calls)

    def test_log_fails_silently_on_firestore_error(self):
        audit, gcp = make_audit_logger()
        gcp.firestore_client.collection.side_effect = Exception("Firestore unavailable")

        entry = SystemEventLog(
            event="TEST_EVENT",
            component="TEST",
            status="SUCCESS",
        )
        # Must not raise
        returned_id = audit.log(entry)
        assert returned_id == entry.log_id

    def test_log_returns_log_id_when_firestore_unavailable(self):
        audit, gcp = make_audit_logger(firestore_available=False)
        entry = SystemEventLog(
            event="TEST_EVENT",
            component="TEST",
            status="SUCCESS",
        )
        returned_id = audit.log(entry)
        assert returned_id == entry.log_id

    def test_log_human_review(self):
        audit, gcp = make_audit_logger()
        entry = HumanReviewLog(
            task_id="TASK-003",
            reviewer_uid="uid-staff1",
            reviewer_name="Jane Smith",
            action=HumanReviewAction.EDITED_AND_APPROVED,
            original_draft_version="v1",
            edits_made=True,
            edit_summary="Fixed spec citation",
            correction_type="citation",
            duration_seconds=142,
            delivery_triggered=True,
        )
        audit.log(entry)

        set_calls = gcp.firestore_client.collection().document().set.call_args_list
        set_call_args = set_calls[0][0][0]
        assert set_call_args["log_type"] == "HUMAN_REVIEW"
        assert set_call_args["reviewer_uid"] == "uid-staff1"
        assert set_call_args["edits_made"] is True

    def test_log_error_with_task_id(self):
        audit, gcp = make_audit_logger()
        entry = ErrorLog(
            component="AGENT-DISPATCH-001",
            task_id="TASK-004",
            error_code="AI_ENGINE_EXHAUSTED",
            error_message="All tiers failed",
            severity=ErrorSeverity.ERROR,
        )
        audit.log(entry)

        set_calls = gcp.firestore_client.collection().document().set.call_args_list
        set_call_args = set_calls[0][0][0]
        assert set_call_args["error_code"] == "AI_ENGINE_EXHAUSTED"
        assert set_call_args["severity"] == "ERROR"


# ---------------------------------------------------------------------------
# Query method tests
# ---------------------------------------------------------------------------

class TestAuditLoggerQueries:
    def _make_firestore_doc(self, data: dict) -> MagicMock:
        doc = MagicMock()
        doc.to_dict.return_value = data
        return doc

    def _make_entry_data(self, log_type, task_id="TASK-001", **extra):
        base = {
            "log_id": "some-uuid",
            "log_type": log_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        base.update(extra)
        if task_id:
            base["task_id"] = task_id
        return base

    def test_get_task_timeline_returns_entries(self):
        audit, gcp = make_audit_logger()

        doc1_data = self._make_entry_data(
            "AGENT_ACTION",
            task_id="TASK-001",
            agent_id="AGENT-TEST",
            action="CLASSIFY_AND_ROUTE",
            input_summary="in",
            output_summary="out",
            duration_ms=100,
            status="SUCCESS",
            ai_call_ids=[],
        )
        doc2_data = self._make_entry_data(
            "SYSTEM_EVENT",
            task_id="TASK-001",
            event="EMAIL_POLL_COMPLETED",
            component="AGENT-DISPATCH-001",
            details={},
            status="SUCCESS",
        )

        mock_stream = [self._make_firestore_doc(doc1_data), self._make_firestore_doc(doc2_data)]

        query = MagicMock()
        query.stream.return_value = mock_stream
        gcp.firestore_client.collection.return_value.where.return_value.order_by.return_value = query

        result = audit.get_task_timeline("TASK-001")
        assert len(result) == 2
        assert isinstance(result[0], AgentActionLog)
        assert isinstance(result[1], SystemEventLog)

    def test_get_task_timeline_returns_empty_on_error(self):
        audit, gcp = make_audit_logger()
        gcp.firestore_client.collection.side_effect = Exception("error")
        result = audit.get_task_timeline("TASK-001")
        assert result == []

    def test_get_agent_activity_filters(self):
        audit, gcp = make_audit_logger()

        doc_data = self._make_entry_data(
            "AGENT_ACTION",
            task_id="TASK-001",
            agent_id="AGENT-DISPATCH-001",
            action="CLASSIFY_AND_ROUTE",
            input_summary="in",
            output_summary="out",
            duration_ms=100,
            status="SUCCESS",
            ai_call_ids=[],
        )

        query = MagicMock()
        query.stream.return_value = [self._make_firestore_doc(doc_data)]
        (gcp.firestore_client.collection.return_value
            .where.return_value
            .where.return_value
            .where.return_value
            .order_by.return_value) = query

        since = datetime.now(timezone.utc) - timedelta(hours=1)
        result = audit.get_agent_activity("AGENT-DISPATCH-001", since)
        assert len(result) == 1
        assert isinstance(result[0], AgentActionLog)

    def test_get_reviewer_history_filters_human_review_type(self):
        audit, gcp = make_audit_logger()

        doc_data = self._make_entry_data(
            "HUMAN_REVIEW",
            task_id="TASK-001",
            reviewer_uid="uid-staff1",
            reviewer_name="Jane Smith",
            action="APPROVED",
            original_draft_version="v1",
            edits_made=False,
            duration_seconds=60,
            delivery_triggered=True,
        )

        query = MagicMock()
        query.stream.return_value = [self._make_firestore_doc(doc_data)]
        (gcp.firestore_client.collection.return_value
            .where.return_value
            .where.return_value
            .order_by.return_value) = query

        result = audit.get_reviewer_history("uid-staff1")
        assert len(result) == 1
        assert isinstance(result[0], HumanReviewLog)
        assert result[0].reviewer_uid == "uid-staff1"

    def test_get_reviewer_history_returns_empty_on_error(self):
        audit, gcp = make_audit_logger()
        gcp.firestore_client.collection.side_effect = Exception("error")
        result = audit.get_reviewer_history("uid-staff1")
        assert result == []


# ---------------------------------------------------------------------------
# Deserializer tests
# ---------------------------------------------------------------------------

class TestDeserializeEntry:
    def test_deserializes_agent_action(self):
        data = {
            "log_id": "abc",
            "log_type": "AGENT_ACTION",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_id": "AGENT-TEST",
            "task_id": "TASK-001",
            "action": "TEST",
            "input_summary": "in",
            "output_summary": "out",
            "duration_ms": 100,
            "status": "SUCCESS",
        }
        result = _deserialize_entry(data)
        assert isinstance(result, AgentActionLog)

    def test_deserializes_ai_call(self):
        data = {
            "log_id": "abc",
            "log_type": "AI_CALL",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ai_call_id": "aicall-1",
            "task_id": "TASK-001",
            "calling_agent": "AGENT",
            "capability_class": "CLASSIFY",
            "tier_used": 1,
            "provider": "google",
            "model": "gemini",
            "fallback_triggered": False,
            "input_tokens": 100,
            "output_tokens": 50,
            "latency_ms": 500,
            "status": "SUCCESS",
        }
        result = _deserialize_entry(data)
        assert isinstance(result, AICallLog)

    def test_returns_none_for_unknown_type(self):
        result = _deserialize_entry({"log_type": "UNKNOWN_TYPE"})
        assert result is None

    def test_returns_none_for_malformed_data(self):
        result = _deserialize_entry({"log_type": "AGENT_ACTION"})  # missing required fields
        assert result is None


# ---------------------------------------------------------------------------
# AI Engine integration tests
# ---------------------------------------------------------------------------

class TestAIEngineAuditIntegration:
    def test_generate_response_emits_ai_call_log(self):
        """Verify AI engine calls audit_logger.log() with AICallLog after successful response."""
        from ai_engine.models import AIRequest, AIResponse, AIMetadata, CapabilityClass, ModelRegistry, CapabilityConfig, ModelConfig

        mock_response = AIResponse(
            content='{"project_id": {"value": "2024-001", "confidence": 0.95, "reasoning": "r"}, '
                    '"phase": {"value": "construction", "confidence": 0.95, "reasoning": "r"}, '
                    '"document_type": {"value": "RFI", "confidence": 0.95, "reasoning": "r"}, '
                    '"urgency": {"value": "MEDIUM", "confidence": 0.95, "reasoning": "r"}}',
            metadata=AIMetadata(
                tier_used=1,
                provider="google",
                model="gemini-2.5-flash",
                fallback_triggered=False,
                latency_ms=500,
                input_tokens=100,
                output_tokens=50,
            ),
            success=True,
        )

        mock_registry = ModelRegistry(
            version="1.0.0",
            updated_at="2026-01-01",
            capability_classes={
                CapabilityClass.CLASSIFY: CapabilityConfig(
                    tier_1=ModelConfig(provider="google", model="gemini-2.5-flash", max_tokens=1024)
                )
            }
        )

        request = AIRequest(
            capability_class=CapabilityClass.CLASSIFY,
            system_prompt="sys",
            user_prompt="user",
            calling_agent="AGENT-TEST",
            task_id="TASK-001",
        )

        from ai_engine.engine import AIEngine

        eng = AIEngine.__new__(AIEngine)
        eng._registry_cache = mock_registry
        eng._cache_time = float("inf")
        eng._cache_ttl = 60

        with patch.object(eng, "_call_model", return_value=mock_response), \
             patch("audit.logger.audit_logger") as mock_audit:

            result = eng.generate_response(request)

        mock_audit.log.assert_called_once()
        logged_entry = mock_audit.log.call_args[0][0]
        assert isinstance(logged_entry, AICallLog)
        assert logged_entry.task_id == "TASK-001"
        assert logged_entry.calling_agent == "AGENT-TEST"
        assert logged_entry.status == "SUCCESS"


# ---------------------------------------------------------------------------
# Dispatcher Agent integration tests
# ---------------------------------------------------------------------------

class TestDispatcherAuditIntegration:
    def _make_ingest(self, ingest_id="ING-001"):
        return {
            "ingest_id": ingest_id,
            "message_id": "msg-1",
            "subject": "RFI-045 re: structural spec",
            "sender_name": "Bob Builder",
            "sender_email": "bob@example.com",
            "body_text": "Please clarify spec section 03 30 00.",
            "attachment_drive_paths": [],
            "subject_hints": {
                "doc_type_hint": "RFI",
                "doc_number_hint": "045",
                "project_number_hint": "2024-001",
                "is_reply": False,
            },
            "status": "PENDING_CLASSIFICATION",
        }

    def _make_classification(self):
        from agents.dispatcher.models import ClassificationResult, DimensionResult
        return ClassificationResult(
            project_id=DimensionResult(value="2024-001", confidence=0.95, reasoning="r"),
            phase=DimensionResult(value="construction", confidence=0.95, reasoning="r"),
            document_type=DimensionResult(value="RFI", confidence=0.95, reasoning="r"),
            urgency=DimensionResult(value="MEDIUM", confidence=0.95, reasoning="r"),
            raw_response="{}",
            ai_call_id="aicall-test-1",
        )

    def test_dispatcher_emits_agent_action_per_task(self):
        """One AGENT_ACTION audit log is emitted per successfully processed task."""
        mock_gcp = make_mock_gcp()
        mock_ai_engine = MagicMock()

        ingest = self._make_ingest()
        classification = self._make_classification()

        # Firestore returns one pending ingest
        mock_doc = MagicMock()
        mock_doc.to_dict.return_value = ingest
        mock_doc.id = "ING-001"
        mock_gcp.firestore_client.collection.return_value.where.return_value.stream.return_value = [mock_doc]

        from agents.dispatcher.agent import DispatcherAgent

        agent = DispatcherAgent(mock_gcp, mock_ai_engine)

        with patch.object(agent._classifier, "classify", return_value=classification), \
             patch("agents.dispatcher.agent.audit_logger") as mock_audit:

            agent.run()

        # Find AGENT_ACTION call
        agent_action_calls = [
            c for c in mock_audit.log.call_args_list
            if isinstance(c[0][0], AgentActionLog)
        ]
        assert len(agent_action_calls) == 1
        logged = agent_action_calls[0][0][0]
        assert logged.action == "CLASSIFY_AND_ROUTE"
        assert logged.status == "SUCCESS"
        assert "aicall-test-1" in logged.ai_call_ids

    def test_dispatcher_emits_system_event_on_completion(self):
        """SYSTEM_EVENT EMAIL_POLL_COMPLETED is emitted at end of run()."""
        mock_gcp = make_mock_gcp()
        mock_ai_engine = MagicMock()

        # No pending ingests
        mock_gcp.firestore_client.collection.return_value.where.return_value.stream.return_value = []

        from agents.dispatcher.agent import DispatcherAgent
        agent = DispatcherAgent(mock_gcp, mock_ai_engine)

        with patch("agents.dispatcher.agent.audit_logger") as mock_audit:
            agent.run()

        system_event_calls = [
            c for c in mock_audit.log.call_args_list
            if isinstance(c[0][0], SystemEventLog)
        ]
        assert len(system_event_calls) == 1
        logged = system_event_calls[0][0][0]
        assert logged.event == "EMAIL_POLL_COMPLETED"
        assert logged.details["tasks_created"] == 0

    def test_dispatcher_emits_error_log_on_ai_exhaustion(self):
        """ErrorLog is emitted when AIEngine is exhausted."""
        from ai_engine.models import AIEngineExhaustedError

        mock_gcp = make_mock_gcp()
        mock_ai_engine = MagicMock()

        ingest = self._make_ingest()
        mock_doc = MagicMock()
        mock_doc.to_dict.return_value = ingest
        mock_doc.id = "ING-001"
        mock_gcp.firestore_client.collection.return_value.where.return_value.stream.return_value = [mock_doc]

        from agents.dispatcher.agent import DispatcherAgent
        agent = DispatcherAgent(mock_gcp, mock_ai_engine)

        with patch.object(agent._classifier, "classify", side_effect=AIEngineExhaustedError("all tiers failed")), \
             patch("agents.dispatcher.agent.audit_logger") as mock_audit:

            agent.run()

        error_calls = [
            c for c in mock_audit.log.call_args_list
            if isinstance(c[0][0], ErrorLog)
        ]
        assert len(error_calls) == 1
        logged = error_calls[0][0][0]
        assert logged.error_code == "AI_ENGINE_EXHAUSTED"
        assert logged.severity == ErrorSeverity.ERROR
