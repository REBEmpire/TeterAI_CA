import pytest
from unittest.mock import patch, MagicMock
import sys, os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_kg_client():
    client = MagicMock()
    client.document_exists.return_value = False
    return client


def _make_drive_service(files=None, folder_map=None):
    drive = MagicMock()
    drive.list_folder_files.return_value = files or []
    drive.get_folder_id.side_effect = lambda pid, path: (folder_map or {}).get(path)
    drive.download_file.return_value = (b"", "application/octet-stream")
    return drive


def _make_ai_engine():
    ai = MagicMock()
    ai.generate_response.return_value.content = (
        '{"doc_number": "RFI-001", "contractor_name": "Turner Construction", '
        '"date_submitted": "2026-01-15", "date_responded": null, '
        '"summary": "Contractor queries concrete mix design for footing F-1.", '
        '"spec_sections": ["03 30 00"], '
        '"parties": [{"name": "Turner Construction", "type": "contractor"}]}'
    )
    ai.generate_embedding.return_value = [0.1] * 768
    return ai


# ---------------------------------------------------------------------------
# infer_doc_type
# ---------------------------------------------------------------------------

def test_infer_doc_type_rfi():
    from knowledge_graph.ingestion import infer_doc_type
    assert infer_doc_type("02 - Construction/RFIs") == "RFI"


def test_infer_doc_type_submittal():
    from knowledge_graph.ingestion import infer_doc_type
    assert infer_doc_type("02 - Construction/Submittals") == "SUBMITTAL"


def test_infer_doc_type_unknown():
    from knowledge_graph.ingestion import infer_doc_type
    assert infer_doc_type("02 - Construction/Punchlist") == "UNKNOWN"


def test_infer_doc_type_bid_rfi():
    from knowledge_graph.ingestion import infer_doc_type
    assert infer_doc_type("01 - Bid Phase/PB-RFIs") == "PB_RFI"


# ---------------------------------------------------------------------------
# extract_text
# ---------------------------------------------------------------------------

def test_extract_text_from_plain_text():
    from knowledge_graph.ingestion import extract_text
    content, metadata_only = extract_text(b"Hello world", "text/plain")
    assert "Hello world" in content
    assert metadata_only is False


def test_extract_text_unknown_type_returns_metadata_only():
    from knowledge_graph.ingestion import extract_text
    content, metadata_only = extract_text(b"\x00\x01\x02", "image/jpeg")
    assert metadata_only is True


def test_extract_text_pdf_too_short_returns_metadata_only():
    """A PDF that yields < 50 chars of text triggers metadata_only=True."""
    import io
    import pypdf
    from knowledge_graph.ingestion import extract_text

    # Build a minimal valid PDF with no extractable text
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()

    content, metadata_only = extract_text(pdf_bytes, "application/pdf")
    assert metadata_only is True


def test_extract_text_docx():
    """DOCX extraction returns text content and metadata_only=False."""
    import io
    from docx import Document as DocxDocument
    from knowledge_graph.ingestion import extract_text

    doc = DocxDocument()
    doc.add_paragraph("This is a test paragraph from a DOCX file.")
    buf = io.BytesIO()
    doc.save(buf)
    docx_bytes = buf.getvalue()

    content, metadata_only = extract_text(
        docx_bytes,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "test paragraph" in content
    assert metadata_only is False


# ---------------------------------------------------------------------------
# DriveToKGIngester.ingest_project
# ---------------------------------------------------------------------------

@patch('knowledge_graph.ingestion.KnowledgeGraphClient')
@patch('knowledge_graph.ingestion.DriveService')
@patch('knowledge_graph.ingestion.engine')
def test_ingest_project_skips_existing_doc(mock_engine, mock_drive_cls, mock_kg_cls):
    """If document_exists returns True the file is silently skipped."""
    from knowledge_graph.ingestion import DriveToKGIngester

    kg = _make_kg_client()
    kg.document_exists.return_value = True  # already in graph
    kg.document_is_metadata_only.return_value = False
    mock_kg_cls.return_value = kg

    drive = _make_drive_service(
        files=[{"id": "file-abc", "name": "RFI-001.pdf", "mimeType": "application/pdf"}],
        folder_map={"02 - Construction/RFIs": "folder-rfi-id"},
    )
    mock_drive_cls.return_value = drive

    ingester = DriveToKGIngester()
    result = ingester.ingest_project("11900", folder_map={"02 - Construction/RFIs": "folder-rfi-id"})

    kg.upsert_document.assert_not_called()
    assert result["skipped"] == 1


@patch('knowledge_graph.ingestion.KnowledgeGraphClient')
@patch('knowledge_graph.ingestion.DriveService')
@patch('knowledge_graph.ingestion.engine')
def test_ingest_project_writes_new_doc(mock_engine, mock_drive_cls, mock_kg_cls):
    """A new PDF file with extractable text is written to the graph."""
    import io, pypdf
    from knowledge_graph.ingestion import DriveToKGIngester

    # Build a PDF with actual text
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()

    kg = _make_kg_client()
    mock_kg_cls.return_value = kg

    drive = _make_drive_service(
        files=[{"id": "file-xyz", "name": "RFI-001.pdf", "mimeType": "application/pdf"}],
        folder_map={"02 - Construction/RFIs": "folder-rfi-id"},
    )
    drive.download_file.return_value = (pdf_bytes, "application/pdf")
    mock_drive_cls.return_value = drive

    mock_engine.generate_response.return_value.content = (
        '{"doc_number": "RFI-001", "contractor_name": "ACME Corp", '
        '"date_submitted": "2026-01-10", "date_responded": null, '
        '"summary": "Query about rebar spacing in footing.", '
        '"spec_sections": ["03 30 00"], '
        '"parties": [{"name": "ACME Corp", "type": "contractor"}]}'
    )
    mock_engine.generate_embedding.return_value = [0.1] * 768

    with patch('knowledge_graph.ingestion.extract_text', return_value=("Some RFI text content here for testing.", False)):
        ingester = DriveToKGIngester()
        result = ingester.ingest_project("11900", folder_map={"02 - Construction/RFIs": "folder-rfi-id"})

    kg.upsert_document.assert_called_once()
    assert result["written"] == 1
    assert result["errors"] == 0


@patch('knowledge_graph.ingestion.KnowledgeGraphClient')
@patch('knowledge_graph.ingestion.DriveService')
@patch('knowledge_graph.ingestion.engine')
def test_ingest_project_handles_ai_parse_error(mock_engine, mock_drive_cls, mock_kg_cls):
    """If AI returns invalid JSON, document is still written as metadata_only."""
    from knowledge_graph.ingestion import DriveToKGIngester

    kg = _make_kg_client()
    mock_kg_cls.return_value = kg

    drive = _make_drive_service(
        files=[{"id": "file-err", "name": "RFI-002.pdf", "mimeType": "application/pdf"}],
        folder_map={"02 - Construction/RFIs": "folder-rfi-id"},
    )
    drive.download_file.return_value = (b"pdf bytes", "application/pdf")
    mock_drive_cls.return_value = drive

    mock_engine.generate_response.return_value.content = "NOT VALID JSON {{{"
    mock_engine.generate_embedding.return_value = [0.1] * 768

    with patch('knowledge_graph.ingestion.extract_text', return_value=("Some long enough text string here that is definitely longer than fifty chars.", False)):
        ingester = DriveToKGIngester()
        result = ingester.ingest_project("11900", folder_map={"02 - Construction/RFIs": "folder-rfi-id"})

    # Still written, but as metadata_only=True
    kg.upsert_document.assert_called_once()
    call_kwargs = kg.upsert_document.call_args
    doc_data = call_kwargs[0][0]
    assert doc_data["metadata_only"] is True
