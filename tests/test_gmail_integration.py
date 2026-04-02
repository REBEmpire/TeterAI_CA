import pytest
from unittest.mock import MagicMock, patch
import base64
from datetime import datetime, timezone

from ai_engine.gcp import GCPIntegration
from integrations.gmail.service import GmailService
from integrations.gmail.models import ParsedEmail

@pytest.fixture
def mock_gcp():
    gcp = MagicMock(spec=GCPIntegration)
    gcp.get_secret.return_value = "dummy"
    gcp.firestore_client = MagicMock()
    return gcp

@pytest.fixture
def gmail_service(mock_gcp):
    with patch("integrations.gmail.service.build") as mock_build:
        mock_build.return_value = MagicMock()
        service = GmailService(gcp=mock_gcp)
        return service

def test_get_subject_hints(gmail_service):
    # RFI tests
    assert gmail_service._get_subject_hints("RFI 123 - Urgent") == {"doc_type_hint": "RFI", "doc_number_hint": "123"}
    assert gmail_service._get_subject_hints("RFI#045") == {"doc_type_hint": "RFI", "doc_number_hint": "045"}
    assert gmail_service._get_subject_hints("rfi-012 status") == {"doc_type_hint": "RFI", "doc_number_hint": "012"}

    # Submittal tests
    assert gmail_service._get_subject_hints("Submittal #45") == {"doc_type_hint": "SUBMITTAL", "doc_number_hint": "45"}

    # Project hint tests
    assert gmail_service._get_subject_hints("Update [2024-001]") == {"project_number_hint": "2024-001"}

    # Reply tests
    assert gmail_service._get_subject_hints("Re: Project update") == {"is_reply": "true"}

def test_parse_message(gmail_service):
    mock_payload = {
        "headers": [
            {"name": "Subject", "value": "RFI 100 [PROJ-X]"},
            {"name": "From", "value": "Test User <test@example.com>"},
            {"name": "Date", "value": "Wed, 18 Mar 2026 12:00:00 +0000"}
        ],
        "body": {
            "data": base64.urlsafe_b64encode(b"This is the body text").decode('utf-8')
        },
        "mimeType": "text/plain"
    }

    mock_msg = {
        "id": "msg123",
        "threadId": "thread123",
        "labelIds": ["UNREAD"],
        "payload": mock_payload
    }

    parsed = gmail_service.parse_message(mock_msg)

    assert parsed.message_id == "msg123"
    assert parsed.subject == "RFI 100 [PROJ-X]"
    assert parsed.sender_email == "test@example.com"
    assert parsed.sender_name == "Test User"
    assert parsed.body_text == "This is the body text"
    assert parsed.subject_hints == {"doc_type_hint": "RFI", "doc_number_hint": "100", "project_number_hint": "PROJ-X"}
    assert len(parsed.attachments) == 0

def test_is_already_processed(gmail_service, mock_gcp):
    doc_ref_mock = MagicMock()
    doc_mock = MagicMock()
    doc_mock.exists = True
    doc_ref_mock.get.return_value = doc_mock

    mock_gcp.firestore_client.collection.return_value.document.return_value = doc_ref_mock

    assert gmail_service.is_already_processed("msg123") is True
    mock_gcp.firestore_client.collection.assert_called_with("processed_emails")

@patch("integrations.gmail.service.firestore")
def test_create_ingest_record(mock_firestore, gmail_service, mock_gcp):
    parsed = ParsedEmail(
        message_id="msg123",
        thread_id="thread123",
        received_at=datetime.now(timezone.utc),
        sender_email="test@example.com",
        sender_name="Test User",
        subject="Subject",
        body_text="Body",
        subject_hints={"is_reply": "true"}
    )

    gmail_service.create_ingest_record(parsed, [{"drive_file_id": "drive/path/1.pdf"}])

    mock_gcp.firestore_client.collection.assert_called_with("email_ingests")
    doc_ref = mock_gcp.firestore_client.collection().document()
    doc_ref.set.assert_called_once()

    call_args = doc_ref.set.call_args[0][0]
    assert call_args["message_id"] == "msg123"
    assert call_args["attachment_drive_paths"] == ["drive/path/1.pdf"]
    assert call_args["status"] == "PENDING_CLASSIFICATION"
