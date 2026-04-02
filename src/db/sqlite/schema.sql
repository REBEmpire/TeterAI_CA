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
    project_number TEXT NOT NULL DEFAULT '',
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

-- ---------------------------------------------------------------------------
-- Closeout checklist — per spec-section deliverable tracking
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- Closeout deficiencies — deficiency notices per checklist item
-- ---------------------------------------------------------------------------
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



-- ---------------------------------------------------------------------------
-- Grading Sessions — tracks multi-model analysis grading
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS grading_sessions (
    session_id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL,
    document_id TEXT,
    document_name TEXT,
    status TEXT DEFAULT 'pending',
    weights TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_grading_sessions_analysis 
    ON grading_sessions(analysis_id);
CREATE INDEX IF NOT EXISTS idx_grading_sessions_status 
    ON grading_sessions(status);
CREATE INDEX IF NOT EXISTS idx_grading_sessions_created 
    ON grading_sessions(created_at);

-- ---------------------------------------------------------------------------
-- Model Grades — AI and human grades for model responses
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS model_grades (
    grade_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    tier INTEGER NOT NULL,
    source TEXT NOT NULL,
    accuracy_score REAL,
    accuracy_reasoning TEXT,
    accuracy_evidence TEXT DEFAULT '[]',
    completeness_score REAL,
    completeness_reasoning TEXT,
    completeness_evidence TEXT DEFAULT '[]',
    relevance_score REAL,
    relevance_reasoning TEXT,
    relevance_evidence TEXT DEFAULT '[]',
    citation_quality_score REAL,
    citation_quality_reasoning TEXT,
    citation_quality_evidence TEXT DEFAULT '[]',
    overall_score REAL NOT NULL,
    grader_id TEXT,
    graded_at TEXT NOT NULL,
    notes TEXT DEFAULT '',
    FOREIGN KEY (session_id) REFERENCES grading_sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_model_grades_session 
    ON model_grades(session_id);
CREATE INDEX IF NOT EXISTS idx_model_grades_source 
    ON model_grades(source);
CREATE INDEX IF NOT EXISTS idx_model_grades_model 
    ON model_grades(model_id);

-- ---------------------------------------------------------------------------
-- Divergence Analyses — AI vs Human grade comparison
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS divergence_analyses (
    analysis_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    ai_grade_id TEXT NOT NULL,
    human_grade_id TEXT NOT NULL,
    criterion_divergences TEXT DEFAULT '[]',
    overall_ai_score REAL NOT NULL,
    overall_human_score REAL NOT NULL,
    overall_difference REAL NOT NULL,
    overall_level TEXT NOT NULL,
    analyzed_at TEXT NOT NULL,
    calibration_notes TEXT DEFAULT '',
    action_items TEXT DEFAULT '[]',
    FOREIGN KEY (session_id) REFERENCES grading_sessions(session_id),
    FOREIGN KEY (ai_grade_id) REFERENCES model_grades(grade_id),
    FOREIGN KEY (human_grade_id) REFERENCES model_grades(grade_id)
);

CREATE INDEX IF NOT EXISTS idx_divergence_session 
    ON divergence_analyses(session_id);
CREATE INDEX IF NOT EXISTS idx_divergence_level 
    ON divergence_analyses(overall_level);
CREATE INDEX IF NOT EXISTS idx_divergence_analyzed 
    ON divergence_analyses(analyzed_at);
