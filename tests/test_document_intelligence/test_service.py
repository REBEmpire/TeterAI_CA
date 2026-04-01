import pytest
from unittest.mock import patch, MagicMock
from document_intelligence.service import DocumentIntelligenceService
from document_intelligence.storage.chunk_store import ChunkStore


@pytest.fixture
def store(tmp_path):
    db_path = str(tmp_path / "test_service.db")
    s = ChunkStore(db_path)
    yield s
    s.close()


@pytest.fixture
def service(store):
    mock_kg = MagicMock()
    with patch("document_intelligence.service.engine") as mock_engine:
        mock_engine.generate_embedding.return_value = [0.1] * 768
        mock_engine.generate_response.return_value = MagicMock(
            content='{"summary": "Test summary"}'
        )
        svc = DocumentIntelligenceService(
            chunk_store=store,
            kg_client=mock_kg,
        )
        yield svc


class TestClassifyDocument:
    def test_spec_book_by_name(self, service):
        assert service.classify_document("Project Specifications.pdf") == "spec_book"

    def test_drawing_set_by_name(self, service):
        assert service.classify_document("Architectural Drawings.pdf") == "drawing_set"

    def test_unknown_document(self, service):
        assert service.classify_document("random.pdf") is None


class TestProcessSpecBook:
    def test_process_spec_book_creates_chunks(self, service, store):
        # Set up mock extractor
        mock_extractor = MagicMock()
        mock_extractor.get_page_count.return_value = 2
        mock_extractor.extract_pages.return_value = [
            {"page_number": 1, "text": "TOC content", "extraction_method": "pypdf", "char_count": 100, "flagged": False},
            {"page_number": 2, "text": "SECTION 09 21 16 - GYPSUM BOARD\nContent here", "extraction_method": "pypdf", "char_count": 200, "flagged": False},
        ]

        mock_bookmark = MagicMock()
        mock_bookmark.find_toc_bookmark.return_value = {"title": "TOC", "page_number": 0}

        mock_parser = MagicMock()
        mock_parser.parse_toc_lines.return_value = [
            {"section_number": "09 21 16", "title": "GYPSUM BOARD", "page_number": 2, "division": "09"},
        ]
        mock_parser.split_pages_by_sections.return_value = [
            {"section_number": "09 21 16", "title": "GYPSUM BOARD", "division": "09",
             "content": "Full section text", "page_start": 2, "page_end": 2},
        ]

        mock_validator = MagicMock()
        mock_validator.detect_page_offset.return_value = 0
        mock_validator.validate_sections.return_value = [
            {"section_number": "09 21 16", "status": "matched"},
        ]
        mock_validator.generate_report.return_value = {"total": 1, "matched": 1}

        # Inject mocks directly onto the service instance
        service._extractor = mock_extractor
        service._bookmark_parser = mock_bookmark
        service._spec_parser = mock_parser
        service._spec_validator = mock_validator

        # Patch engine at module level for the summary/embedding calls
        with patch("document_intelligence.service.engine") as mock_engine:
            mock_engine.generate_embedding.return_value = [0.1] * 768
            mock_engine.generate_response.return_value = MagicMock(
                content='{"summary": "Test summary"}'
            )

            result = service.process_document(
                project_id="11900",
                pdf_path="/specs.pdf",
                file_name="specs.pdf",
                doc_type="spec_book",
                neo4j_doc_id="11900_SPEC_abc",
            )

        assert result["status"] == "indexed"
        chunks = store.get_chunks_by_document(result["document_id"])
        assert len(chunks) == 1
        assert chunks[0]["identifier"] == "09 21 16"
