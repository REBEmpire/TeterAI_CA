import pytest
from document_intelligence.query import DocumentQuery
from document_intelligence.storage.chunk_store import ChunkStore


@pytest.fixture
def store(tmp_path):
    db_path = str(tmp_path / "test_query.db")
    s = ChunkStore(db_path)
    # Seed test data
    doc_id = s.register_document(
        project_id="11900", file_path="/specs.pdf", file_name="specs.pdf",
        doc_type="spec_book", neo4j_doc_id="11900_SPEC_abc",
    )
    s.add_chunk(
        document_id=doc_id, project_id="11900", chunk_type="spec_section",
        identifier="09 21 16", title="Gypsum Board Assemblies",
        content="Full gypsum board section text with installation details.",
        content_summary="Covers gypsum board installation.",
        page_start=412, page_end=428, division="09",
    )
    s.add_chunk(
        document_id=doc_id, project_id="11900", chunk_type="spec_section",
        identifier="07 92 00", title="Joint Sealants",
        content="Sealant specifications for exterior joints.",
        content_summary="Exterior joint sealant requirements.",
        page_start=380, page_end=395, division="07",
    )
    yield s
    s.close()


@pytest.fixture
def query(store):
    return DocumentQuery(store)


class TestExactLookups:
    def test_get_spec_section(self, query):
        result = query.get_spec_section("11900", "09 21 16")
        assert result is not None
        assert result["title"] == "Gypsum Board Assemblies"
        assert "gypsum board" in result["content"].lower()

    def test_get_spec_section_not_found(self, query):
        result = query.get_spec_section("11900", "99 99 99")
        assert result is None

    def test_get_sheet_not_found(self, query):
        result = query.get_sheet("11900", "A1.0")
        assert result is None


class TestDiscovery:
    def test_list_documents(self, query):
        docs = query.list_documents("11900")
        assert len(docs) == 1
        assert docs[0]["doc_type"] == "spec_book"

    def test_list_sections(self, query):
        docs = query.list_documents("11900")
        sections = query.list_sections(docs[0]["id"])
        assert len(sections) == 2

    def test_list_sections_empty(self, query):
        sections = query.list_sections("nonexistent")
        assert sections == []
