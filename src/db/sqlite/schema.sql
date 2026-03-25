-- TeterAI CA — SQLite schema (desktop/local mode)
-- All Firestore collections are mapped to tables here.
-- Timestamps: ISO 8601 strings. Complex nested fields: JSON blobs.

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ---------------------------------------------------------------------------
-- Tasks
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    ingest_id TEXT,
    project_id TEXT,
    project_number TEXT,
    document_type TEXT,
    document_number TEXT,
    phase TEXT,
    urgency TEXT DEFAULT 'LOW',
    status TEXT NOT NULL,
    assigned_agent TEXT,
    assigned_reviewer TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status_history TEXT DEFAULT '[]',
    classification_confidence TEXT,
    source_email TEXT,
    attachments TEXT DEFAULT '[]',
    draft_local_path TEXT,
    final_local_path TEXT,
    draft_content TEXT,
    draft_version TEXT,
    draft_edited INTEGER DEFAULT 0,
    confidence_score REAL,
    citations TEXT DEFAULT '[]',
    referenced_specs TEXT DEFAULT '[]',
    referenced_drawings TEXT DEFAULT '[]',
    review_flag TEXT,
    error_message TEXT,
    correction_captured INTEGER DEFAULT 0,
    sender_name TEXT,
    subject TEXT,
    approved_by TEXT,
    approved_at TEXT,
    rejected_by TEXT,
    rejected_at TEXT,
    rejection_reason TEXT,
    rejection_notes TEXT,
    escalated_by TEXT,
    escalated_at TEXT,
    escalation_notes TEXT,
    delivered_at TEXT,
    agent_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_number);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);

-- ---------------------------------------------------------------------------
-- Email ingests
-- ---------------------------------------------------------------------------
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
    source TEXT DEFAULT 'manual'
);

CREATE INDEX IF NOT EXISTS idx_ingests_status ON email_ingests(status);

-- ---------------------------------------------------------------------------
-- Audit logs — append-only
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_logs (
    log_id TEXT PRIMARY KEY,
    log_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    task_id TEXT,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_logs(task_id);
CREATE INDEX IF NOT EXISTS idx_audit_type_ts ON audit_logs(log_type, timestamp);

-- Denormalized task-scoped index (mirrors audit_logs_by_task Firestore collection)
CREATE TABLE IF NOT EXISTS audit_logs_by_task (
    task_id TEXT PRIMARY KEY,
    log_ids TEXT DEFAULT '[]'
);

-- ---------------------------------------------------------------------------
-- Thought chains
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS thought_chains (
    task_id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Submittal reviews
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS submittal_reviews (
    task_id TEXT PRIMARY KEY,
    project_id TEXT,
    model_results TEXT NOT NULL DEFAULT '{}',
    selected_items TEXT DEFAULT '{}',
    status TEXT DEFAULT 'PENDING_SELECTION',
    approved_by TEXT,
    approved_at TEXT,
    created_at TEXT
);

-- ---------------------------------------------------------------------------
-- RFI log
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rfi_log (
    doc_id TEXT PRIMARY KEY,
    rfi_number_internal TEXT,
    rfi_number_submitted TEXT,
    project_id TEXT,
    contractor_name TEXT,
    question_summary TEXT,
    status TEXT,
    date_staged TEXT,
    date_responded TEXT,
    task_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_rfi_project ON rfi_log(project_id);

-- ---------------------------------------------------------------------------
-- Per-project document counters (replaces Firestore doc_counters subcollection)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS doc_counters (
    project_id TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    count INTEGER DEFAULT 0,
    PRIMARY KEY (project_id, doc_type)
);

-- ---------------------------------------------------------------------------
-- Projects
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phase TEXT DEFAULT 'BID',
    known_senders TEXT DEFAULT '[]',
    local_root_path TEXT,
    created_at TEXT,
    active INTEGER DEFAULT 1
);

-- ---------------------------------------------------------------------------
-- Local folder registry (replaces Firestore drive_folders)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS folder_registry (
    project_id TEXT NOT NULL,
    folder_path TEXT NOT NULL,
    local_path TEXT NOT NULL,
    PRIMARY KEY (project_id, folder_path)
);

-- ---------------------------------------------------------------------------
-- Users
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    uid TEXT PRIMARY KEY,
    email TEXT,
    display_name TEXT,
    role TEXT DEFAULT 'CA_STAFF',
    active INTEGER DEFAULT 1,
    created_at TEXT
);

-- ---------------------------------------------------------------------------
-- Processed email deduplication
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS processed_emails (
    message_id TEXT PRIMARY KEY,
    processed_at TEXT,
    task_id TEXT
);

-- ---------------------------------------------------------------------------
-- Model registry (singleton)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS model_registry (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version TEXT,
    updated_at TEXT,
    config TEXT NOT NULL
);
