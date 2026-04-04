"""
SQLiteClient — local database backend for desktop mode.

Exposes a Firestore-compatible fluent API via CollectionRef so that
agent code using db.collection("X").document("Y").get() routes through
to SQLite with minimal changes at each call site.
"""
import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fluent Firestore-compatibility shims
# ---------------------------------------------------------------------------

class DocumentSnapshot:
    """Mimics google.cloud.firestore.DocumentSnapshot."""

    def __init__(self, doc_id: str, data: Optional[dict]):
        self.id = doc_id
        self._data = data
        self.exists = data is not None

    def to_dict(self) -> dict:
        return dict(self._data) if self._data else {}

    def get(self, key: str, default=None):
        return (self._data or {}).get(key, default)


class QuerySnapshot:
    """Returned by CollectionRef.stream()."""

    def __init__(self, docs: list[DocumentSnapshot]):
        self.docs = docs

    def __iter__(self) -> Iterator[DocumentSnapshot]:
        return iter(self.docs)


class DocumentRef:
    """Mimics google.cloud.firestore.DocumentReference."""

    def __init__(self, client: "SQLiteClient", collection: str, doc_id: str):
        self._client = client
        self._collection = collection
        self._doc_id = doc_id

    def get(self, transaction=None) -> DocumentSnapshot:
        data = self._client._get_doc(self._collection, self._doc_id)
        return DocumentSnapshot(self._doc_id, data)

    def set(self, data: dict, merge: bool = False) -> None:
        if merge:
            existing = self._client._get_doc(self._collection, self._doc_id) or {}
            # Handle firestore.ArrayUnion-style values
            merged = dict(existing)
            for k, v in data.items():
                if isinstance(v, _ArrayUnion):
                    existing_list = merged.get(k, [])
                    merged[k] = list(dict.fromkeys(existing_list + v.values))
                else:
                    merged[k] = v
            data = merged
        self._client._upsert_doc(self._collection, self._doc_id, data)

    def update(self, updates: dict) -> None:
        existing = self._client._get_doc(self._collection, self._doc_id)
        if existing is None:
            existing = {}
        for k, v in updates.items():
            if isinstance(v, _ArrayUnion):
                existing_list = existing.get(k, [])
                existing[k] = list(dict.fromkeys(existing_list + v.values))
            else:
                existing[k] = v
        self._client._upsert_doc(self._collection, self._doc_id, existing)

    def delete(self) -> None:
        self._client._delete_doc(self._collection, self._doc_id)

    def collection(self, name: str) -> "CollectionRef":
        """Support subcollection syntax: doc_ref.collection('sub')."""
        return CollectionRef(self._client, f"{self._collection}/{self._doc_id}/{name}")


class _ArrayUnion:
    """Shim for firestore.ArrayUnion()."""
    def __init__(self, values: list):
        self.values = values


class CollectionQuery:
    """Chainable query builder — mirrors Firestore query API."""

    def __init__(self, client: "SQLiteClient", collection: str, filters: list, limit_val: Optional[int] = None, order_field: Optional[str] = None):
        self._client = client
        self._collection = collection
        self._filters = filters  # list of (field, op, value)
        self._limit_val = limit_val
        self._order_field = order_field

    def where(self, field: str, op: str, value) -> "CollectionQuery":
        return CollectionQuery(
            self._client, self._collection,
            self._filters + [(field, op, value)],
            self._limit_val, self._order_field
        )

    def order_by(self, field: str) -> "CollectionQuery":
        return CollectionQuery(
            self._client, self._collection,
            self._filters, self._limit_val, field
        )

    def limit(self, n: int) -> "CollectionQuery":
        return CollectionQuery(
            self._client, self._collection,
            self._filters, n, self._order_field
        )

    def stream(self) -> Iterator[DocumentSnapshot]:
        rows = self._client._query_collection(
            self._collection, self._filters, self._limit_val, self._order_field
        )
        return iter(rows)


class CollectionRef:
    """Mimics google.cloud.firestore.CollectionReference."""

    def __init__(self, client: "SQLiteClient", collection: str):
        self._client = client
        self._collection = collection

    def document(self, doc_id: str) -> DocumentRef:
        return DocumentRef(self._client, self._collection, doc_id)

    def where(self, field: str, op: str, value) -> CollectionQuery:
        return CollectionQuery(self._client, self._collection, [(field, op, value)])

    def order_by(self, field: str) -> CollectionQuery:
        return CollectionQuery(self._client, self._collection, [], None, field)

    def limit(self, n: int) -> CollectionQuery:
        return CollectionQuery(self._client, self._collection, [], n, None)

    def stream(self) -> Iterator[DocumentSnapshot]:
        rows = self._client._query_collection(self._collection, [], None, None)
        return iter(rows)

    def add(self, data: dict):
        """Firestore-compatible add (auto-generated ID)."""
        import uuid
        doc_id = str(uuid.uuid4())
        self._client._upsert_doc(self._collection, doc_id, data)
        return None, DocumentRef(self._client, self._collection, doc_id)


# ---------------------------------------------------------------------------
# Main client
# ---------------------------------------------------------------------------

# Tables that store one JSON blob per document, keyed by a primary key column.
# Maps collection name → (table_name, pk_column).
_COLLECTION_TABLE_MAP = {
    "tasks": ("tasks", "task_id"),
    "email_ingests": ("email_ingests", "ingest_id"),
    "audit_logs": ("audit_logs", "log_id"),
    "audit_logs_by_task": ("audit_logs_by_task", "task_id"),
    "thought_chains": ("thought_chains", "task_id"),
    "submittal_reviews": ("submittal_reviews", "task_id"),
    "rfi_log": ("rfi_log", "doc_id"),
    "doc_counters": ("doc_counters", "project_id"),  # composite PK handled specially
    "projects": ("projects", "project_id"),
    "drive_folders": ("folder_registry", "project_id"),  # Firestore alias → local table
    "folder_registry": ("folder_registry", "project_id"),
    "users": ("users", "uid"),
    "processed_emails": ("processed_emails", "message_id"),
    "ai_engine": ("model_registry", "id"),
    "closeout_checklist": ("closeout_checklist", "item_id"),
    "closeout_deficiencies": ("closeout_deficiencies", "deficiency_id"),
}


class SQLiteClient:
    """
    Thread-safe SQLite client with Firestore-compatible fluent API.
    Uses WAL journal mode to allow concurrent reads and writes.
    """

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
        schema_path = Path(__file__).parent / "schema.sql"
        conn = self._conn()

        # Fallback to robust inline schema if schema.sql isn't found (e.g. PyInstaller issue)
        if schema_path.exists():
            schema = schema_path.read_text()
            conn.executescript(schema)
            conn.commit()
        else:
            # Inline essential schema definitions
            inline_schema = """
CREATE TABLE IF NOT EXISTS email_ingests (
    ingest_id TEXT PRIMARY KEY,
    message_id TEXT,
    received_at TEXT,
    sender_email TEXT,
    sender_name TEXT,
    subject TEXT,
    body_text TEXT,
    body_text_truncated INTEGER DEFAULT 0,
    attachment_metadata TEXT DEFAULT '[]',
    subject_hints TEXT DEFAULT '{}',
    status TEXT DEFAULT 'PENDING_CLASSIFICATION',
    task_id TEXT,
    created_at TEXT,
    source TEXT DEFAULT 'manual',
    project_id TEXT,
    project_number TEXT,
    tool_type_hint TEXT,
    uploaded_by TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    ingest_id TEXT,
    status TEXT,
    assigned_agent TEXT,
    assigned_reviewer TEXT,
    created_at TEXT,
    updated_at TEXT,
    status_history TEXT DEFAULT '[]',
    project_id TEXT,
    project_number TEXT,
    document_type TEXT,
    document_number TEXT,
    phase TEXT,
    urgency TEXT,
    classification_confidence TEXT,
    error_message TEXT,
    correction_captured INTEGER DEFAULT 0,
    sender_name TEXT,
    subject TEXT,
    source_email TEXT,
    attachments TEXT,
    draft_drive_path TEXT,
    final_drive_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(assigned_agent);
CREATE INDEX IF NOT EXISTS idx_ingests_status ON email_ingests(status);
            """
            conn.executescript(inline_schema)
            conn.commit()

        self._run_migrations()

    def _run_migrations(self) -> None:
        """Apply incremental schema migrations for existing databases."""
        conn = self._conn()
        # Migration: add project_number column to projects table
        cursor = conn.execute("PRAGMA table_info(projects)")
        columns = {row[1] for row in cursor.fetchall()}
        if "project_number" not in columns:
            conn.execute("ALTER TABLE projects ADD COLUMN project_number TEXT NOT NULL DEFAULT ''")
            conn.commit()
            logger.info("Migration: added project_number column to projects table")

        # Migration: add upload-related columns to email_ingests
        cursor = conn.execute("PRAGMA table_info(email_ingests)")
        ei_columns = {row[1] for row in cursor.fetchall()}
        for col, defn in [
            ("project_id", "TEXT"),
            ("project_number", "TEXT"),
            ("tool_type_hint", "TEXT"),
            ("uploaded_by", "TEXT"),
        ]:
            if col not in ei_columns:
                conn.execute(f"ALTER TABLE email_ingests ADD COLUMN {col} {defn}")
                logger.info(f"Migration: added {col} column to email_ingests table")
        conn.commit()

        # Migration: add local_path column to processed_emails
        cursor = conn.execute("PRAGMA table_info(processed_emails)")
        pe_columns = {row[1] for row in cursor.fetchall()}
        if "local_path" not in pe_columns:
            conn.execute("ALTER TABLE processed_emails ADD COLUMN local_path TEXT")
            conn.commit()
            logger.info("Migration: added local_path column to processed_emails table")

        # Migration: create closeout tables if they don't exist
        existing_tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        if "closeout_checklist" not in existing_tables:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS closeout_checklist (
                    item_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    spec_section TEXT NOT NULL,
                    spec_title TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    label TEXT NOT NULL,
                    urgency TEXT DEFAULT 'MEDIUM',
                    status TEXT DEFAULT 'NOT_RECEIVED',
                    responsible_party TEXT,
                    document_path TEXT,
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    deficiency_notes TEXT,
                    notes TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    FOREIGN KEY (project_id) REFERENCES projects(project_id)
                );
                CREATE INDEX IF NOT EXISTS idx_closeout_project ON closeout_checklist(project_id);
                CREATE INDEX IF NOT EXISTS idx_closeout_status ON closeout_checklist(status);
                CREATE INDEX IF NOT EXISTS idx_closeout_spec ON closeout_checklist(spec_section);
            """)
            conn.commit()
            logger.info("Migration: created closeout_checklist table")
        if "closeout_deficiencies" not in existing_tables:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS closeout_deficiencies (
                    deficiency_id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    description TEXT NOT NULL,
                    severity TEXT DEFAULT 'MEDIUM',
                    status TEXT DEFAULT 'OPEN',
                    created_by TEXT,
                    created_at TEXT,
                    resolved_by TEXT,
                    resolved_at TEXT,
                    notes TEXT,
                    FOREIGN KEY (item_id) REFERENCES closeout_checklist(item_id),
                    FOREIGN KEY (project_id) REFERENCES projects(project_id)
                );
            """)
            conn.commit()
            logger.info("Migration: created closeout_deficiencies table")

    # ------------------------------------------------------------------
    # Generic document-store helpers (JSON blob per row)
    # ------------------------------------------------------------------

    def _resolve_collection(self, collection: str) -> tuple[str, str]:
        """Return (table_name, pk_column) for a Firestore collection name."""
        if collection in _COLLECTION_TABLE_MAP:
            return _COLLECTION_TABLE_MAP[collection]
        # Subcollection: "projects/{id}/doc_counters" style
        parts = collection.split("/")
        if len(parts) == 3 and parts[2] == "doc_counters":
            return ("doc_counters", "doc_type")
        logger.warning(f"Unknown collection '{collection}' — using generic blob table")
        return (collection, "id")

    def _upsert_doc(self, collection: str, doc_id: str, data: dict) -> None:
        table, pk = self._resolve_collection(collection)
        # Serialize any non-JSON-native values
        safe_data = _to_json_safe(data)
        conn = self._conn()

        if table == "audit_logs":
            # Flat columns for audit_logs to support indexed queries
            self._upsert_audit_log(conn, doc_id, data)
            return

        if table == "audit_logs_by_task":
            log_ids = data.get("logs", [])
            conn.execute(
                "INSERT INTO audit_logs_by_task(task_id, log_ids) VALUES(?,?) "
                "ON CONFLICT(task_id) DO UPDATE SET log_ids=excluded.log_ids",
                (doc_id, json.dumps(log_ids))
            )
            conn.commit()
            return

        # Generic: store entire document as JSON blob
        blob = json.dumps(safe_data)
        # Special handling for tables with named columns
        if table in ("tasks", "email_ingests", "projects", "submittal_reviews",
                     "rfi_log", "users", "thought_chains", "processed_emails",
                     "folder_registry", "closeout_checklist", "closeout_deficiencies"):
            self._upsert_named_table(conn, table, pk, doc_id, safe_data)
        elif table == "model_registry":
            conn.execute(
                "INSERT INTO model_registry(id, version, updated_at, config) VALUES(1,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET version=excluded.version, "
                "updated_at=excluded.updated_at, config=excluded.config",
                (data.get("version", ""), data.get("updated_at", ""), blob)
            )
            conn.commit()
        else:
            logger.warning(f"Unhandled table '{table}' for upsert; storing to blob fallback.")

    def _upsert_audit_log(self, conn: sqlite3.Connection, log_id: str, data: dict) -> None:
        task_id = data.get("task_id")
        log_type = data.get("log_type", "")
        timestamp = data.get("timestamp", datetime.now(timezone.utc).isoformat())
        if hasattr(timestamp, "isoformat"):
            timestamp = timestamp.isoformat()
        blob = json.dumps(_to_json_safe(data))
        conn.execute(
            "INSERT INTO audit_logs(log_id, log_type, timestamp, task_id, payload) "
            "VALUES(?,?,?,?,?) ON CONFLICT(log_id) DO NOTHING",
            (log_id, log_type, timestamp, task_id, blob)
        )
        conn.commit()

    def _upsert_named_table(self, conn: sqlite3.Connection, table: str, pk: str, doc_id: str, data: dict) -> None:
        """Build INSERT OR REPLACE from data dict for named-column tables."""
        # Merge with existing row to preserve unset columns
        existing = self._get_row_by_pk(conn, table, pk, doc_id)
        row = dict(existing) if existing else {}
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                row[k] = json.dumps(v)
            elif hasattr(v, "isoformat"):
                row[k] = v.isoformat()
            else:
                row[k] = v
        # Always set the PK
        row[pk] = doc_id

        columns = list(row.keys())
        placeholders = ",".join("?" for _ in columns)
        col_names = ",".join(columns)
        updates = ",".join(f"{c}=excluded.{c}" for c in columns if c != pk)

        try:
            conn.execute(
                f"INSERT INTO {table}({col_names}) VALUES({placeholders}) "
                f"ON CONFLICT({pk}) DO UPDATE SET {updates}",
                [row[c] for c in columns]
            )
            conn.commit()
        except Exception as e:
            logger.error(f"_upsert_named_table({table}) failed: {e}")
            conn.rollback()

    def _get_row_by_pk(self, conn: sqlite3.Connection, table: str, pk: str, doc_id: str) -> Optional[dict]:
        try:
            row = conn.execute(f"SELECT * FROM {table} WHERE {pk}=?", (doc_id,)).fetchone()
            return dict(row) if row else None
        except Exception:
            return None

    def _get_doc(self, collection: str, doc_id: str) -> Optional[dict]:
        table, pk = self._resolve_collection(collection)
        conn = self._conn()

        if table == "audit_logs_by_task":
            row = conn.execute("SELECT log_ids FROM audit_logs_by_task WHERE task_id=?", (doc_id,)).fetchone()
            if not row:
                return None
            return {"logs": json.loads(row["log_ids"])}

        if table == "model_registry":
            row = conn.execute("SELECT * FROM model_registry WHERE id=1").fetchone()
            if not row:
                return None
            return json.loads(row["config"])

        row = self._get_row_by_pk(conn, table, pk, doc_id)
        if row is None:
            return None
        return _row_to_dict(row)

    def _delete_doc(self, collection: str, doc_id: str) -> None:
        table, pk = self._resolve_collection(collection)
        conn = self._conn()
        conn.execute(f"DELETE FROM {table} WHERE {pk}=?", (doc_id,))
        conn.commit()

    def _query_collection(
        self,
        collection: str,
        filters: list,
        limit_val: Optional[int],
        order_field: Optional[str],
    ) -> list[DocumentSnapshot]:
        table, pk = self._resolve_collection(collection)
        conn = self._conn()

        if table == "audit_logs":
            return self._query_audit_logs(conn, filters, limit_val, order_field, pk)

        try:
            cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        except Exception:
            return []

        clauses, params = [], []
        for field, op, value in filters:
            if field not in cols:
                continue
            if op == "==" or op == "=":
                clauses.append(f"{field}=?")
                params.append(value)
            elif op == "in":
                placeholders = ",".join("?" for _ in value)
                clauses.append(f"{field} IN ({placeholders})")
                params.extend(value)
            elif op == ">=":
                clauses.append(f"{field}>=?")
                params.append(value)
            elif op == "<=":
                clauses.append(f"{field}<=?")
                params.append(value)
            elif op == ">":
                clauses.append(f"{field}>?")
                params.append(value)

        sql = f"SELECT * FROM {table}"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        if order_field and order_field in cols:
            sql += f" ORDER BY {order_field}"
        if limit_val:
            sql += f" LIMIT {limit_val}"

        try:
            rows = conn.execute(sql, params).fetchall()
        except Exception as e:
            logger.error(f"Query failed on {table}: {e}")
            return []

        result = []
        for row in rows:
            d = _row_to_dict(dict(row))
            doc_id = d.get(pk, "")
            result.append(DocumentSnapshot(doc_id, d))
        return result

    def _query_audit_logs(self, conn, filters, limit_val, order_field, pk) -> list[DocumentSnapshot]:
        clauses, params = [], []
        for field, op, value in filters:
            if field == "task_id":
                if op in ("==", "="):
                    clauses.append("task_id=?")
                    params.append(value)
            elif field == "log_type":
                if op in ("==", "="):
                    clauses.append("log_type=?")
                    params.append(value)
            elif field == "timestamp":
                if op == ">=":
                    ts = value.isoformat() if hasattr(value, "isoformat") else value
                    clauses.append("timestamp>=?")
                    params.append(ts)
            elif field == "agent_id":
                if op in ("==", "="):
                    clauses.append("json_extract(payload,'$.agent_id')=?")
                    params.append(value)
            elif field == "reviewer_uid":
                if op in ("==", "="):
                    clauses.append("json_extract(payload,'$.reviewer_uid')=?")
                    params.append(value)

        sql = "SELECT log_id, payload FROM audit_logs"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY timestamp"
        if limit_val:
            sql += f" LIMIT {limit_val}"

        try:
            rows = conn.execute(sql, params).fetchall()
        except Exception as e:
            logger.error(f"Audit log query failed: {e}")
            return []

        result = []
        for row in rows:
            data = json.loads(row["payload"])
            result.append(DocumentSnapshot(row["log_id"], data))
        return result

    # ------------------------------------------------------------------
    # Firestore-compatible top-level collection() method
    # ------------------------------------------------------------------

    def collection(self, name: str) -> CollectionRef:
        return CollectionRef(self, name)

    def transaction(self):
        """Return a no-op transaction handle (SQLite uses explicit locks instead)."""
        return _NoOpTransaction(self)

    # ------------------------------------------------------------------
    # Atomic counter (replaces Firestore @transactional)
    # ------------------------------------------------------------------

    def increment_counter(self, project_id: str, doc_type: str) -> int:
        """Atomically increment doc counter. Returns new count."""
        conn = self._conn()
        with self._lock:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT count FROM doc_counters WHERE project_id=? AND doc_type=?",
                    (project_id, doc_type)
                ).fetchone()
                new_count = (row["count"] + 1) if row else 1
                conn.execute(
                    "INSERT INTO doc_counters(project_id, doc_type, count) VALUES(?,?,?) "
                    "ON CONFLICT(project_id, doc_type) DO UPDATE SET count=excluded.count",
                    (project_id, doc_type, new_count)
                )
                conn.execute("COMMIT")
                return new_count
            except Exception:
                conn.execute("ROLLBACK")
                raise


class _NoOpTransaction:
    """Placeholder to allow @firestore.transactional-style code to degrade gracefully."""
    def __init__(self, client: SQLiteClient):
        self._client = client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_json_safe(obj):
    """Recursively convert non-JSON-native types."""
    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_json_safe(v) for v in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    # Firestore SERVER_TIMESTAMP sentinel
    if hasattr(obj, "_server_timestamp"):
        return datetime.now(timezone.utc).isoformat()
    return obj


def _row_to_dict(row: dict) -> dict:
    """Deserialize JSON columns in a SQLite row back to Python objects."""
    result = {}
    for k, v in row.items():
        if isinstance(v, str) and v and v[0] in ("{", "["):
            try:
                result[k] = json.loads(v)
            except json.JSONDecodeError:
                result[k] = v
        else:
            result[k] = v
    return result
