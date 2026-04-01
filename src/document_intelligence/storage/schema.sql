-- Document Intelligence Service — SQLite schema
-- Stores full text of spec sections and drawing sheets extracted from PDFs.
-- This is a standalone database separate from the main app SQLite store.

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA synchronous=NORMAL;

-- ---------------------------------------------------------------------------
-- documents: one row per PDF file registered for processing
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id                      TEXT PRIMARY KEY,
    project_id              TEXT NOT NULL,
    file_path               TEXT NOT NULL,
    file_name               TEXT NOT NULL,
    doc_type                TEXT NOT NULL CHECK (doc_type IN ('spec_book', 'drawing_set')),
    total_pages             INT  DEFAULT 0,
    file_size_bytes         INT  DEFAULT 0,
    status                  TEXT NOT NULL DEFAULT 'processing'
                                CHECK (status IN ('processing', 'indexed', 'failed')),
    neo4j_doc_id            TEXT,
    reconciliation_summary  TEXT,
    indexed_at              TIMESTAMP,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_documents_project   ON documents(project_id);
CREATE INDEX IF NOT EXISTS idx_documents_neo4j_id  ON documents(neo4j_doc_id);

-- ---------------------------------------------------------------------------
-- chunks: individual spec sections or drawing sheets
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chunks (
    id                  TEXT PRIMARY KEY,
    document_id         TEXT NOT NULL REFERENCES documents(id),
    project_id          TEXT NOT NULL,
    chunk_type          TEXT NOT NULL CHECK (chunk_type IN ('spec_section', 'drawing_sheet')),
    identifier          TEXT NOT NULL,
    title               TEXT DEFAULT '',
    content             TEXT DEFAULT '',
    content_summary     TEXT DEFAULT '',
    page_start          INT,
    page_end            INT,
    discipline          TEXT DEFAULT '',
    division            TEXT DEFAULT '',
    metadata_json       TEXT DEFAULT '{}',
    verification_status TEXT DEFAULT ''
                            CHECK (verification_status IN ('', 'matched', 'index_only', 'document_only')),
    embedding           BLOB,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_project_id  ON chunks(project_id);
CREATE INDEX IF NOT EXISTS idx_chunks_identifier  ON chunks(identifier);

-- ---------------------------------------------------------------------------
-- processing_log: one row per page, records how text was extracted
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS processing_log (
    id                  TEXT PRIMARY KEY,
    document_id         TEXT NOT NULL REFERENCES documents(id),
    page_number         INT  NOT NULL,
    extraction_method   TEXT NOT NULL CHECK (extraction_method IN ('pypdf', 'ocr', 'failed')),
    char_count          INT  DEFAULT 0,
    flagged             BOOLEAN DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_processing_log_document_id ON processing_log(document_id);
