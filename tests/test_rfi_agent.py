"""
RFI Agent Tests
===============
Unit tests (mocked) — these pass without network access and serve as scaffolding.

⚠️  LIVE TESTING REQUIRED — the following integration tests still need to pass
    before the RFI Agent is considered complete:

    pytest tests/test_rfi_agent.py -v -k "live"

    - test_live_rfi_extract_from_email
    - test_live_rfi_full_pipeline_staged
    - test_live_rfi_escalate_on_low_confidence
    - test_live_rfi_thought_chains_written

    These tests require: GCP credentials, Firestore access, Neo4j, and API keys
    loaded in the model registry.
"""

import json
import pytest
from unittest.mock import MagicMock

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agents.rfi.models import (
    RFIExtraction,
    KGLookupResult,
    RFIResponse,
    RFIExtractionParseError,
)
from agents.rfi.extractor import RFIExtractor
from agents.rfi.drafter import RFIDrafter
from agents.rfi.agent import RFIAgent


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def make_mock_engine(response_content: str):
    engine = MagicMock()
    ai_resp = MagicMock()
    ai_resp.content = response_content
    engine.generate_response.return_value = ai_resp
    return engine


def make_extraction_json(**overrides) -> str:
    base = {
        "rfi_number_submitted": "045",
        "contractor_name": "ABC Contractors",
        "contractor_contact": "John Smith",
        "question": (
            "Specification Section 03 30 00 paragraph 2.3 calls for 4000 PSI concrete. "
            "Structural drawing S-101 note 3 calls for 5000 PSI. Which governs?"
        ),
        "referenced_spec_sections": ["03 30 00"],
        "referenced_drawing_sheets": ["S-101"],
        "date_submitted": "2026-03-18",
        "response_requested_by": "2026-03-28",
        "attachments_analyzed": ["RFI-045.pdf"],
    }
    base.update(overrides)
    return json.dumps(base)


def make_draft_response(confidence: float = 0.85) -> str:
    return (
        "RESPONSE:\n"
        "Per Specification Section 03 30 00, Paragraph 2.3, the minimum compressive strength "
        "is 4000 PSI. However, Structural Drawings Sheet S-101, Note 3 specifies 5000 PSI. "
        "Per AIA A201-2017, Section 1.2.1, the most stringent requirement governs; therefore "
        "the 5000 PSI requirement on the structural drawings governs.\n\n"
        "REFERENCES:\n"
        "- Specification Section 03 30 00, Paragraph 2.3 — Concrete Compressive Strength\n"
        "- Structural Drawings Sheet S-101, Note 3\n"
        "- AIA A201-2017, Section 1.2.1 — Correlation and Intent of Contract Documents\n\n"
        f"CONFIDENCE: {confidence}\n"
        "CONFIDENCE_REASONING: Clear spec and drawing citations available; conflict resolution "
        "rule applies directly."
    )


def make_ingest() -> dict:
    return {
        "ingest_id": "TEST-INGEST-001",
        "subject": "RFI #045 - Concrete PSI conflict",
        "sender_name": "John Smith",
        "sender_email": "john@abccontractors.com",
        "body_text": "Please clarify the concrete strength requirement on Project 2024-001.",
        "attachment_drive_paths": [],
        "status": "PROCESSED",
    }


def make_kg_result() -> KGLookupResult:
    return KGLookupResult(
        spec_sections=[{
            "section_number": "03 30 00",
            "title": "Cast-in-Place Concrete",
            "content_summary": "Minimum compressive strength 4000 PSI at 28 days.",
        }],
        playbook_rules=[{
            "condition": "Spec/Drawing conflict",
            "action": (
                "Cite AIA A201 Section 1.2.1 — documents are complementary; "
                "most stringent governs. Flag for CA staff review."
            ),
        }],
        workflow_steps=[],
    )


# ---------------------------------------------------------------------------
# RFIExtractor unit tests
# ---------------------------------------------------------------------------

class TestRFIExtractor:
    def test_parses_valid_response(self):
        extractor = RFIExtractor(make_mock_engine(make_extraction_json()))
        result = extractor.extract(make_ingest(), "TASK-001")
        assert result.rfi_number_submitted == "045"
        assert result.contractor_name == "ABC Contractors"
        assert result.contractor_contact == "John Smith"
        assert "03 30 00" in result.referenced_spec_sections
        assert "S-101" in result.referenced_drawing_sheets
        assert result.question != ""
        assert result.date_submitted == "2026-03-18"
        assert result.response_requested_by == "2026-03-28"

    def test_strips_markdown_fences(self):
        raw = "```json\n" + make_extraction_json() + "\n```"
        extractor = RFIExtractor(make_mock_engine(raw))
        result = extractor.extract(make_ingest(), "TASK-002")
        assert result.rfi_number_submitted == "045"

    def test_raises_on_invalid_json(self):
        extractor = RFIExtractor(make_mock_engine("this is not json"))
        with pytest.raises(RFIExtractionParseError):
            extractor.extract(make_ingest(), "TASK-003")

    def test_handles_null_optional_fields(self):
        raw = make_extraction_json(contractor_contact=None, referenced_drawing_sheets=[])
        extractor = RFIExtractor(make_mock_engine(raw))
        result = extractor.extract(make_ingest(), "TASK-004")
        assert result.contractor_contact is None
        assert result.referenced_drawing_sheets == []

    def test_unknown_rfi_number_when_absent(self):
        raw = make_extraction_json(rfi_number_submitted="UNKNOWN")
        extractor = RFIExtractor(make_mock_engine(raw))
        result = extractor.extract(make_ingest(), "TASK-005")
        assert result.rfi_number_submitted == "UNKNOWN"

    def test_raw_response_preserved(self):
        content = make_extraction_json()
        extractor = RFIExtractor(make_mock_engine(content))
        result = extractor.extract(make_ingest(), "TASK-006")
        assert result.raw_response == content


# ---------------------------------------------------------------------------
# RFIDrafter unit tests
# ---------------------------------------------------------------------------

class TestRFIDrafter:
    def _extraction(self) -> RFIExtraction:
        return RFIExtraction(
            rfi_number_submitted="045",
            contractor_name="ABC Contractors",
            question="Which concrete strength governs?",
            referenced_spec_sections=["03 30 00"],
            referenced_drawing_sheets=["S-101"],
            raw_response="{}",
        )

    def test_returns_rfi_response(self):
        drafter = RFIDrafter(make_mock_engine(make_draft_response(0.85)))
        result = drafter.draft(self._extraction(), make_kg_result(), "TASK-001")
        assert isinstance(result, RFIResponse)
        assert result.response_text != ""
        assert len(result.references) == 3
        assert result.confidence_score == pytest.approx(0.85)

    def test_high_confidence_no_flag(self):
        drafter = RFIDrafter(make_mock_engine(make_draft_response(0.90)))
        result = drafter.draft(self._extraction(), make_kg_result(), "TASK-001")
        assert result.review_flag is None

    def test_boundary_confidence_stage_threshold(self):
        drafter = RFIDrafter(make_mock_engine(make_draft_response(0.75)))
        result = drafter.draft(self._extraction(), make_kg_result(), "TASK-001")
        assert result.review_flag is None

    def test_medium_confidence_review_carefully_flag(self):
        drafter = RFIDrafter(make_mock_engine(make_draft_response(0.65)))
        result = drafter.draft(self._extraction(), make_kg_result(), "TASK-001")
        assert result.review_flag == "REVIEW_CAREFULLY"

    def test_boundary_confidence_escalate_threshold(self):
        drafter = RFIDrafter(make_mock_engine(make_draft_response(0.50)))
        result = drafter.draft(self._extraction(), make_kg_result(), "TASK-001")
        assert result.review_flag == "REVIEW_CAREFULLY"

    def test_low_confidence_escalated_flag(self):
        drafter = RFIDrafter(make_mock_engine(make_draft_response(0.40)))
        result = drafter.draft(self._extraction(), make_kg_result(), "TASK-001")
        assert result.review_flag == "ESCALATED"

    def test_header_contains_required_fields(self):
        drafter = RFIDrafter(make_mock_engine(make_draft_response(0.85)))
        result = drafter.draft(
            self._extraction(), make_kg_result(), "TASK-001",
            project_id="2024-001", rfi_number_internal="RFI-045"
        )
        assert "2024-001" in result.header
        assert "RFI-045" in result.header
        assert "Teter Architects" in result.header
        assert "ABC Contractors" in result.header

    def test_raw_response_preserved(self):
        raw = make_draft_response(0.85)
        drafter = RFIDrafter(make_mock_engine(raw))
        result = drafter.draft(self._extraction(), make_kg_result(), "TASK-001")
        assert result.raw_response == raw

    def test_empty_kg_result_still_drafts(self):
        empty_kg = KGLookupResult()
        drafter = RFIDrafter(make_mock_engine(make_draft_response(0.60)))
        result = drafter.draft(self._extraction(), empty_kg, "TASK-001")
        assert result.confidence_score == pytest.approx(0.60)


# ---------------------------------------------------------------------------
# RFIAgent unit tests
# ---------------------------------------------------------------------------

class _AgentFixture:
    """Builds a fully mocked RFIAgent for unit tests."""

    def __init__(self, extraction_json: str, draft_text: str, task_status="ASSIGNED_TO_AGENT"):
        # AI engine: first call → extractor, second call → drafter
        self.ai_engine = MagicMock()
        self.ai_engine.generate_response.side_effect = [
            MagicMock(content=extraction_json),
            MagicMock(content=draft_text),
        ]

        # KG client: return empty results (no Neo4j needed)
        self.kg_client = MagicMock()
        self.kg_client.search_spec_sections.return_value = []
        self.kg_client.get_agent_playbook.return_value = []
        self.kg_client.get_document_workflow.return_value = []

        # Firestore mock
        self.db = MagicMock()
        task_doc = MagicMock()
        task_doc.id = "TASK-RFI-001"
        task_doc.to_dict.return_value = {
            "task_id": "TASK-RFI-001",
            "ingest_id": "INGEST-001",
            "status": task_status,
            "assigned_agent": "AGENT-RFI-001",
            "project_id": "2024-001",
            "status_history": [],
        }

        # tasks query
        tasks_col = MagicMock()
        tasks_col.where.return_value.where.return_value.stream.return_value = [task_doc]

        # Per-collection routing
        task_snap = MagicMock()
        task_snap.exists = True
        task_snap.to_dict.return_value = {"status_history": []}

        ingest_snap = MagicMock()
        ingest_snap.exists = True
        ingest_snap.to_dict.return_value = make_ingest()

        counter_snap = MagicMock()
        counter_snap.to_dict.return_value = {"count": 1}
        counter_doc = MagicMock()
        counter_doc.get.return_value = counter_snap

        def col(name):
            c = MagicMock()
            if name == "tasks":
                c.where.return_value.where.return_value.stream.return_value = [task_doc]
                c.document.return_value.get.return_value = task_snap
            elif name == "email_ingests":
                c.document.return_value.get.return_value = ingest_snap
            elif name == "rfi_counters":
                c.document.return_value = counter_doc
            else:
                c.document.return_value.get.return_value = task_snap
            return c

        self.db.collection.side_effect = col

        self.gcp = MagicMock()
        self.gcp.firestore_client = self.db

    def build(self) -> RFIAgent:
        return RFIAgent(gcp=self.gcp, ai_engine=self.ai_engine, kg_client=self.kg_client)


class TestRFIAgent:
    def test_run_returns_task_id_on_success(self):
        fx = _AgentFixture(make_extraction_json(), make_draft_response(0.85))
        result = fx.build().run()
        assert result == ["TASK-RFI-001"]

    def test_run_returns_empty_when_no_tasks(self):
        gcp = MagicMock()
        db = MagicMock()
        db.collection.return_value.where.return_value.where.return_value.stream.return_value = []
        gcp.firestore_client = db
        agent = RFIAgent(gcp=gcp, ai_engine=MagicMock(), kg_client=MagicMock())
        assert agent.run() == []

    def test_run_aborts_without_firestore(self):
        gcp = MagicMock()
        gcp.firestore_client = None
        agent = RFIAgent(gcp=gcp, ai_engine=MagicMock(), kg_client=MagicMock())
        assert agent.run() == []

    def test_high_confidence_leads_to_staged_for_review(self):
        fx = _AgentFixture(make_extraction_json(), make_draft_response(0.85))
        agent = fx.build()
        # Intercept _process_task to inspect result
        results: list = []
        original = agent._process_task

        def capture(db, task_id, ingest_id, project_id):
            r = original(db, task_id, ingest_id, project_id)
            results.append(r)
            return r

        agent._process_task = capture
        agent.run()
        assert results[0].final_status == "STAGED_FOR_REVIEW"

    def test_low_confidence_leads_to_escalated(self):
        fx = _AgentFixture(make_extraction_json(), make_draft_response(0.30))
        agent = fx.build()
        results: list = []
        original = agent._process_task

        def capture(db, task_id, ingest_id, project_id):
            r = original(db, task_id, ingest_id, project_id)
            results.append(r)
            return r

        agent._process_task = capture
        agent.run()
        assert results[0].final_status == "ESCALATED_TO_HUMAN"
        assert results[0].draft is not None  # draft was attempted but not staged

    def test_extraction_failure_returns_error(self):
        fx = _AgentFixture("not json", make_draft_response(0.85))
        agent = fx.build()
        results: list = []
        original = agent._process_task

        def capture(db, task_id, ingest_id, project_id):
            r = original(db, task_id, ingest_id, project_id)
            results.append(r)
            return r

        agent._process_task = capture
        # Should not raise — errors are handled internally
        task_ids = agent.run()
        assert task_ids == ["TASK-RFI-001"]
        assert results[0].final_status == "ERROR"

    def test_missing_ingest_returns_error(self):
        fx = _AgentFixture(make_extraction_json(), make_draft_response(0.85))
        # Make ingest doc return not-exists
        ingest_snap = MagicMock()
        ingest_snap.exists = False

        def col(name):
            c = MagicMock()
            task_doc = MagicMock()
            task_doc.id = "TASK-RFI-001"
            task_doc.to_dict.return_value = {
                "task_id": "TASK-RFI-001",
                "ingest_id": "INGEST-MISSING",
                "status": "ASSIGNED_TO_AGENT",
                "assigned_agent": "AGENT-RFI-001",
                "project_id": "2024-001",
                "status_history": [],
            }
            task_snap = MagicMock()
            task_snap.exists = True
            task_snap.to_dict.return_value = {"status_history": []}
            if name == "tasks":
                c.where.return_value.where.return_value.stream.return_value = [task_doc]
                c.document.return_value.get.return_value = task_snap
            elif name == "email_ingests":
                c.document.return_value.get.return_value = ingest_snap
            else:
                c.document.return_value.get.return_value = task_snap
            return c

        fx.db.collection.side_effect = col
        results: list = []
        agent = fx.build()
        original = agent._process_task

        def capture(db, task_id, ingest_id, project_id):
            r = original(db, task_id, ingest_id, project_id)
            results.append(r)
            return r

        agent._process_task = capture
        agent.run()
        assert results[0].final_status == "ERROR"


# ---------------------------------------------------------------------------
# Live integration tests (skipped without credentials)
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="Requires live GCP credentials, Firestore, and API keys")
def test_live_rfi_extract_from_email():
    """Verify EXTRACT capability parses a real RFI email correctly."""
    pass


@pytest.mark.skip(reason="Requires live GCP credentials, Firestore, and API keys")
def test_live_rfi_full_pipeline_staged():
    """Full pipeline: seed ASSIGNED_TO_AGENT task → verify STAGED_FOR_REVIEW + rfi_log entry."""
    pass


@pytest.mark.skip(reason="Requires live GCP credentials, Firestore, and API keys")
def test_live_rfi_escalate_on_low_confidence():
    """Verify confidence < 0.50 results in ESCALATED_TO_HUMAN with no draft staged."""
    pass


@pytest.mark.skip(reason="Requires live GCP credentials, Firestore, and API keys")
def test_live_rfi_thought_chains_written():
    """Verify thought chain entries (01_extraction, 02_kg_queries, 04_draft_generation) are created."""
    pass
