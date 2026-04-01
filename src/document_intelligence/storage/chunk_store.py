"""
ChunkStore — Thread-safe SQLite client for the Document Intelligence content store.

Manages three tables: documents, chunks, processing_log.
Follows the same threading patterns used in src/db/sqlite/client.py:
  - threading.Lock() for write safety
  - threading.local() for per-thread connections
  - WAL journal mode, foreign keys ON, synchronous NORMAL
"""
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class ChunkStore:
    """
    Thread-safe SQLite client for the Document Intelligence content store.

    All write operations are guarded by a lock.
    Each thread gets its own connection via threading.local() so read-heavy
    concurrent workloads don't serialize unnecessarily.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = str(Path(db_path).expanduser())
        self._lock = threading.Lock()
        self._local = threading.local()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        """Return (or create) the per-thread SQLite connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self) -> None:
        schema_path = Path(__file__).parent / "schema.sql"
        schema = schema_path.read_text()
        conn = self._conn()
        conn.executescript(schema)
        conn.commit()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        return dict(row)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the current thread's connection."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # ------------------------------------------------------------------
    # Document operations
    # ------------------------------------------------------------------

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
        """
        Register a document for processing.

        Idempotent by neo4j_doc_id: if a document with the same neo4j_doc_id
        already exists, returns its existing id without creating a new row.

        Returns the document UUID (str).
        """
        # Check idempotency first (read, no lock needed)
        existing = self._find_document_by_neo4j_id(neo4j_doc_id)
        if existing is not None:
            return existing["id"]

        doc_id = str(uuid.uuid4())
        with self._lock:
            # Double-check inside the lock to prevent a race between two
            # concurrent register calls for the same neo4j_doc_id.
            existing = self._find_document_by_neo4j_id(neo4j_doc_id)
            if existing is not None:
                return existing["id"]

            self._conn().execute(
                """
                INSERT INTO documents
                    (id, project_id, file_path, file_name, doc_type,
                     total_pages, file_size_bytes, status, neo4j_doc_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'processing', ?)
                """,
                (doc_id, project_id, file_path, file_name, doc_type,
                 total_pages, file_size_bytes, neo4j_doc_id),
            )
            self._conn().commit()
        return doc_id

    def _find_document_by_neo4j_id(self, neo4j_doc_id: str) -> Optional[dict]:
        row = self._conn().execute(
            "SELECT * FROM documents WHERE neo4j_doc_id = ?",
            (neo4j_doc_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_document(self, doc_id: str) -> Optional[dict]:
        """Return a document by its UUID, or None if not found."""
        row = self._conn().execute(
            "SELECT * FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def is_document_indexed(self, neo4j_doc_id: str) -> bool:
        """Return True if a document with this neo4j_doc_id has status='indexed'."""
        row = self._conn().execute(
            "SELECT status FROM documents WHERE neo4j_doc_id = ?",
            (neo4j_doc_id,),
        ).fetchone()
        return row is not None and row["status"] == "indexed"

    def finalize_document(
        self,
        doc_id: str,
        status: str,
        reconciliation_summary: Optional[str] = None,
    ) -> None:
        """
        Update a document's status and optional reconciliation_summary.
        Sets indexed_at only when status == 'indexed'.
        """
        indexed_at = (
            datetime.now(timezone.utc).isoformat()
            if status == "indexed"
            else None
        )
        with self._lock:
            self._conn().execute(
                """
                UPDATE documents
                SET status = ?,
                    reconciliation_summary = ?,
                    indexed_at = ?
                WHERE id = ?
                """,
                (status, reconciliation_summary, indexed_at, doc_id),
            )
            self._conn().commit()

    def list_documents(self, project_id: str) -> list[dict]:
        """Return all documents for a project, ordered by created_at."""
        rows = self._conn().execute(
            "SELECT * FROM documents WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Chunk operations
    # ------------------------------------------------------------------

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
        metadata_json: Optional[str] = None,
        verification_status: str = "",
        embedding: Optional[bytes] = None,
    ) -> str:
        """
        Insert a new chunk record.

        Returns the chunk UUID (str).
        """
        chunk_id = str(uuid.uuid4())
        if metadata_json is None:
            metadata_json = "{}"
        with self._lock:
            self._conn().execute(
                """
                INSERT INTO chunks
                    (id, document_id, project_id, chunk_type, identifier,
                     title, content, content_summary, page_start, page_end,
                     discipline, division, metadata_json, verification_status,
                     embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (chunk_id, document_id, project_id, chunk_type, identifier,
                 title, content, content_summary, page_start, page_end,
                 discipline, division, metadata_json, verification_status,
                 embedding),
            )
            self._conn().commit()
        return chunk_id

    def get_chunk(self, chunk_id: str) -> Optional[dict]:
        """Return a chunk by its UUID, or None if not found."""
        row = self._conn().execute(
            "SELECT * FROM chunks WHERE id = ?",
            (chunk_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_chunks_by_document(self, document_id: str) -> list[dict]:
        """Return all chunks for a document, ordered by page_start."""
        rows = self._conn().execute(
            """
            SELECT * FROM chunks
            WHERE document_id = ?
            ORDER BY page_start
            """,
            (document_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_chunk_by_identifier(
        self, project_id: str, identifier: str
    ) -> Optional[dict]:
        """Return the first chunk matching (project_id, identifier), or None."""
        row = self._conn().execute(
            "SELECT * FROM chunks WHERE project_id = ? AND identifier = ? LIMIT 1",
            (project_id, identifier),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    # ------------------------------------------------------------------
    # Processing log operations
    # ------------------------------------------------------------------

    def log_page_extraction(
        self,
        document_id: str,
        page_number: int,
        extraction_method: str,
        char_count: int,
        flagged: bool = False,
    ) -> None:
        """Record the outcome of extracting text from a single PDF page."""
        log_id = str(uuid.uuid4())
        with self._lock:
            self._conn().execute(
                """
                INSERT INTO processing_log
                    (id, document_id, page_number, extraction_method,
                     char_count, flagged)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (log_id, document_id, page_number, extraction_method,
                 char_count, int(flagged)),
            )
            self._conn().commit()

    def get_processing_log(self, document_id: str) -> list[dict]:
        """Return all processing log entries for a document, ordered by page_number."""
        rows = self._conn().execute(
            """
            SELECT * FROM processing_log
            WHERE document_id = ?
            ORDER BY page_number
            """,
            (document_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]
