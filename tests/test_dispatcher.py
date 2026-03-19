"""
Dispatcher Agent Tests
======================
Unit tests (mocked) — these pass without network access and serve as scaffolding.

⚠️  LIVE TESTING REQUIRED — the following integration tests still need to pass
    before the Dispatcher Agent is considered complete:

    pytest tests/test_dispatcher.py -v -k "live"

    - test_live_classify_rfi_email
    - test_live_classify_falls_back_to_tier2
    - test_live_agent_end_to_end
    - test_live_firestore_write_integrity

    These tests require: GCP credentials, Firestore access, and API keys loaded
    in the model registry (google-ai-key, xai-key).
"""

import json
import pytest
from unittest.mock import MagicMock, patch, call

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from agents.dispatcher.models import (
    ClassificationResult,
    DimensionResult,
    DocumentType,
    Phase,
    TaskStatus,
    ClassificationParseError,
)
from agents.dispatcher.router import DispatcherRouter
from agents.dispatcher.classifier import EmailClassifier
from agents.dispatcher.agent import DispatcherAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_classification(
    project_id_value="2024-001",
    project_id_conf=0.95,
    phase_value="construction",
    phase_conf=0.95,
    doc_type_value="RFI",
    doc_type_conf=0.95,
    urgency_value="MEDIUM",
    urgency_conf=0.95,
) -> ClassificationResult:
    return ClassificationResult(
        project_id=DimensionResult(value=project_id_value, confidence=project_id_conf, reasoning="r"),
        phase=DimensionResult(value=phase_value, confidence=phase_conf, reasoning="r"),
        document_type=DimensionResult(value=doc_type_value, confidence=doc_type_conf, reasoning="r"),
        urgency=DimensionResult(value=urgency_value, confidence=urgency_conf, reasoning="r"),
        raw_response='{"project_id": {}, "phase": {}, "document_type": {}, "urgency": {}}',
    )


def make_ingest(ingest_id="TEST-INGEST-001") -> dict:
    return {
        "ingest_id": ingest_id,
        "message_id": f"msg-{ingest_id}",
        "subject": "RFI #045 - Clarification on concrete spec",
        "sender_name": "John Contractor",
        "sender_email": "john@contractor.com",
        "body_text": "Please clarify the concrete mix design for footings on Project 2024-001.",
        "body_text_truncated": False,
        "attachment_drive_paths": [],
        "subject_hints": {
            "doc_type_hint": "RFI",
            "doc_number_hint": "045",
            "project_number_hint": "2024-001",
            "is_reply": False,
        },
        "status": "PENDING_CLASSIFICATION",
    }


# ---------------------------------------------------------------------------
# Router tests (pure logic — no mocks needed)
# ---------------------------------------------------------------------------

class TestDispatcherRouter:
    def setup_method(self):
        self.router = DispatcherRouter()

    def test_high_confidence_rfi_construction_assigns_agent(self):
        result = make_classification()
        decision = self.router.route(result)
        assert decision.action == "ASSIGN_TO_AGENT"
        assert decision.assigned_agent == "AGENT-RFI-001"
        assert decision.all_confident is True

    def test_low_confidence_project_id_escalates(self):
        result = make_classification(project_id_conf=0.45)
        decision = self.router.route(result)
        assert decision.action == "ESCALATE_TO_HUMAN"
        assert "project_id" in decision.reason
        assert decision.all_confident is False

    def test_low_confidence_phase_escalates(self):
        result = make_classification(phase_conf=0.55)
        decision = self.router.route(result)
        assert decision.action == "ESCALATE_TO_HUMAN"
        assert "phase" in decision.reason

    def test_low_confidence_doc_type_escalates(self):
        result = make_classification(doc_type_conf=0.70)
        decision = self.router.route(result)
        assert decision.action == "ESCALATE_TO_HUMAN"
        assert "document_type" in decision.reason

    def test_non_rfi_type_escalates(self):
        result = make_classification(doc_type_value="SUBMITTAL")
        decision = self.router.route(result)
        assert decision.action == "ESCALATE_TO_HUMAN"
        assert decision.assigned_agent is None

    def test_unknown_project_id_escalates_regardless_of_confidence(self):
        result = make_classification(project_id_value="UNKNOWN", project_id_conf=0.95)
        decision = self.router.route(result)
        assert decision.action == "ESCALATE_TO_HUMAN"
        assert "UNKNOWN" in decision.reason

    def test_rfi_in_bid_phase_escalates(self):
        result = make_classification(phase_value="bid")
        decision = self.router.route(result)
        assert decision.action == "ESCALATE_TO_HUMAN"
        assert "RFI/bid" in decision.reason

    def test_all_confident_submittal_escalates_no_agent(self):
        result = make_classification(doc_type_value="SUBMITTAL")
        decision = self.router.route(result)
        assert decision.action == "ESCALATE_TO_HUMAN"
        assert decision.all_confident is True  # confident but no agent configured


# ---------------------------------------------------------------------------
# Classifier tests (mock AIEngine)
# ---------------------------------------------------------------------------

class TestEmailClassifier:
    def _make_mock_engine(self, raw_json: str):
        mock_engine = MagicMock()
        mock_response = MagicMock()
        mock_response.content = raw_json
        mock_engine.generate_response.return_value = mock_response
        return mock_engine

    def test_parse_valid_json_returns_classification_result(self):
        raw = json.dumps({
            "project_id":    {"value": "2024-001", "confidence": 0.95, "reasoning": "Found in subject."},
            "phase":         {"value": "construction", "confidence": 0.92, "reasoning": "Active job site."},
            "document_type": {"value": "RFI", "confidence": 0.97, "reasoning": "Subject says RFI."},
            "urgency":       {"value": "MEDIUM", "confidence": 0.88, "reasoning": "No deadline stated."},
        })
        classifier = EmailClassifier(self._make_mock_engine(raw))
        result = classifier.classify(make_ingest())
        assert result.project_id.value == "2024-001"
        assert result.document_type.value == "RFI"
        assert result.urgency.value == "MEDIUM"
        assert result.raw_response == raw

    def test_parse_json_wrapped_in_markdown_code_fence(self):
        raw_json = json.dumps({
            "project_id":    {"value": "2024-001", "confidence": 0.91, "reasoning": "r"},
            "phase":         {"value": "construction", "confidence": 0.90, "reasoning": "r"},
            "document_type": {"value": "RFI", "confidence": 0.93, "reasoning": "r"},
            "urgency":       {"value": "LOW", "confidence": 0.85, "reasoning": "r"},
        })
        wrapped = f"```json\n{raw_json}\n```"
        classifier = EmailClassifier(self._make_mock_engine(wrapped))
        result = classifier.classify(make_ingest())
        assert result.document_type.value == "RFI"

    def test_invalid_json_raises_classification_parse_error(self):
        classifier = EmailClassifier(self._make_mock_engine("not valid json at all"))
        with pytest.raises(ClassificationParseError):
            classifier.classify(make_ingest())

    def test_missing_key_raises_classification_parse_error(self):
        raw = json.dumps({
            "project_id": {"value": "X", "confidence": 0.9, "reasoning": "r"},
            # Missing phase, document_type, urgency
        })
        classifier = EmailClassifier(self._make_mock_engine(raw))
        with pytest.raises(ClassificationParseError):
            classifier.classify(make_ingest())

    def test_empty_body_text_still_classifies(self):
        raw = json.dumps({
            "project_id":    {"value": "UNKNOWN", "confidence": 0.30, "reasoning": "No project found."},
            "phase":         {"value": "UNKNOWN",  "confidence": 0.30, "reasoning": "Cannot determine."},
            "document_type": {"value": "GENERAL",  "confidence": 0.60, "reasoning": "No doc type."},
            "urgency":       {"value": "LOW",       "confidence": 0.70, "reasoning": "Informational."},
        })
        ingest = make_ingest()
        ingest["body_text"] = None
        classifier = EmailClassifier(self._make_mock_engine(raw))
        result = classifier.classify(ingest)
        assert result.project_id.value == "UNKNOWN"


# ---------------------------------------------------------------------------
# Agent orchestrator tests (mock AIEngine + Firestore)
# ---------------------------------------------------------------------------

class TestDispatcherAgent:
    def _make_mock_gcp(self, ingest_docs: list[dict]):
        mock_gcp = MagicMock()
        mock_gcp.firestore_client = MagicMock()
        db = mock_gcp.firestore_client

        # Mock ingests query
        mock_docs = []
        for ingest in ingest_docs:
            doc = MagicMock()
            doc.id = ingest["ingest_id"]
            doc.to_dict.return_value = ingest
            mock_docs.append(doc)

        db.collection.return_value.where.return_value.stream.return_value = iter(mock_docs)
        db.collection.return_value.document.return_value.update = MagicMock()
        db.collection.return_value.document.return_value.set = MagicMock()
        return mock_gcp

    def _make_mock_engine_with_result(self, classification: ClassificationResult):
        mock_engine = MagicMock()
        raw = json.dumps({
            "project_id":    {"value": classification.project_id.value, "confidence": classification.project_id.confidence, "reasoning": "r"},
            "phase":         {"value": classification.phase.value, "confidence": classification.phase.confidence, "reasoning": "r"},
            "document_type": {"value": classification.document_type.value, "confidence": classification.document_type.confidence, "reasoning": "r"},
            "urgency":       {"value": classification.urgency.value, "confidence": classification.urgency.confidence, "reasoning": "r"},
        })
        mock_response = MagicMock()
        mock_response.content = raw
        mock_engine.generate_response.return_value = mock_response
        return mock_engine

    def test_high_confidence_rfi_creates_task_assigned_to_agent(self):
        classification = make_classification()
        mock_gcp = self._make_mock_gcp([make_ingest()])
        mock_engine = self._make_mock_engine_with_result(classification)

        agent = DispatcherAgent(mock_gcp, mock_engine)
        task_ids = agent.run()

        assert len(task_ids) == 1
        # Verify task was created via set()
        db = mock_gcp.firestore_client
        db.collection.assert_any_call("tasks")

    def test_multiple_ingests_all_processed(self):
        mock_gcp = self._make_mock_gcp([
            make_ingest("INGEST-001"),
            make_ingest("INGEST-002"),
            make_ingest("INGEST-003"),
        ])
        classification = make_classification()
        mock_engine = self._make_mock_engine_with_result(classification)

        agent = DispatcherAgent(mock_gcp, mock_engine)
        task_ids = agent.run()
        assert len(task_ids) == 3

    def test_ai_exhaustion_sets_error_state(self):
        from ai_engine.models import AIEngineExhaustedError
        mock_gcp = self._make_mock_gcp([make_ingest()])
        mock_engine = MagicMock()
        mock_engine.generate_response.side_effect = AIEngineExhaustedError("All tiers failed")

        agent = DispatcherAgent(mock_gcp, mock_engine)
        task_ids = agent.run()

        # No task_ids returned (error state, not added to processed list)
        assert task_ids == []

        # Verify ERROR update was attempted
        db = mock_gcp.firestore_client
        update_calls = db.collection.return_value.document.return_value.update.call_args_list
        error_calls = [c for c in update_calls if c.args and "ERROR" in str(c.args[0].get("status", ""))]
        assert len(error_calls) >= 1

    def test_parse_error_sets_error_state(self):
        mock_gcp = self._make_mock_gcp([make_ingest()])
        mock_engine = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "this is not json"
        mock_engine.generate_response.return_value = mock_response

        agent = DispatcherAgent(mock_gcp, mock_engine)
        task_ids = agent.run()
        assert task_ids == []

    def test_no_firestore_client_returns_empty(self):
        mock_gcp = MagicMock()
        mock_gcp.firestore_client = None
        mock_engine = MagicMock()

        agent = DispatcherAgent(mock_gcp, mock_engine)
        task_ids = agent.run()
        assert task_ids == []


# ---------------------------------------------------------------------------
# Live integration tests — require GCP credentials + API keys
# ---------------------------------------------------------------------------
# These are stubs that document what must be verified before the agent is
# considered production-ready. They are skipped unless --live flag is passed.

@pytest.mark.skip(reason="LIVE TESTING REQUIRED — needs GCP credentials and live API keys")
def test_live_classify_rfi_email():
    """
    Real email text → Gemini 2.5 Flash classifies correctly.
    Verify: response is valid JSON, confidence scores ≥ 0.80, document_type=RFI.
    """
    pass


@pytest.mark.skip(reason="LIVE TESTING REQUIRED — needs GCP credentials and live API keys")
def test_live_classify_falls_back_to_tier2():
    """
    Force Tier 1 (Gemini 2.5 Flash) failure with a bad API key env var.
    Verify: Grok 4.1 Fast Reasoning (Tier 2) succeeds, fallback_triggered=True in metadata.
    """
    pass


@pytest.mark.skip(reason="LIVE TESTING REQUIRED — needs GCP credentials and live API keys")
def test_live_agent_end_to_end():
    """
    1. Seed real Firestore email_ingests doc with status=PENDING_CLASSIFICATION
    2. Run DispatcherAgent.run()
    3. Verify tasks/ doc created with correct status and status_history
    4. Verify email_ingests doc updated to PROCESSED or ESCALATED
    """
    pass


@pytest.mark.skip(reason="LIVE TESTING REQUIRED — needs GCP credentials and live API keys")
def test_live_firestore_write_integrity():
    """
    Verify all required Task fields are written per WF-001 schema.
    Check: task_id, ingest_id, project_id, phase, document_type, urgency,
           status, classification_confidence, status_history, created_at, updated_at.
    """
    pass
