"""
Tests for ChunkStore — SQLite-backed content store for Document Intelligence.
"""
import os
import tempfile
import pytest

from document_intelligence.storage.chunk_store import ChunkStore


@pytest.fixture
def store(tmp_path):
    """Create a fresh ChunkStore in a temp directory for each test."""
    db_path = str(tmp_path / "test_chunks.db")
    s = ChunkStore(db_path)
    yield s
    s.close()


# ---------------------------------------------------------------------------
# 1. register_document creates and returns a document
# ---------------------------------------------------------------------------

def test_register_document_creates_document(store):
    doc_id = store.register_document(
        project_id="proj-001",
        file_path="/docs/spec.pdf",
        file_name="spec.pdf",
        doc_type="spec_book",
        neo4j_doc_id="neo4j-abc-123",
        total_pages=50,
        file_size_bytes=1048576,
    )
    assert doc_id is not None
    assert isinstance(doc_id, str)
    assert len(doc_id) == 36  # UUID format

    doc = store.get_document(doc_id)
    assert doc is not None
    assert doc["project_id"] == "proj-001"
    assert doc["file_path"] == "/docs/spec.pdf"
    assert doc["file_name"] == "spec.pdf"
    assert doc["doc_type"] == "spec_book"
    assert doc["neo4j_doc_id"] == "neo4j-abc-123"
    assert doc["total_pages"] == 50
    assert doc["file_size_bytes"] == 1048576
    assert doc["status"] == "processing"


# ---------------------------------------------------------------------------
# 2. register_document is idempotent (same neo4j_doc_id returns same id)
# ---------------------------------------------------------------------------

def test_register_document_idempotent(store):
    doc_id_first = store.register_document(
        project_id="proj-001",
        file_path="/docs/spec.pdf",
        file_name="spec.pdf",
        doc_type="spec_book",
        neo4j_doc_id="neo4j-dedup-999",
    )
    doc_id_second = store.register_document(
        project_id="proj-001",
        file_path="/docs/spec.pdf",
        file_name="spec.pdf",
        doc_type="spec_book",
        neo4j_doc_id="neo4j-dedup-999",
    )
    assert doc_id_first == doc_id_second


# ---------------------------------------------------------------------------
# 3. add_chunk creates a chunk with correct fields
# ---------------------------------------------------------------------------

def test_add_chunk_creates_chunk(store):
    doc_id = store.register_document(
        project_id="proj-001",
        file_path="/docs/spec.pdf",
        file_name="spec.pdf",
        doc_type="spec_book",
        neo4j_doc_id="neo4j-chunk-test",
    )
    chunk_id = store.add_chunk(
        document_id=doc_id,
        project_id="proj-001",
        chunk_type="spec_section",
        identifier="03 30 00",
        title="Cast-in-Place Concrete",
        content="Section text here...",
        content_summary="Concrete requirements",
        page_start=10,
        page_end=15,
        discipline="Structural",
        division="03",
    )
    assert chunk_id is not None
    assert isinstance(chunk_id, str)
    assert len(chunk_id) == 36

    chunk = store.get_chunk(chunk_id)
    assert chunk is not None
    assert chunk["document_id"] == doc_id
    assert chunk["project_id"] == "proj-001"
    assert chunk["chunk_type"] == "spec_section"
    assert chunk["identifier"] == "03 30 00"
    assert chunk["title"] == "Cast-in-Place Concrete"
    assert chunk["content"] == "Section text here..."
    assert chunk["content_summary"] == "Concrete requirements"
    assert chunk["page_start"] == 10
    assert chunk["page_end"] == 15
    assert chunk["discipline"] == "Structural"
    assert chunk["division"] == "03"


# ---------------------------------------------------------------------------
# 4. get_chunks_by_document returns all chunks for a document, ordered by page_start
# ---------------------------------------------------------------------------

def test_get_chunks_by_document(store):
    doc_id = store.register_document(
        project_id="proj-002",
        file_path="/docs/drawings.pdf",
        file_name="drawings.pdf",
        doc_type="drawing_set",
        neo4j_doc_id="neo4j-drawings-001",
    )
    # Insert chunks out of order
    store.add_chunk(
        document_id=doc_id, project_id="proj-002",
        chunk_type="drawing_sheet", identifier="A-201",
        title="Floor Plan Level 2", content="", page_start=20, page_end=20,
    )
    store.add_chunk(
        document_id=doc_id, project_id="proj-002",
        chunk_type="drawing_sheet", identifier="A-101",
        title="Floor Plan Level 1", content="", page_start=5, page_end=5,
    )
    store.add_chunk(
        document_id=doc_id, project_id="proj-002",
        chunk_type="drawing_sheet", identifier="A-301",
        title="Roof Plan", content="", page_start=35, page_end=35,
    )

    chunks = store.get_chunks_by_document(doc_id)
    assert len(chunks) == 3
    pages = [c["page_start"] for c in chunks]
    assert pages == sorted(pages), "Chunks should be ordered by page_start"
    assert chunks[0]["identifier"] == "A-101"
    assert chunks[1]["identifier"] == "A-201"
    assert chunks[2]["identifier"] == "A-301"


# ---------------------------------------------------------------------------
# 5. log_page_extraction creates log entries
# ---------------------------------------------------------------------------

def test_log_page_extraction(store):
    doc_id = store.register_document(
        project_id="proj-003",
        file_path="/docs/specs2.pdf",
        file_name="specs2.pdf",
        doc_type="spec_book",
        neo4j_doc_id="neo4j-log-test",
    )
    store.log_page_extraction(
        document_id=doc_id,
        page_number=1,
        extraction_method="pypdf",
        char_count=2400,
        flagged=False,
    )
    store.log_page_extraction(
        document_id=doc_id,
        page_number=2,
        extraction_method="ocr",
        char_count=150,
        flagged=True,
    )

    log = store.get_processing_log(doc_id)
    assert len(log) == 2
    assert log[0]["page_number"] == 1
    assert log[0]["extraction_method"] == "pypdf"
    assert log[0]["char_count"] == 2400
    assert log[0]["flagged"] == 0 or log[0]["flagged"] is False

    assert log[1]["page_number"] == 2
    assert log[1]["extraction_method"] == "ocr"
    assert log[1]["char_count"] == 150
    assert log[1]["flagged"] == 1 or log[1]["flagged"] is True


# ---------------------------------------------------------------------------
# 6. finalize_document sets status and indexed_at when status=indexed
# ---------------------------------------------------------------------------

def test_finalize_document_indexed(store):
    doc_id = store.register_document(
        project_id="proj-004",
        file_path="/docs/final.pdf",
        file_name="final.pdf",
        doc_type="spec_book",
        neo4j_doc_id="neo4j-finalize-indexed",
    )
    store.finalize_document(
        doc_id=doc_id,
        status="indexed",
        reconciliation_summary="All 120 sections matched.",
    )

    doc = store.get_document(doc_id)
    assert doc["status"] == "indexed"
    assert doc["reconciliation_summary"] == "All 120 sections matched."
    assert doc["indexed_at"] is not None


# ---------------------------------------------------------------------------
# 7. finalize_document with status "failed" does not set indexed_at
# ---------------------------------------------------------------------------

def test_finalize_document_failed(store):
    doc_id = store.register_document(
        project_id="proj-004",
        file_path="/docs/broken.pdf",
        file_name="broken.pdf",
        doc_type="drawing_set",
        neo4j_doc_id="neo4j-finalize-failed",
    )
    store.finalize_document(
        doc_id=doc_id,
        status="failed",
        reconciliation_summary="Extraction error on page 5.",
    )

    doc = store.get_document(doc_id)
    assert doc["status"] == "failed"
    assert doc["reconciliation_summary"] == "Extraction error on page 5."
    assert not doc.get("indexed_at")  # should be None / falsy


# ---------------------------------------------------------------------------
# 8. is_document_indexed returns True/False correctly
# ---------------------------------------------------------------------------

def test_is_document_indexed(store):
    doc_id = store.register_document(
        project_id="proj-005",
        file_path="/docs/check.pdf",
        file_name="check.pdf",
        doc_type="spec_book",
        neo4j_doc_id="neo4j-indexed-check",
    )

    # Before finalization
    assert store.is_document_indexed("neo4j-indexed-check") is False

    store.finalize_document(doc_id=doc_id, status="indexed")
    assert store.is_document_indexed("neo4j-indexed-check") is True

    # Unknown neo4j_doc_id
    assert store.is_document_indexed("neo4j-does-not-exist") is False


# ---------------------------------------------------------------------------
# Bonus: get_chunk_by_identifier and list_documents
# ---------------------------------------------------------------------------

def test_get_chunk_by_identifier(store):
    doc_id = store.register_document(
        project_id="proj-006",
        file_path="/docs/spec3.pdf",
        file_name="spec3.pdf",
        doc_type="spec_book",
        neo4j_doc_id="neo4j-ident-test",
    )
    store.add_chunk(
        document_id=doc_id, project_id="proj-006",
        chunk_type="spec_section", identifier="07 92 00",
        title="Joint Sealants", content="Sealant text",
    )

    chunk = store.get_chunk_by_identifier("proj-006", "07 92 00")
    assert chunk is not None
    assert chunk["title"] == "Joint Sealants"

    not_found = store.get_chunk_by_identifier("proj-006", "99 99 99")
    assert not_found is None


def test_list_documents(store):
    store.register_document(
        project_id="proj-007", file_path="/a.pdf", file_name="a.pdf",
        doc_type="spec_book", neo4j_doc_id="neo4j-list-001",
    )
    store.register_document(
        project_id="proj-007", file_path="/b.pdf", file_name="b.pdf",
        doc_type="drawing_set", neo4j_doc_id="neo4j-list-002",
    )
    store.register_document(
        project_id="proj-999", file_path="/c.pdf", file_name="c.pdf",
        doc_type="spec_book", neo4j_doc_id="neo4j-list-003",
    )

    docs_007 = store.list_documents("proj-007")
    assert len(docs_007) == 2
    assert all(d["project_id"] == "proj-007" for d in docs_007)

    docs_999 = store.list_documents("proj-999")
    assert len(docs_999) == 1

    docs_none = store.list_documents("proj-nonexistent")
    assert docs_none == []
