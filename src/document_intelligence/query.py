# src/document_intelligence/query.py
"""
Agent-facing query interface for the Document Intelligence content store.

Provides exact lookups, keyword search, and discovery methods that agents
use to retrieve precisely the document content they need.
"""
import logging
from typing import Optional

from document_intelligence.storage.chunk_store import ChunkStore

logger = logging.getLogger(__name__)


class DocumentQuery:
    """Query interface for agents to access document chunks."""

    def __init__(self, store: ChunkStore):
        self._store = store

    # ----- Exact Lookups -----

    def get_spec_section(
        self, project_id: str, section_number: str
    ) -> Optional[dict]:
        """
        Return full text + metadata for a specific spec section.

        Returns dict with: identifier, title, content, content_summary,
                           page_start, page_end, division, metadata_json
        Or None if not found.
        """
        return self._store.get_chunk_by_identifier(project_id, section_number)

    def get_sheet(
        self, project_id: str, sheet_number: str
    ) -> Optional[dict]:
        """
        Return extracted text + metadata for a specific drawing sheet.

        Returns dict with: identifier, title, content, content_summary,
                           page_start, page_end, discipline
        Or None if not found.
        """
        return self._store.get_chunk_by_identifier(project_id, sheet_number)

    def get_pages(
        self, document_id: str, pages: list[int]
    ) -> list[dict]:
        """
        Return raw extracted text for specific PDF pages.

        Uses the processing_log + chunks to find the relevant page text.
        """
        chunks = self._store.get_chunks_by_document(document_id)
        results = []
        for page_num in pages:
            for chunk in chunks:
                if (chunk.get("page_start") and chunk.get("page_end")
                        and chunk["page_start"] <= page_num <= chunk["page_end"]):
                    results.append({
                        "page_number": page_num,
                        "chunk_id": chunk["id"],
                        "identifier": chunk["identifier"],
                        "content": chunk["content"],
                    })
                    break
        return results

    # ----- Search -----

    def search(
        self,
        project_id: str,
        query: str,
        top_k: int = 10,
        doc_type: Optional[str] = None,
        discipline: Optional[str] = None,
        division: Optional[str] = None,
    ) -> list[dict]:
        """
        Search across chunks with optional filters.

        Currently keyword-based. Vector search (sqlite-vss) will be added
        when embeddings are populated on chunks.

        Returns ranked chunks with content summaries.
        """
        conn = self._store._conn()
        query_lower = f"%{query.lower()}%"

        sql = """
            SELECT id, chunk_type, identifier, title, content_summary,
                   page_start, page_end, discipline, division,
                   verification_status
            FROM chunks
            WHERE project_id = ?
              AND (LOWER(content) LIKE ? OR LOWER(title) LIKE ?
                   OR LOWER(content_summary) LIKE ?)
        """
        params: list = [project_id, query_lower, query_lower, query_lower]

        if doc_type:
            sql += " AND chunk_type = ?"
            params.append(doc_type)
        if discipline:
            sql += " AND discipline = ?"
            params.append(discipline)
        if division:
            sql += " AND division = ?"
            params.append(division)

        sql += " LIMIT ?"
        params.append(top_k)

        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ----- Discovery -----

    def list_documents(self, project_id: str) -> list[dict]:
        """List all processed documents for a project."""
        return self._store.list_documents(project_id)

    def list_sections(self, document_id: str) -> list[dict]:
        """List all spec sections for a document."""
        chunks = self._store.get_chunks_by_document(document_id)
        return [c for c in chunks if c["chunk_type"] == "spec_section"]

    def list_sheets(self, document_id: str) -> list[dict]:
        """List all drawing sheets for a document."""
        chunks = self._store.get_chunks_by_document(document_id)
        return [c for c in chunks if c["chunk_type"] == "drawing_sheet"]
