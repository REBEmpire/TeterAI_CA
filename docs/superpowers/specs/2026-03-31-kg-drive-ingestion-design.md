# Knowledge Graph Implementation & Drive Ingestion — Design Spec

| Field | Value |
|-------|-------|
| Date | 2026-03-31 |
| Status | Approved |
| Related Specs | TETER-CA-AI-KG-001, TETER-CA-AI-INT-DRIVE-001 |

---

## Context

The Knowledge Graph (Neo4j Aura) is provisioned and the schema is defined in `specs/phase-0/TETER-CA-AI-KG-001_Knowledge-Graph-Architecture.md`, but `src/knowledge_graph/` is entirely empty. The Dispatcher Agent (which is implemented and running) already references the KG for playbook rules, but there is nothing in Neo4j to query.

Additionally, the 5 pilot projects have real existing CA documents in their Google Drive folders (`Teter AI Prototype/` root) that contain institutional knowledge the agents need to work with — past RFIs, meeting minutes, submittals, etc.

This spec covers:
1. Implementing `src/knowledge_graph/` (the `KnowledgeGraphClient` and supporting modules)
2. Seeding the KG with Tier 1/2/4 baseline data (playbooks, workflow rules, industry standards)
3. Building a Drive-to-KG ingestion pipeline to extract and graph the existing project documents

---

## Architecture

Three deliverables, in build order:

```
src/knowledge_graph/
├── __init__.py
├── models.py          ← Python dataclasses for all KG node types (Tiers 1–4 + Project Layer)
├── schema.py          ← Neo4j constraint/index setup, MERGE helpers
├── client.py          ← KnowledgeGraphClient (the interface agents call)
└── ingestion.py       ← DriveToKGIngester service

scripts/
├── setup_kg_schema.py        ← idempotent: creates constraints + vector indexes in Neo4j
├── seed_kg_baseline.py       ← Tier 1 (playbooks) + Tier 2 (workflows) + Tier 4 (CSI/AIA)
└── ingest_drive_to_kg.py     ← crawls Drive project folders, AI-extracts, writes nodes
```

**Data flow (ingestion):**
```
Google Drive (project folders)
        │
        ▼
DriveToKGIngester
  ├── list files per project folder (skips 04 - Agent Workspace)
  ├── download + extract text (pdfplumber / Drive export / python-docx)
  ├── AI extraction (AIEngine — same pattern as RFIExtractor)
  ├── generate embedding for summary field
  └── write to Neo4j via KnowledgeGraphClient (MERGE, idempotent)
```

---

## Extended Schema

The existing 4-tier schema from KG-001 is preserved. A **Project Document Layer** is added, extending Tier 3.

### New Node Types

```cypher
(:Project {
  project_id: String,           // "11900", "12333", etc.
  project_number: String,
  name: String,
  phase: String,                // "construction" | "bid" | "closeout"
  drive_root_folder_id: String
})

(:CADocument {
  doc_id: String,               // "{project_id}_{doc_type}_{doc_number}"
  drive_file_id: String,        // Google Drive file ID — idempotency key
  filename: String,
  drive_folder_path: String,    // "02 - Construction/RFIs"
  doc_type: String,             // "RFI" | "SUBMITTAL" | "MEETING_MINUTES" | etc.
  doc_number: String,           // "RFI-045" (null if unknown)
  phase: String,
  date_submitted: String,       // ISO date string
  date_responded: String,       // ISO date string (null if open)
  summary: String,              // AI-generated 1–2 sentence summary
  embedding: [Float],           // semantic search vector
  embedding_model: String,
  embedding_updated_at: DateTime,
  metadata_only: Boolean        // true if text extraction failed (scanned PDF, DWG, etc.)
})

(:Party {
  party_id: String,             // slugified name, e.g. "turner-construction"
  name: String,
  type: String                  // "contractor" | "owner" | "consultant"
})
```

### New Relationships

```cypher
(:Project)-[:HAS_DOCUMENT]->(:CADocument)
(:CADocument)-[:SUBMITTED_BY]->(:Party)
(:CADocument)-[:REFERENCES_SPEC]->(:SpecSection)   // links to Tier 4
(:CADocument)-[:RELATES_TO]->(:CADocument)          // sibling docs (RFI → CO, etc.)
(:Project)-[:INVOLVES_PARTY]->(:Party)
```

### New Vector Index

| Index Name | Node Label | Property |
|-----------|-----------|---------|
| `ca_document_embeddings` | CADocument | embedding |

---

## Baseline Seed Data (Tier 1, 2, 4)

All seed writes use `MERGE` on the node's ID property — safe to re-run.

### Tier 2 — Workflow Process

- 10 `DocumentType` nodes: RFI, SUBMITTAL, SUB_REQ, PCO_COR, BULLETIN, CHANGE_ORDER, PAY_APP, MEETING_MINUTES, PB_RFI, ADDENDUM — with numbering prefixes and response deadline days (RFI: 10, SUBMITTAL: 14)
- `WorkflowStep` chain for RFI: Receipt → Acknowledge → Route to Architect → Draft Response → CA Review → Issue → Close
- Placeholder single-step workflows for all other document types

### Tier 4 — Industry Knowledge

- 16 CSI MasterFormat division `SpecSection` nodes (Division 01–16): division number, title, brief keyword summary. Division-level only (full section text is out of scope per KG-001 open question #2).
- 3 AIA A201 `ContractClause` nodes: §3.2 (Contractor's Review of Contract Documents), §4.3 (Claims and Disputes), §9.3 (Applications for Payment)

### Tier 1 — Agent Playbooks

- `Agent` node for `AGENT-DISPATCH-001` with `PlaybookRule` nodes encoding the classification confidence thresholds and routing decision rules from `TETER-CA-AI-AGT-DISPATCH-001`
- `Agent` node for `AGENT-RFI-001` with `PlaybookRule` nodes encoding the extraction and response drafting rules from the RFI spec
- `EscalationCriteria` nodes linked to each agent for the escalation triggers

---

## Ingestion Pipeline (Drive → KG)

### `DriveToKGIngester.ingest_project(project_id)`

1. Resolve project's Drive root folder ID from Firestore (`drive_folders/{project_id}`)
2. Recursively list all files, excluding `04 - Agent Workspace/` subtree
3. For each file:
   - **Skip if** a `CADocument` node with this `drive_file_id` already exists (idempotency)
   - Infer document type from folder path (e.g., file in `02 - Construction/RFIs/` → `RFI`)
   - Extract text:
     - PDFs → `pdfplumber`; if < 50 chars extracted, mark `metadata_only=True`
     - Google Docs → Drive API export as `text/plain`
     - DOCX → `python-docx`
     - Other (DWG, images, etc.) → `metadata_only=True`
   - AI extraction via `AIEngine` (temperature=0.0, `CapabilityClass.EXTRACT`):
     - doc_number, contractor_name, dates, key question/decision, spec section references
     - 1–2 sentence summary
   - Generate embedding for `summary`
   - `MERGE` `:CADocument`, `:Party`, and relationships in Neo4j
   - Log to audit trail

### CLI Runner (`scripts/ingest_drive_to_kg.py`)

Same pattern as `seed_drive_folders.py`:

```
python scripts/ingest_drive_to_kg.py                    # all 5 pilot projects
python scripts/ingest_drive_to_kg.py --project 11900    # single project
python scripts/ingest_drive_to_kg.py --dry-run          # preview without writes
```

Progress output per document with ✓ / ⚠ indicators.

---

## KnowledgeGraphClient Interface

Implements the interface defined in KG-001 §8, plus new project-layer methods:

```python
class KnowledgeGraphClient:
    # KG-001 interface (intelligence layer)
    def get_agent_playbook(self, agent_id: str) -> list[PlaybookRule]: ...
    def search_spec_sections(self, query: str, top_k: int = 5) -> list[SpecSection]: ...
    def get_document_workflow(self, doc_type: str) -> list[WorkflowStep]: ...
    def get_contract_clause(self, clause_id: str) -> ContractClause: ...
    def log_correction(self, correction: CorrectionEvent) -> None: ...

    # Project document layer (new)
    def get_project_documents(self, project_id: str, doc_type: str = None) -> list[CADocument]: ...
    def search_project_documents(self, query: str, project_id: str = None, top_k: int = 5) -> list[CADocument]: ...
    def upsert_document(self, doc: CADocument, project_id: str) -> None: ...
    def upsert_party(self, party: Party) -> None: ...
```

Uses `neo4j` Python driver (already in `.venv` via existing requirements).

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| PDF text extraction < 50 chars | Store as `metadata_only=True`; log WARNING; continue |
| AI extraction parse error | Log ERROR; store metadata-only CADocument; continue |
| Drive API 403 | Log CRITICAL; skip file; continue with remaining files |
| Drive API 429 | Exponential backoff (3 retries); skip on exhaustion |
| Neo4j write failure | Log CRITICAL; retry 3x; abort project if unresolved |
| File already in graph | Skip silently (idempotent) |

---

## Verification

1. Run `python scripts/setup_kg_schema.py` — verify constraints and indexes exist in Neo4j console
2. Run `python scripts/seed_kg_baseline.py --dry-run` then without `--dry-run` — verify node counts
3. Run `python scripts/ingest_drive_to_kg.py --project 11900 --dry-run` then live — verify CADocument nodes appear in Neo4j
4. Query: `MATCH (p:Project {project_id: '11900'})-[:HAS_DOCUMENT]->(d:CADocument) RETURN d.doc_type, count(*) ORDER BY count(*) DESC` — should show doc type distribution
5. Query: `CALL db.index.vector.queryNodes('ca_document_embeddings', 3, $vec)` — verify semantic search returns results

---

## Files to Create

| File | Purpose |
|------|---------|
| `src/knowledge_graph/__init__.py` | Package init |
| `src/knowledge_graph/models.py` | Dataclasses for all node types |
| `src/knowledge_graph/schema.py` | Constraint/index setup, Cypher MERGE helpers |
| `src/knowledge_graph/client.py` | KnowledgeGraphClient implementation |
| `src/knowledge_graph/ingestion.py` | DriveToKGIngester service |
| `scripts/setup_kg_schema.py` | CLI: apply constraints and indexes |
| `scripts/seed_kg_baseline.py` | CLI: Tier 1/2/4 seed data |
| `scripts/ingest_drive_to_kg.py` | CLI: Drive → KG ingestion runner |

## Files to Modify

| File | Change |
|------|--------|
| `specs/phase-0/TETER-CA-AI-KG-001_Knowledge-Graph-Architecture.md` | Add Project Document Layer section (new node types + relationships) |
