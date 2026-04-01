# src/document_intelligence/__init__.py
"""
Document Intelligence Service — pre-processes large PDF spec books and
drawing sets into searchable, agent-accessible chunks.

Usage:
    from document_intelligence.service import DocumentIntelligenceService
    from document_intelligence.query import DocumentQuery
    from document_intelligence.storage.chunk_store import ChunkStore
"""
from .service import DocumentIntelligenceService
from .query import DocumentQuery

__all__ = ["DocumentIntelligenceService", "DocumentQuery"]
