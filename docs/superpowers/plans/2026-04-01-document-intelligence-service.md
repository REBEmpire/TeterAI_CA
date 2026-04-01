# Document Intelligence Service — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a post-ingestion pipeline that chunks spec books and drawing sets into searchable sections/sheets, stores full text in SQLite, and enriches the Knowledge Graph with project-specific SpecSection and DrawingSheet nodes.

**Architecture:** Dual-store design — Neo4j stores lightweight nodes with summaries and relationships for graph traversal; SQLite stores full chunk text with sqlite-vss vector search for content retrieval. A standalone processing script reads CADocument nodes from Neo4j, processes corresponding PDFs, writes chunks to SQLite, and enriches the KG. Idempotent and safe to re-run.

**Tech Stack:** pypdf (PDF text + bookmarks), pytesseract + Pillow (OCR fallback), sqlite3 + sqlite-vss (content store + vector search), Neo4j (KG enrichment), existing AIEngine for summaries and embeddings.

**Spec:** `docs/superpowers/specs/2026-04-01-document-intelligence-service-design.md`

---

## File Structure

```
src/document_intelligence/
  __init__.py                              # Module init, exports DocumentIntelligenceService
  service.py                               # Pipeline orchestrator — coordinates all steps
  extractors/
    __init__.py
    pdf_extractor.py                       # Page-by-page text extraction + OCR fallback
    bookmark_parser.py                     # PDF bookmark/outline navigation
  parsers/
    __init__.py
    spec_parser.py                         # TOC detection, section splitting, CSI pattern matching
    drawing_parser.py                      # Sheet index detection, title block parsing, discipline inference
  validators/
    __init__.py
    spec_validator.py                      # TOC-to-content cross-validation
    drawing_validator.py                   # Index-to-sheet reconciliation
  storage/
    __init__.py
    chunk_store.py                         # SQLite tables + sqlite-vss vector search
    schema.sql                             # DDL for documents, chunks, processing_log tables
  query.py                                 # Agent-facing query interface

scripts/
  process_project_documents.py             # Standalone CLI runner

tests/
  test_document_intelligence/
    __init__.py
    test_pdf_extractor.py
    test_bookmark_parser.py
    test_spec_parser.py
    test_drawing_parser.py
    test_spec_validator.py
    test_drawing_validator.py
    test_chunk_store.py
    test_query.py
    test_service.py
    conftest.py                            # Shared fixtures (sample PDFs, mock data)
```

**Files to modify:**
- `src/knowledge_graph/client.py` — Add `upsert_spec_section`, `upsert_drawing_sheet`, `create_cross_reference` methods
- `src/knowledge_graph/models.py` — Add `DrawingSheet` dataclass, update `NODE_REGISTRY`
- `src/knowledge_graph/schema.py` — Add `DrawingSheet` constraint and vector index
- `pyproject.toml` — Add `pytesseract`, `Pillow`, `sqlite-vss` to dependencies

---

## Task 1: SQLite Schema and Chunk Store

**Files:**
- Create: `src/document_intelligence/storage/schema.sql`
- Create: `src/document_intelligence/storage/__init__.py`
- Create: `src/document_intelligence/storage/chunk_store.py`
- Create: `src/document_intelligence/__init__.py`
- Test: `tests/test_document_intelligence/__init__.py`
- Test: `tests/test_document_intelligence/test_chunk_store.py`

- [ ] **Step 1: Create the SQL schema file**

Create `src/document_intelligence/storage/schema.sql`:

```sql
-- Document Intelligence Service — SQLite schema
-- Three tables: documents, chunks, processing_log

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    doc_type TEXT NOT NULL CHECK (doc_type IN ('spec_book', 'drawing_set')),
    total_pages INTEGER DEFAULT 0,
    file_size_bytes INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'processing' CHECK (status IN ('processing', 'indexed', 'failed')),
    neo4j_doc_id TEXT,
    reconciliation_summary TEXT,
    indexed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    project_id TEXT NOT NULL,
    chunk_type TEXT NOT NULL CHECK (chunk_type IN ('spec_section', 'drawing_sheet')),
    identifier TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    content_summary TEXT DEFAULT '',
    page_start INTEGER,
    page_end INTEGER,
    discipline TEXT DEFAULT '',
    division TEXT DEFAULT '',
    metadata_json TEXT DEFAULT '{}',
    verification_status TEXT DEFAULT '' CHECK (verification_status IN ('', 'matched', 'index_only', 'document_only')),
    embedding BLOB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS processing_log (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    page_number INTEGER NOT NULL,
    extraction_method TEXT NOT NULL CHECK (extraction_method IN ('pypdf', 'ocr', 'failed')),
    char_count INTEGER DEFAULT 0,
    flagged BOOLEAN DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_project_id ON chunks(project_id);
CREATE INDEX IF NOT EXISTS idx_chunks_identifier ON chunks(identifier);
CREATE INDEX IF NOT EXISTS idx_processing_log_document_id ON processing_log(document_id);
```

- [ ] **Step 2: Create package init files**

Create `src/document_intelligence/__init__.py`:

```python
# src/document_intelligence/__init__.py
```

Create `src/document_intelligence/storage/__init__.py`:

```python
# src/document_intelligence/storage/__init__.py
```

Create `tests/test_document_intelligence/__init__.py`:

```python
# tests/test_document_intelligence/__init__.py
```

- [ ] **Step 3: Write failing tests for ChunkStore**

Create `tests/test_document_intelligence/test_chunk_store.py`:

```python
import os
import tempfile
import pytest
from document_intelligence.storage.chunk_store import ChunkStore


@pytest.fixture
def store(tmp_path):
    db_path = str(tmp_path / "test_chunks.db")
    s = ChunkStore(db_path)
    yield s
    s.close()


def test_register_document(store):
    doc_id = store.register_document(
        project_id="11900",
        file_path="/path/to/specs.pdf",
        file_name="specs.pdf",
        doc_type="spec_book",
        total_pages=500,
        file_size_bytes=12345678,
        neo4j_doc_id="11900_SPEC_abc123",
    )
    assert doc_id is not None
    doc = store.get_document(doc_id)
    assert doc["project_id"] == "11900"
    assert doc["status"] == "processing"
    assert doc["total_pages"] == 500


def test_register_document_idempotent(store):
    doc_id1 = store.register_document(
        project_id="11900",
        file_path="/path/to/specs.pdf",
        file_name="specs.pdf",
        doc_type="spec_book",
        neo4j_doc_id="11900_SPEC_abc123",
    )
    doc_id2 = store.register_document(
        project_id="11900",
        file_path="/path/to/specs.pdf",
        file_name="specs.pdf",
        doc_type="spec_book",
        neo4j_doc_id="11900_SPEC_abc123",
    )
    assert doc_id1 == doc_id2


def test_add_chunk(store):
    doc_id = store.register_document(
        project_id="11900",
        file_path="/path/to/specs.pdf",
        file_name="specs.pdf",
        doc_type="spec_book",
        neo4j_doc_id="11900_SPEC_abc123",
    )
    chunk_id = store.add_chunk(
        document_id=doc_id,
        project_id="11900",
        chunk_type="spec_section",
        identifier="09 21 16",
        title="Gypsum Board Assemblies",
        content="Full section text here...",
        content_summary="Covers gypsum board installation.",
        page_start=412,
        page_end=428,
        division="09",
    )
    assert chunk_id is not None
    chunk = store.get_chunk(chunk_id)
    assert chunk["identifier"] == "09 21 16"
    assert chunk["title"] == "Gypsum Board Assemblies"
    assert chunk["page_start"] == 412


def test_get_chunks_by_document(store):
    doc_id = store.register_document(
        project_id="11900",
        file_path="/path/to/specs.pdf",
        file_name="specs.pdf",
        doc_type="spec_book",
        neo4j_doc_id="11900_SPEC_abc123",
    )
    store.add_chunk(
        document_id=doc_id, project_id="11900",
        chunk_type="spec_section", identifier="03 00 00",
        title="Concrete", content="...", page_start=10, page_end=20, division="03",
    )
    store.add_chunk(
        document_id=doc_id, project_id="11900",
        chunk_type="spec_section", identifier="09 00 00",
        title="Finishes", content="...", page_start=100, page_end=120, division="09",
    )
    chunks = store.get_chunks_by_document(doc_id)
    assert len(chunks) == 2


def test_log_page_extraction(store):
    doc_id = store.register_document(
        project_id="11900",
        file_path="/path/to/specs.pdf",
        file_name="specs.pdf",
        doc_type="spec_book",
        neo4j_doc_id="11900_SPEC_abc123",
    )
    store.log_page_extraction(
        document_id=doc_id,
        page_number=1,
        extraction_method="pypdf",
        char_count=3500,
        flagged=False,
    )
    store.log_page_extraction(
        document_id=doc_id,
        page_number=2,
        extraction_method="ocr",
        char_count=45,
        flagged=True,
    )
    logs = store.get_processing_log(doc_id)
    assert len(logs) == 2
    assert logs[1]["flagged"] == 1


def test_finalize_document(store):
    doc_id = store.register_document(
        project_id="11900",
        file_path="/path/to/specs.pdf",
        file_name="specs.pdf",
        doc_type="spec_book",
        neo4j_doc_id="11900_SPEC_abc123",
    )
    store.finalize_document(doc_id, status="indexed")
    doc = store.get_document(doc_id)
    assert doc["status"] == "indexed"
    assert doc["indexed_at"] is not None


def test_finalize_document_failed(store):
    doc_id = store.register_document(
        project_id="11900",
        file_path="/path/to/specs.pdf",
        file_name="specs.pdf",
        doc_type="spec_book",
        neo4j_doc_id="11900_SPEC_abc123",
    )
    store.finalize_document(doc_id, status="failed")
    doc = store.get_document(doc_id)
    assert doc["status"] == "failed"


def test_document_already_indexed(store):
    doc_id = store.register_document(
        project_id="11900",
        file_path="/path/to/specs.pdf",
        file_name="specs.pdf",
        doc_type="spec_book",
        neo4j_doc_id="11900_SPEC_abc123",
    )
    store.finalize_document(doc_id, status="indexed")
    assert store.is_document_indexed("11900_SPEC_abc123") is True
    assert store.is_document_indexed("nonexistent") is False
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd "C:/Users/RussellBybee/Documents/Adventures in AI Land/TeterAI_CA/TeterAI_CA" && uv run pytest tests/test_document_intelligence/test_chunk_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'document_intelligence'`

- [ ] **Step 5: Implement ChunkStore**

Create `src/document_intelligence/storage/chunk_store.py`:

```python
# src/document_intelligence/storage/chunk_store.py
"""
SQLite content store for document chunks (spec sections and drawing sheets).

Thread-safe. Uses WAL journal mode for concurrent reads during processing.
Schema applied on init from schema.sql.
"""
import json
import logging
import os
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class ChunkStore:
    def __init__(self, db_path: str):
        self._db_path = str(Path(db_path).expanduser())
        self._lock = threading.Lock()
        self._local = threading.local()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self) -> None:
        schema_sql = _SCHEMA_PATH.read_text()
        conn = self._conn()
        conn.executescript(schema_sql)

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    # ----- Documents -----

    def register_document(
        self,
        project_id: str,
        file_path: str,
        file_name: str,
        doc_type: str,
        neo4j_doc_id: str,
        total_pages: int = 0,
        file_size_bytes: int = 0,
    ) -> str:
        conn = self._conn()
        with self._lock:
            existing = conn.execute(
                "SELECT id FROM documents WHERE neo4j_doc_id = ?",
                (neo4j_doc_id,),
            ).fetchone()
            if existing:
                return existing["id"]

            doc_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO documents
                   (id, project_id, file_path, file_name, doc_type,
                    total_pages, file_size_bytes, neo4j_doc_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (doc_id, project_id, file_path, file_name, doc_type,
                 total_pages, file_size_bytes, neo4j_doc_id),
            )
            conn.commit()
            return doc_id

    def get_document(self, doc_id: str) -> Optional[dict]:
        row = self._conn().execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        return dict(row) if row else None

    def is_document_indexed(self, neo4j_doc_id: str) -> bool:
        row = self._conn().execute(
            "SELECT status FROM documents WHERE neo4j_doc_id = ?",
            (neo4j_doc_id,),
        ).fetchone()
        return row is not None and row["status"] == "indexed"

    def finalize_document(
        self, doc_id: str, status: str,
        reconciliation_summary: Optional[dict] = None,
    ) -> None:
        conn = self._conn()
        recon_json = json.dumps(reconciliation_summary) if reconciliation_summary else None
        with self._lock:
            if status == "indexed":
                conn.execute(
                    """UPDATE documents
                       SET status = ?, indexed_at = CURRENT_TIMESTAMP,
                           reconciliation_summary = ?
                       WHERE id = ?""",
                    (status, recon_json, doc_id),
                )
            else:
                conn.execute(
                    "UPDATE documents SET status = ? WHERE id = ?",
                    (status, doc_id),
                )
            conn.commit()

    # ----- Chunks -----

    def add_chunk(
        self,
        document_id: str,
        project_id: str,
        chunk_type: str,
        identifier: str,
        title: str,
        content: str,
        content_summary: str = "",
        page_start: Optional[int] = None,
        page_end: Optional[int] = None,
        discipline: str = "",
        division: str = "",
        metadata_json: Optional[dict] = None,
        verification_status: str = "",
        embedding: Optional[bytes] = None,
    ) -> str:
        chunk_id = str(uuid.uuid4())
        meta = json.dumps(metadata_json) if metadata_json else "{}"
        conn = self._conn()
        with self._lock:
            conn.execute(
                """INSERT INTO chunks
                   (id, document_id, project_id, chunk_type, identifier, title,
                    content, content_summary, page_start, page_end,
                    discipline, division, metadata_json, verification_status, embedding)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (chunk_id, document_id, project_id, chunk_type, identifier, title,
                 content, content_summary, page_start, page_end,
                 discipline, division, meta, verification_status, embedding),
            )
            conn.commit()
        return chunk_id

    def get_chunk(self, chunk_id: str) -> Optional[dict]:
        row = self._conn().execute(
            "SELECT * FROM chunks WHERE id = ?", (chunk_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_chunks_by_document(self, document_id: str) -> list[dict]:
        rows = self._conn().execute(
            "SELECT * FROM chunks WHERE document_id = ? ORDER BY page_start",
            (document_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_chunk_by_identifier(
        self, project_id: str, identifier: str
    ) -> Optional[dict]:
        row = self._conn().execute(
            "SELECT * FROM chunks WHERE project_id = ? AND identifier = ?",
            (project_id, identifier),
        ).fetchone()
        return dict(row) if row else None

    # ----- Processing Log -----

    def log_page_extraction(
        self,
        document_id: str,
        page_number: int,
        extraction_method: str,
        char_count: int,
        flagged: bool = False,
    ) -> None:
        log_id = str(uuid.uuid4())
        conn = self._conn()
        with self._lock:
            conn.execute(
                """INSERT INTO processing_log
                   (id, document_id, page_number, extraction_method, char_count, flagged)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (log_id, document_id, page_number, extraction_method, char_count, flagged),
            )
            conn.commit()

    def get_processing_log(self, document_id: str) -> list[dict]:
        rows = self._conn().execute(
            "SELECT * FROM processing_log WHERE document_id = ? ORDER BY page_number",
            (document_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ----- Listing -----

    def list_documents(self, project_id: str) -> list[dict]:
        rows = self._conn().execute(
            "SELECT * FROM documents WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd "C:/Users/RussellBybee/Documents/Adventures in AI Land/TeterAI_CA/TeterAI_CA" && uv run pytest tests/test_document_intelligence/test_chunk_store.py -v`
Expected: All 8 tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/document_intelligence/__init__.py src/document_intelligence/storage/ tests/test_document_intelligence/
git commit -m "feat(doc-intel): add SQLite chunk store with schema and tests"
```

---

## Task 2: PDF Extractor (Page-by-Page + OCR Fallback)

**Files:**
- Create: `src/document_intelligence/extractors/__init__.py`
- Create: `src/document_intelligence/extractors/pdf_extractor.py`
- Test: `tests/test_document_intelligence/test_pdf_extractor.py`

- [ ] **Step 1: Create extractors init**

Create `src/document_intelligence/extractors/__init__.py`:

```python
# src/document_intelligence/extractors/__init__.py
```

- [ ] **Step 2: Write failing tests for PdfExtractor**

Create `tests/test_document_intelligence/test_pdf_extractor.py`:

```python
import io
import pytest
from unittest.mock import patch, MagicMock
from document_intelligence.extractors.pdf_extractor import PdfExtractor


@pytest.fixture
def extractor():
    return PdfExtractor()


def _make_minimal_pdf(text: str = "Hello World") -> bytes:
    """Create a minimal valid PDF in memory using pypdf."""
    from pypdf import PdfWriter
    from pypdf.generic import PageObject, RectangleObject
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.pagesizes import letter

    # Use reportlab to make a real PDF with text
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=letter)
    c.drawString(100, 700, text)
    c.showPage()
    c.save()
    return buf.getvalue()


def _make_empty_pdf() -> bytes:
    """Create a PDF with a blank page (no extractable text)."""
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


class TestExtractPages:
    def test_extract_valid_pdf(self, extractor, tmp_path):
        """Test page-by-page extraction returns text per page."""
        # Use a mock approach since creating PDFs with text requires reportlab
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_make_empty_pdf())

        pages = extractor.extract_pages(str(pdf_path))
        assert isinstance(pages, list)
        assert len(pages) >= 1
        assert "page_number" in pages[0]
        assert "text" in pages[0]
        assert "extraction_method" in pages[0]
        assert "char_count" in pages[0]

    def test_extract_nonexistent_file(self, extractor):
        pages = extractor.extract_pages("/nonexistent/file.pdf")
        assert pages == []

    def test_extract_invalid_content(self, extractor, tmp_path):
        bad_file = tmp_path / "bad.pdf"
        bad_file.write_bytes(b"this is not a pdf")
        pages = extractor.extract_pages(str(bad_file))
        assert pages == []

    def test_short_text_flagged(self, extractor, tmp_path):
        """Pages with < 50 chars should be flagged."""
        pdf_path = tmp_path / "blank.pdf"
        pdf_path.write_bytes(_make_empty_pdf())

        pages = extractor.extract_pages(str(pdf_path))
        if pages:
            assert pages[0]["flagged"] is True

    def test_page_count(self, extractor, tmp_path):
        """get_page_count returns total pages in a PDF."""
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_make_empty_pdf())
        count = extractor.get_page_count(str(pdf_path))
        assert count == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_document_intelligence/test_pdf_extractor.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Implement PdfExtractor**

Create `src/document_intelligence/extractors/pdf_extractor.py`:

```python
# src/document_intelligence/extractors/pdf_extractor.py
"""
Page-by-page PDF text extraction with OCR fallback.

Uses subprocess isolation for pypdf (matches ingestion.py pattern)
to prevent C extension segfaults from killing the worker process.
OCR fallback via pytesseract when text extraction yields < 50 chars.
"""
import io
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Minimum characters for a page to be considered successfully extracted
_MIN_CHARS = 50


class PdfExtractor:
    """Extract text from PDF files page-by-page with OCR fallback."""

    def get_page_count(self, pdf_path: str) -> int:
        """Return total number of pages in a PDF, or 0 on error."""
        script = (
            "import pypdf, sys\n"
            f"r = pypdf.PdfReader({repr(pdf_path)})\n"
            "print(len(r.pages))\n"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, encoding="utf-8", errors="replace", timeout=30,
            )
            if proc.returncode == 0:
                return int(proc.stdout.strip())
        except Exception as e:
            logger.warning(f"get_page_count failed for {pdf_path}: {e}")
        return 0

    def extract_pages(self, pdf_path: str) -> list[dict]:
        """
        Extract text from every page of a PDF.

        Returns a list of dicts, one per page:
            {page_number, text, extraction_method, char_count, flagged}

        extraction_method: "pypdf" | "ocr" | "failed"
        flagged: True if char_count < 50 (poor extraction)
        """
        if not Path(pdf_path).exists():
            logger.warning(f"PDF file not found: {pdf_path}")
            return []

        content = Path(pdf_path).read_bytes()
        if len(content) < 4 or not content.startswith(b"%PDF"):
            logger.warning(f"Not a valid PDF: {pdf_path}")
            return []

        # Extract all pages via pypdf in subprocess
        raw_pages = self._extract_all_pages_pypdf(pdf_path)
        if raw_pages is None:
            return []

        results = []
        for page_num, text in enumerate(raw_pages, start=1):
            char_count = len(text.strip())

            if char_count < _MIN_CHARS:
                # Try OCR fallback
                ocr_text = self._ocr_page(pdf_path, page_num - 1)
                if ocr_text and len(ocr_text.strip()) > char_count:
                    results.append({
                        "page_number": page_num,
                        "text": ocr_text,
                        "extraction_method": "ocr",
                        "char_count": len(ocr_text.strip()),
                        "flagged": len(ocr_text.strip()) < _MIN_CHARS,
                    })
                    continue

            method = "pypdf" if char_count >= _MIN_CHARS else "failed"
            results.append({
                "page_number": page_num,
                "text": text,
                "extraction_method": method if char_count >= _MIN_CHARS else "failed",
                "char_count": char_count,
                "flagged": char_count < _MIN_CHARS,
            })

        return results

    def _extract_all_pages_pypdf(self, pdf_path: str) -> Optional[list[str]]:
        """Run pypdf in subprocess, return list of per-page text strings."""
        script = (
            "import pypdf, io, sys, json\n"
            "sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')\n"
            f"r = pypdf.PdfReader({repr(pdf_path)})\n"
            "pages = [p.extract_text() or '' for p in r.pages]\n"
            "print(json.dumps(pages))\n"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, encoding="utf-8", errors="replace",
                timeout=120,
            )
            if proc.returncode != 0:
                logger.warning(f"pypdf subprocess failed: {proc.stderr[:300]}")
                return None
            import json
            return json.loads(proc.stdout)
        except subprocess.TimeoutExpired:
            logger.warning(f"pypdf extraction timed out for {pdf_path}")
            return None
        except Exception as e:
            logger.warning(f"pypdf extraction failed for {pdf_path}: {e}")
            return None

    def _ocr_page(self, pdf_path: str, page_index: int) -> Optional[str]:
        """
        OCR a single page using pytesseract + Pillow.
        Returns extracted text or None on failure.
        """
        script = (
            "import sys, json\n"
            "try:\n"
            "    from pdf2image import convert_from_path\n"
            "    import pytesseract\n"
            f"    images = convert_from_path({repr(pdf_path)}, first_page={page_index + 1}, last_page={page_index + 1})\n"
            "    text = pytesseract.image_to_string(images[0]) if images else ''\n"
            "    print(json.dumps(text))\n"
            "except ImportError:\n"
            "    print(json.dumps(''))\n"
            "except Exception as e:\n"
            "    print(json.dumps(''), file=sys.stderr)\n"
            "    print(json.dumps(''), end='')\n"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, encoding="utf-8", errors="replace",
                timeout=60,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                import json
                return json.loads(proc.stdout)
        except Exception as e:
            logger.debug(f"OCR fallback failed for page {page_index}: {e}")
        return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_document_intelligence/test_pdf_extractor.py -v`
Expected: PASS (OCR tests may skip gracefully if pytesseract not installed)

- [ ] **Step 6: Commit**

```bash
git add src/document_intelligence/extractors/ tests/test_document_intelligence/test_pdf_extractor.py
git commit -m "feat(doc-intel): add PDF page-by-page extractor with OCR fallback"
```

---

## Task 3: Bookmark Parser

**Files:**
- Create: `src/document_intelligence/extractors/bookmark_parser.py`
- Test: `tests/test_document_intelligence/test_bookmark_parser.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_document_intelligence/test_bookmark_parser.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from document_intelligence.extractors.bookmark_parser import BookmarkParser


@pytest.fixture
def parser():
    return BookmarkParser()


class TestBookmarkParser:
    def test_no_bookmarks(self, parser, tmp_path):
        """A blank PDF has no bookmarks."""
        from pypdf import PdfWriter
        import io
        writer = PdfWriter()
        writer.add_blank_page(612, 792)
        pdf_path = tmp_path / "no_bookmarks.pdf"
        with open(pdf_path, "wb") as f:
            writer.write(f)

        bookmarks = parser.extract_bookmarks(str(pdf_path))
        assert bookmarks == []

    def test_find_toc_bookmark_returns_none_when_absent(self, parser, tmp_path):
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(612, 792)
        pdf_path = tmp_path / "no_toc.pdf"
        with open(pdf_path, "wb") as f:
            writer.write(f)

        result = parser.find_toc_bookmark(str(pdf_path))
        assert result is None

    def test_bookmark_structure(self, parser):
        """Test that extracted bookmarks have the expected keys."""
        # We test the parsing function directly with mock data
        mock_outline = [
            MagicMock(title="Table of Contents", page=MagicMock()),
            MagicMock(title="Section 03 30 00 - Concrete", page=MagicMock()),
        ]
        # Mock page resolution
        mock_reader = MagicMock()
        mock_reader.outline = mock_outline
        mock_reader.pages = [MagicMock(), MagicMock()]

        with patch("document_intelligence.extractors.bookmark_parser.pypdf.PdfReader", return_value=mock_reader):
            with patch.object(parser, "_resolve_page_number", side_effect=[0, 1]):
                bookmarks = parser.extract_bookmarks("dummy.pdf")
                assert len(bookmarks) == 2
                assert bookmarks[0]["title"] == "Table of Contents"
                assert "page_number" in bookmarks[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_document_intelligence/test_bookmark_parser.py -v`
Expected: FAIL

- [ ] **Step 3: Implement BookmarkParser**

Create `src/document_intelligence/extractors/bookmark_parser.py`:

```python
# src/document_intelligence/extractors/bookmark_parser.py
"""
PDF bookmark/outline extraction for navigating spec books and drawing sets.

PDF bookmarks (outline) provide a structured table of contents that helps
locate TOC pages and section boundaries without pattern-matching.
"""
import logging
from typing import Optional

import pypdf

logger = logging.getLogger(__name__)

# Fuzzy match targets for TOC bookmark
_TOC_TITLES = {"table of contents", "toc", "contents", "index"}

# Fuzzy match targets for sheet index bookmark
_SHEET_INDEX_TITLES = {
    "sheet index", "drawing index", "drawing list",
    "sheet list", "index of drawings",
}


class BookmarkParser:
    """Extract and navigate PDF bookmarks/outline."""

    def extract_bookmarks(self, pdf_path: str) -> list[dict]:
        """
        Extract all top-level bookmarks from a PDF.

        Returns list of dicts:
            {title: str, page_number: int (0-based)}
        """
        try:
            reader = pypdf.PdfReader(pdf_path)
        except Exception as e:
            logger.warning(f"Cannot read PDF for bookmarks: {pdf_path}: {e}")
            return []

        if not reader.outline:
            return []

        bookmarks = []
        self._flatten_outline(reader, reader.outline, bookmarks)
        return bookmarks

    def _flatten_outline(
        self,
        reader: pypdf.PdfReader,
        outline: list,
        result: list[dict],
    ) -> None:
        """Recursively flatten nested outline into a flat bookmark list."""
        for item in outline:
            if isinstance(item, list):
                self._flatten_outline(reader, item, result)
            else:
                title = getattr(item, "title", None)
                if title:
                    page_num = self._resolve_page_number(reader, item)
                    result.append({
                        "title": title.strip(),
                        "page_number": page_num,
                    })

    def _resolve_page_number(
        self, reader: pypdf.PdfReader, bookmark
    ) -> int:
        """Resolve a bookmark's destination to a 0-based page number."""
        try:
            dest = bookmark
            if hasattr(dest, "page"):
                page_obj = dest.page
                if isinstance(page_obj, int):
                    return page_obj
                # Indirect reference — resolve via reader
                for i, page in enumerate(reader.pages):
                    if page.indirect_reference == page_obj:
                        return i
            return 0
        except Exception:
            return 0

    def find_toc_bookmark(self, pdf_path: str) -> Optional[dict]:
        """
        Find the bookmark pointing to the Table of Contents.

        Returns {title, page_number} or None if no TOC bookmark found.
        """
        bookmarks = self.extract_bookmarks(pdf_path)
        for bm in bookmarks:
            if bm["title"].lower().strip() in _TOC_TITLES:
                return bm
        return None

    def find_sheet_index_bookmark(self, pdf_path: str) -> Optional[dict]:
        """
        Find the bookmark pointing to the Sheet Index / Drawing List.

        Returns {title, page_number} or None.
        """
        bookmarks = self.extract_bookmarks(pdf_path)
        for bm in bookmarks:
            if bm["title"].lower().strip() in _SHEET_INDEX_TITLES:
                return bm
        return None

    def get_section_boundaries(self, pdf_path: str) -> list[dict]:
        """
        Use bookmarks to infer section boundaries.

        Returns list of:
            {title, start_page (0-based), end_page (0-based, inclusive)}

        End page is the page before the next bookmark starts (or last page).
        """
        bookmarks = self.extract_bookmarks(pdf_path)
        if not bookmarks:
            return []

        try:
            reader = pypdf.PdfReader(pdf_path)
            total_pages = len(reader.pages)
        except Exception:
            return []

        boundaries = []
        for i, bm in enumerate(bookmarks):
            start = bm["page_number"]
            if i + 1 < len(bookmarks):
                end = bookmarks[i + 1]["page_number"] - 1
            else:
                end = total_pages - 1
            if end < start:
                end = start
            boundaries.append({
                "title": bm["title"],
                "start_page": start,
                "end_page": end,
            })

        return boundaries
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_document_intelligence/test_bookmark_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/document_intelligence/extractors/bookmark_parser.py tests/test_document_intelligence/test_bookmark_parser.py
git commit -m "feat(doc-intel): add PDF bookmark parser for TOC and sheet index detection"
```

---

## Task 4: Spec Parser (TOC Detection + Section Splitting)

**Files:**
- Create: `src/document_intelligence/parsers/__init__.py`
- Create: `src/document_intelligence/parsers/spec_parser.py`
- Test: `tests/test_document_intelligence/test_spec_parser.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_document_intelligence/test_spec_parser.py`:

```python
import pytest
from document_intelligence.parsers.spec_parser import SpecParser


@pytest.fixture
def parser():
    return SpecParser()


class TestParseTocLines:
    def test_standard_toc_line(self, parser):
        lines = [
            "SECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES ....... 412",
            "SECTION 07 92 00 - JOINT SEALANTS ............... 380",
        ]
        sections = parser.parse_toc_lines(lines)
        assert len(sections) == 2
        assert sections[0]["section_number"] == "09 21 16"
        assert sections[0]["title"] == "GYPSUM BOARD ASSEMBLIES"
        assert sections[0]["page_number"] == 412
        assert sections[1]["section_number"] == "07 92 00"

    def test_toc_line_without_dots(self, parser):
        lines = ["SECTION 03 30 00 - CAST-IN-PLACE CONCRETE 150"]
        sections = parser.parse_toc_lines(lines)
        assert len(sections) == 1
        assert sections[0]["section_number"] == "03 30 00"
        assert sections[0]["title"] == "CAST-IN-PLACE CONCRETE"

    def test_toc_line_no_section_prefix(self, parser):
        lines = ["09 21 16 GYPSUM BOARD ASSEMBLIES 412"]
        sections = parser.parse_toc_lines(lines)
        assert len(sections) == 1
        assert sections[0]["section_number"] == "09 21 16"

    def test_non_matching_lines_ignored(self, parser):
        lines = [
            "This is a random line",
            "Page 5 of 10",
            "",
        ]
        sections = parser.parse_toc_lines(lines)
        assert sections == []


class TestInferDivision:
    def test_infer_division(self, parser):
        assert parser.infer_division("09 21 16") == "09"
        assert parser.infer_division("03 30 00") == "03"
        assert parser.infer_division("07 92 00") == "07"


class TestDetectSectionHeaders:
    def test_detect_section_header_in_text(self, parser):
        text = (
            "Some preamble text\n"
            "SECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES\n"
            "PART 1 - GENERAL\n"
            "1.1 SUMMARY\n"
        )
        headers = parser.detect_section_headers(text)
        assert len(headers) == 1
        assert headers[0]["section_number"] == "09 21 16"
        assert "GYPSUM BOARD" in headers[0]["title"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_document_intelligence/test_spec_parser.py -v`
Expected: FAIL

- [ ] **Step 3: Implement SpecParser**

Create `src/document_intelligence/parsers/__init__.py`:

```python
# src/document_intelligence/parsers/__init__.py
```

Create `src/document_intelligence/parsers/spec_parser.py`:

```python
# src/document_intelligence/parsers/spec_parser.py
"""
Spec book parser — TOC detection, section splitting, CSI pattern matching.

Handles two detection strategies:
  1. Bookmark-first: Use PDF bookmarks to find TOC, parse TOC lines
  2. Pattern-matching fallback: Scan pages for SECTION XX XX XX headers
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Regex: "SECTION 09 21 16" or just "09 21 16" with optional title and page
_CSI_SECTION_RE = re.compile(
    r"(?:SECTION\s+)?"
    r"(\d{2}\s?\d{2}\s?\d{2})"
    r"(?:\s*[-–—]\s*(.+?))?"
    r"(?:\s*[.·…]+\s*(\d+))?"
    r"\s*$",
    re.IGNORECASE,
)

# Standalone section header in body text (SECTION XX XX XX - TITLE)
_SECTION_HEADER_RE = re.compile(
    r"^SECTION\s+(\d{2}\s?\d{2}\s?\d{2})\s*[-–—]\s*(.+)",
    re.IGNORECASE | re.MULTILINE,
)

# Match "09 21 16 TITLE 412" (no SECTION prefix, number then title then page)
_BARE_CSI_RE = re.compile(
    r"^(\d{2}\s\d{2}\s\d{2})\s+(.+?)\s+(\d+)\s*$",
)


class SpecParser:
    """Parse spec book structure: TOC lines, section headers, CSI divisions."""

    def parse_toc_lines(self, lines: list[str]) -> list[dict]:
        """
        Parse TOC-style lines into structured section entries.

        Returns list of:
            {section_number, title, page_number, division}

        Handles formats:
            SECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES ....... 412
            09 21 16 GYPSUM BOARD ASSEMBLIES 412
            SECTION 03 30 00 - CAST-IN-PLACE CONCRETE 150
        """
        sections = []
        for line in lines:
            line = line.strip()
            if not line:
                continue

            match = _CSI_SECTION_RE.search(line)
            if not match:
                match = _BARE_CSI_RE.match(line)
                if match:
                    section_num = self._normalize_section_number(match.group(1))
                    title = match.group(2).strip().rstrip(".")
                    page = int(match.group(3))
                    sections.append({
                        "section_number": section_num,
                        "title": title,
                        "page_number": page,
                        "division": self.infer_division(section_num),
                    })
                continue

            section_num = self._normalize_section_number(match.group(1))
            title = (match.group(2) or "").strip().rstrip(".")
            page_str = match.group(3)
            page = int(page_str) if page_str else None

            sections.append({
                "section_number": section_num,
                "title": title,
                "page_number": page,
                "division": self.infer_division(section_num),
            })

        return sections

    def detect_section_headers(self, text: str) -> list[dict]:
        """
        Scan body text for SECTION XX XX XX headers (pattern-matching fallback).

        Returns list of {section_number, title}.
        """
        headers = []
        for match in _SECTION_HEADER_RE.finditer(text):
            section_num = self._normalize_section_number(match.group(1))
            title = match.group(2).strip()
            headers.append({
                "section_number": section_num,
                "title": title,
            })
        return headers

    def infer_division(self, section_number: str) -> str:
        """Extract the 2-digit CSI division from a section number."""
        return section_number[:2]

    def split_pages_by_sections(
        self,
        pages: list[dict],
        toc_sections: list[dict],
        page_offset: int = 0,
    ) -> list[dict]:
        """
        Split page text into section chunks using TOC page references.

        Args:
            pages: List of {page_number, text} from PdfExtractor
            toc_sections: List of {section_number, title, page_number} from parse_toc_lines
            page_offset: Adjustment between printed page numbers and PDF page indices

        Returns list of:
            {section_number, title, division, content, page_start, page_end}
        """
        if not toc_sections or not pages:
            return []

        # Build a page-number-indexed lookup
        page_text = {p["page_number"]: p["text"] for p in pages}
        total_pages = max(page_text.keys()) if page_text else 0

        chunks = []
        for i, section in enumerate(toc_sections):
            if section.get("page_number") is None:
                continue

            start_page = section["page_number"] + page_offset
            if i + 1 < len(toc_sections) and toc_sections[i + 1].get("page_number"):
                end_page = toc_sections[i + 1]["page_number"] + page_offset - 1
            else:
                end_page = total_pages

            # Collect text from all pages in range
            content_parts = []
            for pg in range(start_page, end_page + 1):
                if pg in page_text:
                    content_parts.append(page_text[pg])

            chunks.append({
                "section_number": section["section_number"],
                "title": section["title"],
                "division": section.get("division", self.infer_division(section["section_number"])),
                "content": "\n".join(content_parts),
                "page_start": start_page,
                "page_end": end_page,
            })

        return chunks

    def _normalize_section_number(self, raw: str) -> str:
        """Normalize section number to 'XX XX XX' format with spaces."""
        digits = re.sub(r"\s+", "", raw)
        if len(digits) == 6:
            return f"{digits[:2]} {digits[2:4]} {digits[4:6]}"
        return raw.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_document_intelligence/test_spec_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/document_intelligence/parsers/ tests/test_document_intelligence/test_spec_parser.py
git commit -m "feat(doc-intel): add spec parser for TOC and section header detection"
```

---

## Task 5: Drawing Parser (Sheet Index + Title Block)

**Files:**
- Create: `src/document_intelligence/parsers/drawing_parser.py`
- Test: `tests/test_document_intelligence/test_drawing_parser.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_document_intelligence/test_drawing_parser.py`:

```python
import pytest
from document_intelligence.parsers.drawing_parser import DrawingParser


@pytest.fixture
def parser():
    return DrawingParser()


class TestInferDiscipline:
    def test_architectural(self, parser):
        assert parser.infer_discipline("A2.3") == "Architectural"

    def test_structural(self, parser):
        assert parser.infer_discipline("S3.1") == "Structural"

    def test_mechanical(self, parser):
        assert parser.infer_discipline("M1.0") == "Mechanical"

    def test_electrical(self, parser):
        assert parser.infer_discipline("E2.1") == "Electrical"

    def test_plumbing(self, parser):
        assert parser.infer_discipline("P1.0") == "Plumbing"

    def test_landscape(self, parser):
        assert parser.infer_discipline("L1.0") == "Landscape"

    def test_civil(self, parser):
        assert parser.infer_discipline("C1.0") == "Civil"

    def test_fire_protection(self, parser):
        assert parser.infer_discipline("FP1.0") == "Fire Protection"

    def test_unknown_prefix(self, parser):
        assert parser.infer_discipline("X1.0") == "Unknown"


class TestParseSheetIndexLines:
    def test_standard_sheet_line(self, parser):
        lines = [
            "A1.0    ARCHITECTURAL SITE PLAN",
            "A2.1    FIRST FLOOR PLAN",
            "S1.0    STRUCTURAL FOUNDATION PLAN",
        ]
        sheets = parser.parse_sheet_index_lines(lines)
        assert len(sheets) == 3
        assert sheets[0]["sheet_number"] == "A1.0"
        assert sheets[0]["title"] == "ARCHITECTURAL SITE PLAN"
        assert sheets[0]["discipline"] == "Architectural"

    def test_sheet_with_dash_separator(self, parser):
        lines = ["A1.0 - ARCHITECTURAL SITE PLAN"]
        sheets = parser.parse_sheet_index_lines(lines)
        assert len(sheets) == 1
        assert sheets[0]["title"] == "ARCHITECTURAL SITE PLAN"

    def test_non_matching_lines(self, parser):
        lines = ["This is not a sheet entry", "Page 1", ""]
        sheets = parser.parse_sheet_index_lines(lines)
        assert sheets == []


class TestDetectTitleBlock:
    def test_detect_sheet_number_in_text(self, parser):
        text = (
            "Some notes about the drawing\n"
            "Sheet: A2.3\n"
            "Title: SECOND FLOOR PLAN\n"
        )
        result = parser.detect_title_block(text)
        assert result is not None
        assert result["sheet_number"] == "A2.3"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_document_intelligence/test_drawing_parser.py -v`
Expected: FAIL

- [ ] **Step 3: Implement DrawingParser**

Create `src/document_intelligence/parsers/drawing_parser.py`:

```python
# src/document_intelligence/parsers/drawing_parser.py
"""
Drawing set parser — sheet index detection, title block parsing, discipline inference.

Drawing sheet numbers follow discipline prefixes:
    A=Architectural, S=Structural, M=Mechanical, E=Electrical,
    P=Plumbing, L=Landscape, C=Civil, FP=Fire Protection
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Discipline prefix mapping
_DISCIPLINE_MAP: dict[str, str] = {
    "A":  "Architectural",
    "S":  "Structural",
    "M":  "Mechanical",
    "E":  "Electrical",
    "P":  "Plumbing",
    "L":  "Landscape",
    "C":  "Civil",
    "FP": "Fire Protection",
    "FS": "Fire Suppression",
    "T":  "Telecommunications",
    "G":  "General",
}

# Regex: sheet number like A1.0, S3.1, FP1.0, M2.01
_SHEET_NUMBER_RE = re.compile(
    r"^([A-Z]{1,2}\d+(?:\.\d+[A-Za-z]?)?)$"
)

# Sheet index line: "A1.0    TITLE" or "A1.0 - TITLE"
_SHEET_LINE_RE = re.compile(
    r"^\s*([A-Z]{1,2}\d+(?:\.\d+[A-Za-z]?))\s+[-–—]?\s*(.+?)\s*$",
    re.IGNORECASE,
)

# Title block detection: "Sheet: A2.3" or sheet number alone on a line
_TITLE_BLOCK_SHEET_RE = re.compile(
    r"(?:Sheet[:\s]+|^)([A-Z]{1,2}\d+(?:\.\d+[A-Za-z]?))\s*$",
    re.IGNORECASE | re.MULTILINE,
)


class DrawingParser:
    """Parse drawing set structure: sheet indexes, title blocks, disciplines."""

    def infer_discipline(self, sheet_number: str) -> str:
        """Infer the discipline from a sheet number prefix."""
        upper = sheet_number.upper()
        # Try two-letter prefixes first (FP, FS)
        if len(upper) >= 2 and upper[:2] in _DISCIPLINE_MAP:
            return _DISCIPLINE_MAP[upper[:2]]
        # Single-letter prefix
        if upper[0] in _DISCIPLINE_MAP:
            return _DISCIPLINE_MAP[upper[0]]
        return "Unknown"

    def parse_sheet_index_lines(self, lines: list[str]) -> list[dict]:
        """
        Parse sheet index lines into structured sheet entries.

        Returns list of:
            {sheet_number, title, discipline}
        """
        sheets = []
        for line in lines:
            line = line.strip()
            if not line:
                continue

            match = _SHEET_LINE_RE.match(line)
            if not match:
                continue

            sheet_num = match.group(1).upper()
            title = match.group(2).strip()

            # Validate it looks like a real sheet number
            if not re.match(r"[A-Z]{1,2}\d", sheet_num):
                continue

            sheets.append({
                "sheet_number": sheet_num,
                "title": title,
                "discipline": self.infer_discipline(sheet_num),
            })

        return sheets

    def detect_title_block(self, page_text: str) -> Optional[dict]:
        """
        Attempt to detect a sheet number from title block text on a drawing page.

        Returns {sheet_number, discipline} or None.
        """
        match = _TITLE_BLOCK_SHEET_RE.search(page_text)
        if match:
            sheet_num = match.group(1).upper()
            return {
                "sheet_number": sheet_num,
                "discipline": self.infer_discipline(sheet_num),
            }
        return None

    def split_pages_by_sheets(
        self,
        pages: list[dict],
        sheet_index: list[dict],
    ) -> list[dict]:
        """
        Assign pages to sheets. For drawing sets, each page typically = one sheet.

        Args:
            pages: list of {page_number, text} from PdfExtractor
            sheet_index: list of {sheet_number, title, discipline} from parse_sheet_index_lines

        Returns list of:
            {sheet_number, title, discipline, content, page_start, page_end}
        """
        if not sheet_index or not pages:
            return []

        chunks = []
        # Simple 1:1 mapping — sheet_index[i] corresponds to pages offset
        # In real drawing sets, the sheet index often starts after cover/index pages
        # We match by detecting title blocks on each page
        page_assignments: dict[str, list[dict]] = {}

        for page in pages:
            tb = self.detect_title_block(page["text"])
            if tb:
                sn = tb["sheet_number"]
                if sn not in page_assignments:
                    page_assignments[sn] = []
                page_assignments[sn].append(page)

        for sheet in sheet_index:
            sn = sheet["sheet_number"]
            assigned_pages = page_assignments.get(sn, [])
            if assigned_pages:
                content = "\n".join(p["text"] for p in assigned_pages)
                page_nums = [p["page_number"] for p in assigned_pages]
                chunks.append({
                    "sheet_number": sn,
                    "title": sheet["title"],
                    "discipline": sheet["discipline"],
                    "content": content,
                    "page_start": min(page_nums),
                    "page_end": max(page_nums),
                })
            else:
                # Sheet listed in index but not found in pages
                chunks.append({
                    "sheet_number": sn,
                    "title": sheet["title"],
                    "discipline": sheet["discipline"],
                    "content": "",
                    "page_start": None,
                    "page_end": None,
                })

        return chunks
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_document_intelligence/test_drawing_parser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/document_intelligence/parsers/drawing_parser.py tests/test_document_intelligence/test_drawing_parser.py
git commit -m "feat(doc-intel): add drawing parser for sheet index and discipline inference"
```

---

## Task 6: Spec Validator (TOC-to-Content Cross-Validation)

**Files:**
- Create: `src/document_intelligence/validators/__init__.py`
- Create: `src/document_intelligence/validators/spec_validator.py`
- Test: `tests/test_document_intelligence/test_spec_validator.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_document_intelligence/test_spec_validator.py`:

```python
import pytest
from document_intelligence.validators.spec_validator import SpecValidator


@pytest.fixture
def validator():
    return SpecValidator()


class TestValidateSections:
    def test_matched_section(self, validator):
        toc_sections = [
            {"section_number": "09 21 16", "title": "GYPSUM BOARD", "page_number": 5},
        ]
        pages = {
            5: "SECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES\nPART 1 - GENERAL"
        }
        results = validator.validate_sections(toc_sections, pages)
        assert len(results) == 1
        assert results[0]["status"] == "matched"

    def test_mismatched_section(self, validator):
        toc_sections = [
            {"section_number": "09 21 16", "title": "GYPSUM BOARD", "page_number": 5},
        ]
        pages = {5: "SECTION 07 92 00 - JOINT SEALANTS\nPART 1 - GENERAL"}
        results = validator.validate_sections(toc_sections, pages)
        assert len(results) == 1
        assert results[0]["status"] == "mismatch"

    def test_page_not_found(self, validator):
        toc_sections = [
            {"section_number": "09 21 16", "title": "GYPSUM BOARD", "page_number": 999},
        ]
        pages = {1: "Some content"}
        results = validator.validate_sections(toc_sections, pages)
        assert len(results) == 1
        assert results[0]["status"] == "page_not_found"


class TestDetectPageOffset:
    def test_detect_offset(self, validator):
        toc_sections = [
            {"section_number": "09 21 16", "page_number": 100},
            {"section_number": "07 92 00", "page_number": 80},
        ]
        pages = {
            98: "SECTION 09 21 16 - GYPSUM BOARD",
            78: "SECTION 07 92 00 - JOINT SEALANTS",
        }
        offset = validator.detect_page_offset(toc_sections, pages)
        assert offset == -2

    def test_no_offset_needed(self, validator):
        toc_sections = [
            {"section_number": "09 21 16", "page_number": 10},
        ]
        pages = {10: "SECTION 09 21 16"}
        offset = validator.detect_page_offset(toc_sections, pages)
        assert offset == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_document_intelligence/test_spec_validator.py -v`
Expected: FAIL

- [ ] **Step 3: Implement SpecValidator**

Create `src/document_intelligence/validators/__init__.py`:

```python
# src/document_intelligence/validators/__init__.py
```

Create `src/document_intelligence/validators/spec_validator.py`:

```python
# src/document_intelligence/validators/spec_validator.py
"""
TOC-to-content cross-validation for spec books.

Verifies that sections listed in the TOC actually exist at the specified
pages. Detects and auto-corrects consistent page offset issues (printed
page numbers vs PDF page indices).
"""
import re
import logging
from collections import Counter
from typing import Optional

logger = logging.getLogger(__name__)

_CSI_PATTERN = re.compile(r"(\d{2}\s?\d{2}\s?\d{2})")


class SpecValidator:
    """Validate spec book TOC entries against actual page content."""

    def validate_sections(
        self,
        toc_sections: list[dict],
        pages: dict[int, str],
        page_offset: int = 0,
    ) -> list[dict]:
        """
        Cross-validate TOC sections against page content.

        Args:
            toc_sections: list of {section_number, title, page_number}
            pages: dict mapping page_number → page text
            page_offset: adjustment to apply to TOC page numbers

        Returns list of:
            {section_number, title, toc_page, actual_page, status}

        status: "matched" | "mismatch" | "page_not_found"
        """
        results = []
        for section in toc_sections:
            if section.get("page_number") is None:
                continue

            target_page = section["page_number"] + page_offset
            section_num = section["section_number"]
            normalized = re.sub(r"\s+", "", section_num)

            if target_page not in pages:
                results.append({
                    "section_number": section_num,
                    "title": section.get("title", ""),
                    "toc_page": section["page_number"],
                    "actual_page": target_page,
                    "status": "page_not_found",
                })
                continue

            page_text = pages[target_page]
            # Check if the section number appears on the target page
            found_numbers = _CSI_PATTERN.findall(page_text)
            page_normalized = [re.sub(r"\s+", "", n) for n in found_numbers]

            if normalized in page_normalized:
                results.append({
                    "section_number": section_num,
                    "title": section.get("title", ""),
                    "toc_page": section["page_number"],
                    "actual_page": target_page,
                    "status": "matched",
                })
            else:
                results.append({
                    "section_number": section_num,
                    "title": section.get("title", ""),
                    "toc_page": section["page_number"],
                    "actual_page": target_page,
                    "status": "mismatch",
                })

        return results

    def detect_page_offset(
        self,
        toc_sections: list[dict],
        pages: dict[int, str],
        search_range: int = 10,
    ) -> int:
        """
        Detect a consistent page offset between TOC page numbers and PDF indices.

        Tries offsets from -search_range to +search_range and picks the one
        that produces the most section matches.

        Returns: the best offset (0 if no clear winner).
        """
        best_offset = 0
        best_matches = 0

        for offset in range(-search_range, search_range + 1):
            match_count = 0
            for section in toc_sections:
                if section.get("page_number") is None:
                    continue
                target = section["page_number"] + offset
                if target not in pages:
                    continue
                normalized = re.sub(r"\s+", "", section["section_number"])
                found = _CSI_PATTERN.findall(pages[target])
                if normalized in [re.sub(r"\s+", "", n) for n in found]:
                    match_count += 1

            if match_count > best_matches:
                best_matches = match_count
                best_offset = offset

        return best_offset

    def generate_report(self, validation_results: list[dict]) -> dict:
        """
        Summarise validation results.

        Returns:
            {total, matched, mismatched, not_found, match_rate}
        """
        counts = Counter(r["status"] for r in validation_results)
        total = len(validation_results)
        return {
            "total": total,
            "matched": counts.get("matched", 0),
            "mismatched": counts.get("mismatch", 0),
            "not_found": counts.get("page_not_found", 0),
            "match_rate": round(counts.get("matched", 0) / total, 3) if total else 0.0,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_document_intelligence/test_spec_validator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/document_intelligence/validators/ tests/test_document_intelligence/test_spec_validator.py
git commit -m "feat(doc-intel): add spec validator for TOC-to-content cross-validation"
```

---

## Task 7: Drawing Validator (Index-to-Sheet Reconciliation)

**Files:**
- Create: `src/document_intelligence/validators/drawing_validator.py`
- Test: `tests/test_document_intelligence/test_drawing_validator.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_document_intelligence/test_drawing_validator.py`:

```python
import pytest
from document_intelligence.validators.drawing_validator import DrawingValidator


@pytest.fixture
def validator():
    return DrawingValidator()


class TestReconcile:
    def test_all_matched(self, validator):
        index_sheets = [
            {"sheet_number": "A1.0", "title": "SITE PLAN"},
            {"sheet_number": "A2.1", "title": "FLOOR PLAN"},
        ]
        detected_sheets = ["A1.0", "A2.1"]

        results = validator.reconcile(index_sheets, detected_sheets)
        assert results["matched"] == ["A1.0", "A2.1"]
        assert results["index_only"] == []
        assert results["document_only"] == []

    def test_index_only(self, validator):
        index_sheets = [
            {"sheet_number": "A1.0", "title": "SITE PLAN"},
            {"sheet_number": "A2.1", "title": "FLOOR PLAN"},
        ]
        detected_sheets = ["A1.0"]

        results = validator.reconcile(index_sheets, detected_sheets)
        assert results["matched"] == ["A1.0"]
        assert results["index_only"] == ["A2.1"]

    def test_document_only(self, validator):
        index_sheets = [
            {"sheet_number": "A1.0", "title": "SITE PLAN"},
        ]
        detected_sheets = ["A1.0", "A3.0"]

        results = validator.reconcile(index_sheets, detected_sheets)
        assert results["document_only"] == ["A3.0"]

    def test_empty_index(self, validator):
        results = validator.reconcile([], ["A1.0"])
        assert results["document_only"] == ["A1.0"]
        assert results["matched"] == []


class TestVerificationStatus:
    def test_assign_status(self, validator):
        reconciliation = {
            "matched": ["A1.0"],
            "index_only": ["A2.1"],
            "document_only": ["A3.0"],
        }
        assert validator.get_verification_status("A1.0", reconciliation) == "matched"
        assert validator.get_verification_status("A2.1", reconciliation) == "index_only"
        assert validator.get_verification_status("A3.0", reconciliation) == "document_only"
        assert validator.get_verification_status("X9.9", reconciliation) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_document_intelligence/test_drawing_validator.py -v`
Expected: FAIL

- [ ] **Step 3: Implement DrawingValidator**

Create `src/document_intelligence/validators/drawing_validator.py`:

```python
# src/document_intelligence/validators/drawing_validator.py
"""
Drawing set index-to-sheet reconciliation.

Compares sheets listed in the sheet index against sheets actually detected
in the PDF via title block parsing. Classifies each sheet as:
  matched       — in both index and PDF
  index_only    — in index but not found in PDF
  document_only — in PDF but not in index
"""
import logging

logger = logging.getLogger(__name__)


class DrawingValidator:
    """Reconcile drawing sheet index against detected sheets."""

    def reconcile(
        self,
        index_sheets: list[dict],
        detected_sheet_numbers: list[str],
    ) -> dict:
        """
        Compare index entries against detected sheet numbers.

        Args:
            index_sheets: list of {sheet_number, title, ...} from the sheet index
            detected_sheet_numbers: list of sheet numbers found via title block detection

        Returns:
            {matched: [...], index_only: [...], document_only: [...]}
        """
        index_set = {s["sheet_number"] for s in index_sheets}
        detected_set = set(detected_sheet_numbers)

        matched = sorted(index_set & detected_set)
        index_only = sorted(index_set - detected_set)
        document_only = sorted(detected_set - index_set)

        return {
            "matched": matched,
            "index_only": index_only,
            "document_only": document_only,
        }

    def get_verification_status(
        self, sheet_number: str, reconciliation: dict
    ) -> str:
        """Return the verification status for a sheet number."""
        if sheet_number in reconciliation.get("matched", []):
            return "matched"
        if sheet_number in reconciliation.get("index_only", []):
            return "index_only"
        if sheet_number in reconciliation.get("document_only", []):
            return "document_only"
        return ""

    def generate_report(self, reconciliation: dict) -> dict:
        """
        Summarise reconciliation results.

        Returns:
            {total, matched, index_only, document_only, match_rate}
        """
        matched = len(reconciliation.get("matched", []))
        index_only = len(reconciliation.get("index_only", []))
        document_only = len(reconciliation.get("document_only", []))
        total = matched + index_only + document_only
        return {
            "total": total,
            "matched": matched,
            "index_only": index_only,
            "document_only": document_only,
            "match_rate": round(matched / total, 3) if total else 0.0,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_document_intelligence/test_drawing_validator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/document_intelligence/validators/drawing_validator.py tests/test_document_intelligence/test_drawing_validator.py
git commit -m "feat(doc-intel): add drawing validator for index-to-sheet reconciliation"
```

---

## Task 8: KG Client Extensions (SpecSection/DrawingSheet Methods)

**Files:**
- Modify: `src/knowledge_graph/client.py` — Add new MERGE methods at end (before `kg_client = ...`)
- Modify: `src/knowledge_graph/models.py` — Add `DrawingSheet` dataclass
- Modify: `src/knowledge_graph/schema.py` — Add `DrawingSheet` constraint + vector index

- [ ] **Step 1: Add DrawingSheet to models.py**

In `src/knowledge_graph/models.py`, add after the `SpecSection` dataclass:

```python
@dataclass
class DrawingSheet:
    """A drawing sheet from a project's drawing set."""
    sheet_number: str
    project_id: str = ""
    title: str = ""
    discipline: str = ""
    source_doc_id: str = ""
    content_summary: str = ""
    chunk_id: str = ""
    embedding: list[float] = field(default_factory=list)
    embedding_model: str = ""
```

And add to `NODE_REGISTRY`:

```python
    DrawingSheet:       ("DrawingSheet",        "sheet_number"),
```

- [ ] **Step 2: Add DrawingSheet constraint and vector index to schema.py**

In `src/knowledge_graph/schema.py`, add to `CONSTRAINTS` list:

```python
    "CREATE CONSTRAINT drawing_sheet_unique IF NOT EXISTS FOR (n:DrawingSheet) REQUIRE (n.sheet_number, n.project_id) IS NODE KEY",
```

Add to `VECTOR_INDEXES` list:

```python
    """CREATE VECTOR INDEX drawing_sheet_embeddings IF NOT EXISTS
   FOR (n:DrawingSheet) ON (n.embedding)
   OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}""",
```

- [ ] **Step 3: Add KG client methods for SpecSection/DrawingSheet upsert**

In `src/knowledge_graph/client.py`, add before the `kg_client = KnowledgeGraphClient()` line:

```python
    # ------------------------------------------------------------------
    # Document Intelligence — SpecSection / DrawingSheet enrichment
    # ------------------------------------------------------------------

    def upsert_spec_section(self, section_data: dict, project_id: str) -> None:
        """
        MERGE a project-specific SpecSection node and link to its CADocument.

        Required keys: section_number, title, project_id, source_doc_id,
                       page_range, content_summary, embedding, chunk_id
        """
        if not self._driver:
            return

        def _do():
            with self._session() as session:
                session.run(
                    """
                    MERGE (s:SpecSection {section_number: $section_number, project_id: $project_id})
                    SET s.title           = $title,
                        s.source_doc_id   = $source_doc_id,
                        s.page_range      = $page_range,
                        s.content_summary = $content_summary,
                        s.embedding       = $embedding,
                        s.embedding_model = $embedding_model,
                        s.chunk_id        = $chunk_id
                    """,
                    **section_data,
                )
                # Link to source CADocument
                if section_data.get("source_doc_id"):
                    session.run(
                        """
                        MATCH (d:CADocument {doc_id: $doc_id})
                        MATCH (s:SpecSection {section_number: $section_number, project_id: $project_id})
                        MERGE (d)-[:HAS_SECTION]->(s)
                        """,
                        doc_id=section_data["source_doc_id"],
                        section_number=section_data["section_number"],
                        project_id=project_id,
                    )

        self._run_with_retry(_do)

    def upsert_drawing_sheet(self, sheet_data: dict, project_id: str) -> None:
        """
        CREATE/MERGE a DrawingSheet node and link to its CADocument.

        Required keys: sheet_number, title, discipline, project_id,
                       source_doc_id, content_summary, embedding, chunk_id
        """
        if not self._driver:
            return

        def _do():
            with self._session() as session:
                session.run(
                    """
                    MERGE (ds:DrawingSheet {sheet_number: $sheet_number, project_id: $project_id})
                    SET ds.title           = $title,
                        ds.discipline      = $discipline,
                        ds.source_doc_id   = $source_doc_id,
                        ds.content_summary = $content_summary,
                        ds.embedding       = $embedding,
                        ds.embedding_model = $embedding_model,
                        ds.chunk_id        = $chunk_id
                    """,
                    **sheet_data,
                )
                if sheet_data.get("source_doc_id"):
                    session.run(
                        """
                        MATCH (d:CADocument {doc_id: $doc_id})
                        MATCH (ds:DrawingSheet {sheet_number: $sheet_number, project_id: $project_id})
                        MERGE (d)-[:HAS_SHEET]->(ds)
                        """,
                        doc_id=sheet_data["source_doc_id"],
                        sheet_number=sheet_data["sheet_number"],
                        project_id=project_id,
                    )

        self._run_with_retry(_do)

    def create_cross_reference(
        self,
        from_label: str,
        from_key: str,
        from_value: str,
        rel_type: str,
        to_label: str,
        to_key: str,
        to_value: str,
        project_id: str,
    ) -> None:
        """
        Create a cross-reference relationship between nodes.

        Used for REFERENCES_DRAWING, REFERENCES_SPEC, COORDINATES_WITH.
        """
        if not self._driver:
            return

        def _do():
            with self._session() as session:
                session.run(
                    f"""
                    MATCH (a:{from_label} {{{from_key}: $from_val, project_id: $project_id}})
                    MATCH (b:{to_label} {{{to_key}: $to_val, project_id: $project_id}})
                    MERGE (a)-[:{rel_type}]->(b)
                    """,
                    from_val=from_value,
                    to_val=to_value,
                    project_id=project_id,
                )

        self._run_with_retry(_do)
```

- [ ] **Step 4: Commit**

```bash
git add src/knowledge_graph/client.py src/knowledge_graph/models.py src/knowledge_graph/schema.py
git commit -m "feat(doc-intel): add KG client methods for SpecSection/DrawingSheet upsert"
```

---

## Task 9: Agent Query Interface

**Files:**
- Create: `src/document_intelligence/query.py`
- Test: `tests/test_document_intelligence/test_query.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_document_intelligence/test_query.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_document_intelligence/test_query.py -v`
Expected: FAIL

- [ ] **Step 3: Implement DocumentQuery**

Create `src/document_intelligence/query.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_document_intelligence/test_query.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/document_intelligence/query.py tests/test_document_intelligence/test_query.py
git commit -m "feat(doc-intel): add agent-facing query interface for document chunks"
```

---

## Task 10: Service Orchestrator

**Files:**
- Create: `src/document_intelligence/service.py`
- Test: `tests/test_document_intelligence/test_service.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_document_intelligence/test_service.py`:

```python
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
    @patch("document_intelligence.service.PdfExtractor")
    @patch("document_intelligence.service.BookmarkParser")
    @patch("document_intelligence.service.SpecParser")
    @patch("document_intelligence.service.SpecValidator")
    def test_process_spec_book_creates_chunks(
        self, MockValidator, MockParser, MockBookmark, MockExtractor, service, store
    ):
        # Setup mocks
        mock_extractor = MockExtractor.return_value
        mock_extractor.get_page_count.return_value = 2
        mock_extractor.extract_pages.return_value = [
            {"page_number": 1, "text": "TOC content", "extraction_method": "pypdf", "char_count": 100, "flagged": False},
            {"page_number": 2, "text": "SECTION 09 21 16 - GYPSUM BOARD\nContent here", "extraction_method": "pypdf", "char_count": 200, "flagged": False},
        ]

        mock_bookmark = MockBookmark.return_value
        mock_bookmark.find_toc_bookmark.return_value = {"title": "TOC", "page_number": 0}

        mock_parser = MockParser.return_value
        mock_parser.parse_toc_lines.return_value = [
            {"section_number": "09 21 16", "title": "GYPSUM BOARD", "page_number": 2, "division": "09"},
        ]
        mock_parser.split_pages_by_sections.return_value = [
            {"section_number": "09 21 16", "title": "GYPSUM BOARD", "division": "09",
             "content": "Full section text", "page_start": 2, "page_end": 2},
        ]

        mock_validator = MockValidator.return_value
        mock_validator.detect_page_offset.return_value = 0
        mock_validator.validate_sections.return_value = [
            {"section_number": "09 21 16", "status": "matched"},
        ]
        mock_validator.generate_report.return_value = {"total": 1, "matched": 1}

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_document_intelligence/test_service.py -v`
Expected: FAIL

- [ ] **Step 3: Implement DocumentIntelligenceService**

Create `src/document_intelligence/service.py`:

```python
# src/document_intelligence/service.py
"""
Document Intelligence Service — pipeline orchestrator.

Coordinates the full processing pipeline:
  1. Register document in SQLite
  2. Extract text page-by-page (pypdf + OCR fallback)
  3. Detect structure (TOC for specs, sheet index for drawings)
  4. Validate structure (cross-reference TOC/index with actual content)
  5. Create chunks in SQLite
  6. Enrich Knowledge Graph with SpecSection/DrawingSheet nodes
  7. Finalize document status
"""
import json
import logging
import re
from typing import Optional

from ai_engine.engine import engine
from ai_engine.models import AIRequest, CapabilityClass

from document_intelligence.extractors.pdf_extractor import PdfExtractor
from document_intelligence.extractors.bookmark_parser import BookmarkParser
from document_intelligence.parsers.spec_parser import SpecParser
from document_intelligence.parsers.drawing_parser import DrawingParser
from document_intelligence.validators.spec_validator import SpecValidator
from document_intelligence.validators.drawing_validator import DrawingValidator
from document_intelligence.storage.chunk_store import ChunkStore

logger = logging.getLogger(__name__)

# Keywords to classify document type from filename
_SPEC_KEYWORDS = {"spec", "specification", "project manual", "technical spec"}
_DRAWING_KEYWORDS = {"drawing", "plan", "sheet", "dwg", "architectural", "structural"}

# Cross-reference patterns in text
_DRAWING_REF_RE = re.compile(r"(?:See |Refer to |Per )?(?:Drawing |Sheet |Dwg\.?\s*)([A-Z]{1,2}\d+(?:\.\d+)?)", re.IGNORECASE)
_SPEC_REF_RE = re.compile(r"(?:See |Refer to |Per )?(?:Section |Spec\.?\s*)(\d{2}\s?\d{2}\s?\d{2})", re.IGNORECASE)


class DocumentIntelligenceService:
    """Orchestrate document processing pipeline."""

    def __init__(
        self,
        chunk_store: ChunkStore,
        kg_client=None,
    ):
        self._store = chunk_store
        self._kg = kg_client
        self._extractor = PdfExtractor()
        self._bookmark_parser = BookmarkParser()
        self._spec_parser = SpecParser()
        self._drawing_parser = DrawingParser()
        self._spec_validator = SpecValidator()
        self._drawing_validator = DrawingValidator()

    def classify_document(self, filename: str) -> Optional[str]:
        """Classify a document as spec_book or drawing_set from its filename."""
        lower = filename.lower()
        for kw in _SPEC_KEYWORDS:
            if kw in lower:
                return "spec_book"
        for kw in _DRAWING_KEYWORDS:
            if kw in lower:
                return "drawing_set"
        return None

    def process_document(
        self,
        project_id: str,
        pdf_path: str,
        file_name: str,
        doc_type: str,
        neo4j_doc_id: str,
    ) -> dict:
        """
        Process a single PDF document through the full pipeline.

        Args:
            project_id:   Project ID (e.g. "11900")
            pdf_path:     Local path to the PDF file
            file_name:    Original filename
            doc_type:     "spec_book" or "drawing_set"
            neo4j_doc_id: Corresponding CADocument.doc_id in Neo4j

        Returns:
            {document_id, status, chunks_created, errors}
        """
        # Skip if already indexed
        if self._store.is_document_indexed(neo4j_doc_id):
            logger.info(f"Skipping already-indexed document: {file_name}")
            return {"document_id": None, "status": "skipped", "chunks_created": 0, "errors": []}

        errors = []

        # Step 1: Register document
        total_pages = self._extractor.get_page_count(pdf_path)
        import os
        file_size = os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0

        doc_id = self._store.register_document(
            project_id=project_id,
            file_path=pdf_path,
            file_name=file_name,
            doc_type=doc_type,
            total_pages=total_pages,
            file_size_bytes=file_size,
            neo4j_doc_id=neo4j_doc_id,
        )

        # Step 2: Extract pages
        pages = self._extractor.extract_pages(pdf_path)
        if not pages:
            self._store.finalize_document(doc_id, status="failed")
            return {"document_id": doc_id, "status": "failed", "chunks_created": 0,
                    "errors": ["No pages extracted"]}

        # Log extraction results
        for page in pages:
            self._store.log_page_extraction(
                document_id=doc_id,
                page_number=page["page_number"],
                extraction_method=page["extraction_method"],
                char_count=page["char_count"],
                flagged=page["flagged"],
            )

        # Step 3-5: Process by type
        if doc_type == "spec_book":
            chunks_created = self._process_spec_book(doc_id, project_id, pdf_path, pages, neo4j_doc_id, errors)
        elif doc_type == "drawing_set":
            chunks_created = self._process_drawing_set(doc_id, project_id, pdf_path, pages, neo4j_doc_id, errors)
        else:
            self._store.finalize_document(doc_id, status="failed")
            return {"document_id": doc_id, "status": "failed", "chunks_created": 0,
                    "errors": [f"Unknown doc_type: {doc_type}"]}

        # Step 7: Finalize
        status = "indexed" if chunks_created > 0 else "failed"
        self._store.finalize_document(doc_id, status=status)

        return {
            "document_id": doc_id,
            "status": status,
            "chunks_created": chunks_created,
            "errors": errors,
        }

    def _process_spec_book(
        self, doc_id: str, project_id: str, pdf_path: str,
        pages: list[dict], neo4j_doc_id: str, errors: list,
    ) -> int:
        """Process a spec book: detect TOC, validate, chunk, enrich KG."""
        chunks_created = 0

        # Try bookmark-first TOC detection
        toc_bookmark = self._bookmark_parser.find_toc_bookmark(pdf_path)
        toc_pages_text = []

        if toc_bookmark:
            boundaries = self._bookmark_parser.get_section_boundaries(pdf_path)
            # Get text from TOC pages
            toc_start = toc_bookmark["page_number"]
            for page in pages:
                pg = page["page_number"] - 1  # 0-based
                if pg >= toc_start:
                    toc_pages_text.append(page["text"])
                    # Stop at next major section
                    if pg > toc_start + 20:
                        break

        if not toc_pages_text:
            # Fallback: scan first 30 pages for TOC-like content
            for page in pages[:30]:
                toc_pages_text.append(page["text"])

        # Parse TOC lines
        all_lines = []
        for text in toc_pages_text:
            all_lines.extend(text.split("\n"))
        toc_sections = self._spec_parser.parse_toc_lines(all_lines)

        if not toc_sections:
            # Pattern-matching fallback: scan all pages for section headers
            for page in pages:
                headers = self._spec_parser.detect_section_headers(page["text"])
                for h in headers:
                    h["page_number"] = page["page_number"]
                    toc_sections.append(h)

        if not toc_sections:
            errors.append("No spec sections detected via TOC or pattern matching")
            return 0

        # Validate & detect page offset
        page_text_map = {p["page_number"]: p["text"] for p in pages}
        page_offset = self._spec_validator.detect_page_offset(toc_sections, page_text_map)
        validation_results = self._spec_validator.validate_sections(
            toc_sections, page_text_map, page_offset
        )
        validation_report = self._spec_validator.generate_report(validation_results)

        # Split pages into section chunks
        section_chunks = self._spec_parser.split_pages_by_sections(
            pages, toc_sections, page_offset
        )

        # Create chunks and enrich KG
        for chunk_data in section_chunks:
            # Generate summary
            summary = self._generate_summary(chunk_data["content"][:3000], chunk_data["title"])
            # Generate embedding
            embedding = self._generate_embedding(summary)

            # Find verification status
            v_status = "matched"
            for vr in validation_results:
                if vr["section_number"] == chunk_data["section_number"]:
                    v_status = vr["status"]
                    break

            chunk_id = self._store.add_chunk(
                document_id=doc_id,
                project_id=project_id,
                chunk_type="spec_section",
                identifier=chunk_data["section_number"],
                title=chunk_data["title"],
                content=chunk_data["content"],
                content_summary=summary,
                page_start=chunk_data["page_start"],
                page_end=chunk_data["page_end"],
                division=chunk_data["division"],
                verification_status=v_status,
            )
            chunks_created += 1

            # Enrich KG
            if self._kg:
                self._kg.upsert_spec_section({
                    "section_number": chunk_data["section_number"],
                    "title": chunk_data["title"],
                    "project_id": project_id,
                    "source_doc_id": neo4j_doc_id,
                    "page_range": f"pages {chunk_data['page_start']}-{chunk_data['page_end']}",
                    "content_summary": summary,
                    "embedding": embedding,
                    "embedding_model": "text-embedding",
                    "chunk_id": chunk_id,
                }, project_id)

        # Parse cross-references
        if self._kg:
            self._create_cross_references(section_chunks, project_id)

        return chunks_created

    def _process_drawing_set(
        self, doc_id: str, project_id: str, pdf_path: str,
        pages: list[dict], neo4j_doc_id: str, errors: list,
    ) -> int:
        """Process a drawing set: detect sheet index, validate, chunk, enrich KG."""
        chunks_created = 0

        # Try bookmark-first sheet index detection
        index_bookmark = self._bookmark_parser.find_sheet_index_bookmark(pdf_path)
        index_text_lines = []

        if index_bookmark:
            idx_page = index_bookmark["page_number"]
            for page in pages:
                pg = page["page_number"] - 1
                if pg >= idx_page and pg <= idx_page + 5:
                    index_text_lines.extend(page["text"].split("\n"))
        else:
            # Scan first 10 pages
            for page in pages[:10]:
                index_text_lines.extend(page["text"].split("\n"))

        sheet_index = self._drawing_parser.parse_sheet_index_lines(index_text_lines)

        # Detect title blocks on every page
        detected_sheets = []
        for page in pages:
            tb = self._drawing_parser.detect_title_block(page["text"])
            if tb:
                detected_sheets.append(tb["sheet_number"])

        # Validate
        if sheet_index:
            reconciliation = self._drawing_validator.reconcile(sheet_index, detected_sheets)
            recon_report = self._drawing_validator.generate_report(reconciliation)
        else:
            # No index found — use detected sheets directly
            reconciliation = {"matched": [], "index_only": [], "document_only": detected_sheets}
            recon_report = self._drawing_validator.generate_report(reconciliation)
            # Build sheet_index from detected sheets
            sheet_index = [
                {"sheet_number": sn, "title": "", "discipline": self._drawing_parser.infer_discipline(sn)}
                for sn in detected_sheets
            ]

        self._store.finalize_document(doc_id, status="processing", reconciliation_summary=recon_report)

        # Split pages by sheets
        sheet_chunks = self._drawing_parser.split_pages_by_sheets(pages, sheet_index)

        for chunk_data in sheet_chunks:
            summary = self._generate_summary(
                chunk_data["content"][:3000] if chunk_data["content"] else "",
                f"Drawing Sheet {chunk_data['sheet_number']}: {chunk_data['title']}",
            )
            embedding = self._generate_embedding(summary)
            v_status = self._drawing_validator.get_verification_status(
                chunk_data["sheet_number"], reconciliation
            )

            chunk_id = self._store.add_chunk(
                document_id=doc_id,
                project_id=project_id,
                chunk_type="drawing_sheet",
                identifier=chunk_data["sheet_number"],
                title=chunk_data["title"],
                content=chunk_data.get("content", ""),
                content_summary=summary,
                page_start=chunk_data.get("page_start"),
                page_end=chunk_data.get("page_end"),
                discipline=chunk_data["discipline"],
                verification_status=v_status,
            )
            chunks_created += 1

            if self._kg:
                self._kg.upsert_drawing_sheet({
                    "sheet_number": chunk_data["sheet_number"],
                    "title": chunk_data["title"],
                    "discipline": chunk_data["discipline"],
                    "project_id": project_id,
                    "source_doc_id": neo4j_doc_id,
                    "content_summary": summary,
                    "embedding": embedding,
                    "embedding_model": "text-embedding",
                    "chunk_id": chunk_id,
                }, project_id)

        return chunks_created

    def _generate_summary(self, content: str, title: str) -> str:
        """Generate a 2-3 sentence summary via AI."""
        if not content.strip():
            return f"{title} (no extractable text)"
        try:
            request = AIRequest(
                capability_class=CapabilityClass.EXTRACT,
                system_prompt=(
                    "Summarize the following construction document section in 2-3 sentences. "
                    "Focus on what it specifies, requires, or shows."
                ),
                user_prompt=f"TITLE: {title}\n\nCONTENT:\n{content}",
                temperature=0.0,
                calling_agent="doc_intelligence",
                task_id=f"summary-{title[:20]}",
            )
            response = engine.generate_response(request)
            return response.content.strip()
        except Exception as e:
            logger.warning(f"Summary generation failed for {title}: {e}")
            return f"{title}"

    def _generate_embedding(self, text: str) -> list[float]:
        """Generate embedding for content summary."""
        try:
            return engine.generate_embedding(text)
        except Exception as e:
            logger.warning(f"Embedding generation failed: {e}")
            return []

    def _create_cross_references(
        self, chunks: list[dict], project_id: str
    ) -> None:
        """Parse cross-references from chunk content and create KG relationships."""
        for chunk in chunks:
            content = chunk.get("content", "")
            section_num = chunk.get("section_number", "")

            # Find drawing references
            for match in _DRAWING_REF_RE.finditer(content):
                sheet_ref = match.group(1).upper()
                self._kg.create_cross_reference(
                    from_label="SpecSection",
                    from_key="section_number",
                    from_value=section_num,
                    rel_type="REFERENCES_DRAWING",
                    to_label="DrawingSheet",
                    to_key="sheet_number",
                    to_value=sheet_ref,
                    project_id=project_id,
                )

            # Find spec references (from one section to another)
            for match in _SPEC_REF_RE.finditer(content):
                ref_num = self._spec_parser._normalize_section_number(match.group(1))
                if ref_num != section_num:
                    self._kg.create_cross_reference(
                        from_label="SpecSection",
                        from_key="section_number",
                        from_value=section_num,
                        rel_type="REFERENCES_SPEC",
                        to_label="SpecSection",
                        to_key="section_number",
                        to_value=ref_num,
                        project_id=project_id,
                    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_document_intelligence/test_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/document_intelligence/service.py tests/test_document_intelligence/test_service.py
git commit -m "feat(doc-intel): add service orchestrator for full processing pipeline"
```

---

## Task 11: Processing Script

**Files:**
- Create: `scripts/process_project_documents.py`

- [ ] **Step 1: Implement the CLI script**

Create `scripts/process_project_documents.py`:

```python
#!/usr/bin/env python
"""
Process project spec books and drawing sets into the Document Intelligence
content store (SQLite) and enrich the Knowledge Graph (Neo4j).

Usage:
    python scripts/process_project_documents.py                    # all projects
    python scripts/process_project_documents.py --project 11900    # single project
    python scripts/process_project_documents.py --dry-run          # preview only
    python scripts/process_project_documents.py --db-path ./chunks.db  # custom DB path

Reads CADocument nodes from Neo4j to find spec books and drawing sets,
downloads PDFs from Google Drive, and processes them.
"""
import argparse
import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config.local_config import LocalConfig
LocalConfig.ensure_exists().push_to_env()

from knowledge_graph.client import KnowledgeGraphClient
from integrations.drive.service import DriveService
from document_intelligence.storage.chunk_store import ChunkStore
from document_intelligence.service import DocumentIntelligenceService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("process_documents")

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "document_intelligence.db"
)

# Pilot projects
PILOT_PROJECTS = ["11900", "12333", "12556", "12660", "12757"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process project spec books and drawing sets."
    )
    parser.add_argument("--project", type=str, help="Single project ID to process")
    parser.add_argument("--dry-run", action="store_true", help="Preview without processing")
    parser.add_argument("--db-path", type=str, default=DEFAULT_DB_PATH, help="SQLite DB path")
    args = parser.parse_args()

    project_ids = [args.project] if args.project else PILOT_PROJECTS

    # Initialize services
    kg = KnowledgeGraphClient()
    drive = DriveService()
    store = ChunkStore(args.db_path)
    service = DocumentIntelligenceService(chunk_store=store, kg_client=kg)

    total_stats = {"processed": 0, "skipped": 0, "failed": 0, "chunks": 0}

    for project_id in project_ids:
        print(f"\n{'='*60}")
        print(f"Project: {project_id}")
        print(f"{'='*60}")

        # Get CADocument nodes that look like spec books or drawing sets
        docs = kg.get_project_documents(project_id)
        candidates = []
        for doc in docs:
            doc_type = service.classify_document(doc.get("filename", ""))
            if doc_type:
                candidates.append((doc, doc_type))

        if not candidates:
            print(f"  No spec books or drawing sets found for project {project_id}")
            continue

        for doc, doc_type in candidates:
            filename = doc.get("filename", "unknown")
            doc_id = doc.get("doc_id", "")
            drive_file_id = doc.get("drive_file_id", "")

            if args.dry_run:
                print(f"  [DRY RUN] {filename} -> {doc_type}")
                total_stats["processed"] += 1
                continue

            # Download PDF to temp file
            print(f"  Processing: {filename} ({doc_type})...")
            try:
                content, mime = drive.download_file(drive_file_id)
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                    f.write(content)
                    tmp_path = f.name

                result = service.process_document(
                    project_id=project_id,
                    pdf_path=tmp_path,
                    file_name=filename,
                    doc_type=doc_type,
                    neo4j_doc_id=doc_id,
                )

                if result["status"] == "indexed":
                    print(f"    ✓ {result['chunks_created']} chunks created")
                    total_stats["processed"] += 1
                    total_stats["chunks"] += result["chunks_created"]
                elif result["status"] == "skipped":
                    print(f"    - Already indexed, skipping")
                    total_stats["skipped"] += 1
                else:
                    print(f"    ✗ Failed: {result['errors']}")
                    total_stats["failed"] += 1

            except Exception as e:
                print(f"    ✗ Error: {e}")
                total_stats["failed"] += 1
            finally:
                try:
                    os.unlink(tmp_path)
                except (OSError, UnboundLocalError):
                    pass

    # Summary
    print(f"\n{'='*60}")
    print(f"Summary: {total_stats['processed']} processed, "
          f"{total_stats['chunks']} chunks created, "
          f"{total_stats['skipped']} skipped, "
          f"{total_stats['failed']} failed")

    store.close()
    kg.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add scripts/process_project_documents.py
git commit -m "feat(doc-intel): add standalone processing script for project documents"
```

---

## Task 12: Update Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add new dependencies**

Add a new optional dependency group in `pyproject.toml`:

```toml
# Document Intelligence — optional; for spec book / drawing set processing
doc-intel = [
    "pytesseract>=0.3.10",
    "Pillow>=10.0.0",
    "pdf2image>=1.16.0",
]
```

And update the `all` group:

```toml
all = [
    "app[cloud]",
    "app[kg]",
    "app[doc-intel]",
]
```

Note: `sqlite-vss` is deferred — it requires platform-specific C extensions and can be added later when vector search on chunks is needed. The current implementation uses keyword search as a functional starting point.

- [ ] **Step 2: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add doc-intel optional dependencies (pytesseract, Pillow, pdf2image)"
```

---

## Task 13: Update Module Init and Exports

**Files:**
- Modify: `src/document_intelligence/__init__.py`

- [ ] **Step 1: Update the module init**

Update `src/document_intelligence/__init__.py`:

```python
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
```

- [ ] **Step 2: Final commit**

```bash
git add src/document_intelligence/__init__.py
git commit -m "feat(doc-intel): finalize module exports"
```

---

## Verification

After all tasks are complete, verify the full system:

1. **Run all document intelligence tests:**
   ```bash
   uv run pytest tests/test_document_intelligence/ -v
   ```

2. **Test with a real spec book (if available):**
   ```bash
   python scripts/process_project_documents.py --project 11900 --dry-run
   ```

3. **Verify SQLite store manually:**
   ```bash
   python -c "
   from document_intelligence.storage.chunk_store import ChunkStore
   store = ChunkStore('data/document_intelligence.db')
   print(store.list_documents('11900'))
   "
   ```

4. **Verify KG enrichment (Neo4j Browser):**
   ```cypher
   MATCH (d:CADocument)-[:HAS_SECTION]->(s:SpecSection)
   RETURN d.filename, s.section_number, s.title LIMIT 10;

   MATCH (d:CADocument)-[:HAS_SHEET]->(ds:DrawingSheet)
   RETURN d.filename, ds.sheet_number, ds.discipline LIMIT 10;

   MATCH (s:SpecSection)-[:REFERENCES_DRAWING]->(ds:DrawingSheet)
   RETURN s.section_number, ds.sheet_number LIMIT 10;
   ```
