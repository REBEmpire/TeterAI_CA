# Document Intelligence Service — Design Spec

**Date:** 2026-04-01
**Status:** Approved
**Scope:** New module within TeterAI_CA for pre-processing large PDF spec books and drawing sets into searchable, agent-accessible chunks.

---

## Problem

TeterAI agents cannot effectively access the content of large project documents. Spec books run thousands of pages and drawing sets span hundreds of sheets. The current ingestion pipeline (`ingestion.py`) treats each PDF as a single unit — extracting all text, truncating to 3,000 characters for AI metadata extraction, and storing one `CADocument` node per file in Neo4j. The remaining 99% of content is invisible to agents.

The existing `SpecSection` nodes in the KG are 20 generic CSI division stubs, not project-specific sections with real content. Drawing sheets referenced in RFIs exist only as lightweight reference nodes, not as indexed content from actual drawing sets.

## Solution

A **Document Intelligence Service** that:

1. Pre-processes PDF spec books and drawing sets when added to a project
2. Chunks them intelligently by spec section or drawing sheet (not arbitrary character counts)
3. Stores full chunk text in SQLite (with sqlite-vss for vector search)
4. Enriches the Knowledge Graph with project-specific `SpecSection` and `DrawingSheet` nodes linked to chunks
5. Provides a query interface for agents to retrieve exactly the content they need

## Architecture

### Dual-Store Design

| Neo4j (Knowledge Graph) | SQLite (Content Store) |
|---|---|
| Knows what exists and how things relate | Stores actual full text content |
| Semantic search via embeddings on summaries | Keyword search + vector search via sqlite-vss |
| Graph traversal for cross-references | Serves pages/sections when agents request them |
| Lightweight: section numbers, titles, summaries, relationships | Full text: every word on every page |

A chunk's `chunk_id` in SQLite corresponds to a `SpecSection` or `DrawingSheet` node in Neo4j. Agents query the KG to find what they need, then fetch full text from SQLite.

### Integration with Existing Pipeline

The Document Intelligence Service runs as a **separate post-ingestion step**, not a modification to `ingestion.py`. This is intentional — `ingestion.py` is actively used for project seeding and must remain stable.

- A standalone script (`scripts/process_project_documents.py`) reads `CADocument` nodes from Neo4j, processes the corresponding PDFs, and writes chunks to SQLite + enriches the KG
- Idempotent — safe to re-run, skips already-processed documents
- Later, when ready, a single call can be added to `ingestion.py` to trigger processing inline

---

## Module Structure

```
src/document_intelligence/
  __init__.py
  service.py                # Orchestrator — coordinates the full pipeline
  extractors/
    __init__.py
    pdf_extractor.py        # Page-by-page text extraction + OCR fallback
    bookmark_parser.py      # PDF bookmark/outline navigation
  parsers/
    __init__.py
    spec_parser.py          # TOC detection, section splitting, CSI pattern matching
    drawing_parser.py       # Sheet index detection, title block parsing, discipline inference
  validators/
    __init__.py
    spec_validator.py       # TOC-to-content cross-validation
    drawing_validator.py    # Sheet index-to-actual sheet reconciliation
  storage/
    __init__.py
    chunk_store.py          # SQLite tables + sqlite-vss vector search
    schema.sql              # Table definitions
  query.py                  # Agent-facing query interface
```

---

## Data Model (SQLite)

### `documents` table

| Column | Type | Description |
|---|---|---|
| id | TEXT PK | UUID |
| project_id | TEXT | Links to Neo4j Project node |
| file_path | TEXT | Local path to source PDF |
| file_name | TEXT | Original filename |
| doc_type | TEXT | "spec_book" or "drawing_set" |
| total_pages | INTEGER | Page count |
| file_size_bytes | INTEGER | File size |
| status | TEXT | "processing", "indexed", "failed" |
| neo4j_doc_id | TEXT | Corresponding CADocument.doc_id in Neo4j |
| reconciliation_summary | TEXT | JSON: match/mismatch counts from validation |
| indexed_at | TIMESTAMP | When processing completed |
| created_at | TIMESTAMP | When import started |

### `chunks` table

| Column | Type | Description |
|---|---|---|
| id | TEXT PK | UUID |
| document_id | TEXT FK | References documents.id |
| project_id | TEXT | For direct project-scoped queries |
| chunk_type | TEXT | "spec_section" or "drawing_sheet" |
| identifier | TEXT | Section number ("09 21 16") or sheet number ("A2.3") |
| title | TEXT | Section or sheet title |
| content | TEXT | Full extracted text |
| content_summary | TEXT | AI-generated 2-3 sentence summary |
| page_start | INTEGER | First page in source PDF |
| page_end | INTEGER | Last page in source PDF |
| discipline | TEXT | For drawings: Architectural, Structural, etc. |
| division | TEXT | For specs: CSI division number |
| metadata_json | TEXT | Flexible JSON for additional parsed data |
| verification_status | TEXT | "matched", "index_only", "document_only" |
| embedding | BLOB | Vector embedding for semantic search (sqlite-vss) |
| created_at | TIMESTAMP | When chunk was created |

### `processing_log` table

| Column | Type | Description |
|---|---|---|
| id | TEXT PK | UUID |
| document_id | TEXT FK | References documents.id |
| page_number | INTEGER | Page in source PDF |
| extraction_method | TEXT | "pypdf", "ocr", "failed" |
| char_count | INTEGER | Characters extracted |
| flagged | BOOLEAN | True if extraction was poor |

---

## Knowledge Graph Enrichment

### New/Enhanced Nodes

**`SpecSection` (project-specific, coexists with existing Tier 4 generic CSI division nodes):**
- `section_number`, `title`, `project_id`
- `source_doc_id`: links back to CADocument
- `page_range`: "pages 412-428"
- `content_summary`: AI-generated from actual content
- `embedding`: based on real content
- `chunk_id`: foreign key to SQLite chunks table

**`DrawingSheet` (new node type):**
- `sheet_number`, `title`, `discipline`, `project_id`
- `source_doc_id`: links back to CADocument
- `content_summary`: AI summary of notes and callouts
- `embedding`: based on extracted content
- `chunk_id`: foreign key to SQLite chunks table

### New Relationships

```
CADocument -[:HAS_SECTION]-> SpecSection
CADocument -[:HAS_SHEET]-> DrawingSheet
SpecSection -[:REFERENCES_DRAWING]-> DrawingSheet
DrawingSheet -[:REFERENCES_SPEC]-> SpecSection
DrawingSheet -[:COORDINATES_WITH]-> DrawingSheet
RFI -[:REFERENCES_SPEC]-> SpecSection         (existing, now richer targets)
RFI -[:REFERENCES_DRAWING]-> DrawingSheet      (existing Drawing nodes upgraded)
```

---

## Processing Pipeline

### Step 1: Document Registration
- Create `documents` row in SQLite with `status = "processing"`
- Read corresponding `CADocument` from Neo4j for metadata

### Step 2: Page-by-Page Extraction
- Extract text from every page via `pypdf`
- If text < 50 chars on a page, flag for OCR via `pytesseract`
- Log each page to `processing_log`

### Step 3: Structure Detection

**Spec Books — Bookmark-First TOC Extraction:**
1. Extract PDF bookmarks/outline via `pypdf`
2. Find bookmark labeled "Table of Contents" or "TOC" (case-insensitive, fuzzy match)
3. Use bookmark's target page to locate the TOC, read through to the next bookmark boundary
4. Parse TOC lines: `section_number - title ... page_number`
5. If no bookmarks exist, fall back to scanning for CSI section header patterns (`SECTION \d{2}\s?\d{2}\s?\d{2}`)
6. Flag documents with no bookmarks: "Structure detected by pattern matching, manual review recommended"

**Drawing Sets — Sheet Index Extraction:**
1. Scan PDF bookmarks for "Sheet Index", "Drawing Index", "Drawing List" or similar
2. If no bookmarks, scan first 10 pages for a table with sheet number/title columns
3. Parse index into sheet map: `{sheet_number, sheet_title, discipline}`
4. Infer discipline from sheet number prefix: A=Architectural, S=Structural, M=Mechanical, E=Electrical, P=Plumbing, L=Landscape, C=Civil, FP=Fire Protection

### Step 4: Validation

**Spec Books — TOC-to-Content Cross-Validation:**
1. For each section the TOC claims exists, go to the listed page and verify a matching section header
2. Detect consistent page offset issues (printed page numbers vs. PDF page numbers) and auto-correct
3. Flag mismatches for manual review
4. Determine actual page ranges (each section ends where the next begins)

**Drawing Sets — Index-to-Sheet Reconciliation:**
1. Extract title block from every sheet in the PDF
2. Cross-verify against the sheet index
3. Classify each sheet:
   - **Matched**: found in both index and document, data agrees
   - **Index-only**: listed in index but not found in PDF
   - **Document-only**: found in PDF but not in index
4. Store verification status on each chunk
5. Generate reconciliation report stored in `documents.reconciliation_summary`

### Step 5: Chunk Creation & Storage
- Create `chunks` row per section/sheet with full text and metadata
- Generate content summary via lightweight AI call
- Generate embedding via `AIEngine.generate_embedding()` on the content summary

### Step 6: KG Enrichment
- MERGE `SpecSection` nodes (project-specific) in Neo4j, link to `CADocument`
- CREATE `DrawingSheet` nodes, link to `CADocument`
- Parse cross-references from text content and create relationships:
  - Spec text: "See Drawing A2.3" or "Refer to Section 07 92 00"
  - Drawing notes: "Per Section 09 21 16"
  - Create `REFERENCES_DRAWING`, `REFERENCES_SPEC`, `COORDINATES_WITH` relationships

### Step 7: Finalization
- Update `documents.status = "indexed"`, set `indexed_at`
- Update `CADocument` node in Neo4j with section/sheet count
- Log processing stats

---

## Agent Query Interface

Located at `src/document_intelligence/query.py`.

### Exact Lookups
```python
get_spec_section(project_id, section_number) -> dict
# Returns: full text + metadata for a specific spec section

get_sheet(project_id, sheet_number) -> dict
# Returns: extracted text + metadata for a specific drawing sheet

get_pages(document_id, pages: list[int]) -> list[dict]
# Returns: raw extracted text for specific PDF pages
```

### Search
```python
search(project_id, query, top_k=10, doc_type=None, discipline=None, division=None) -> list[dict]
# Semantic search across chunks, with optional filters
# Returns: ranked chunks with scores and content summaries
```

### Discovery
```python
list_documents(project_id) -> list[dict]
list_sections(document_id) -> list[dict]
list_sheets(document_id) -> list[dict]
```

### Typical Agent Flow (RFI Example)
1. Parse RFI to identify spec sections and drawing references
2. Call `get_spec_section()` and `get_sheet()` for known references
3. Use KG graph traversal to find cross-trade relationships
4. Call `search()` for broader context
5. Receive precisely targeted content within token budget

---

## Error Handling

- If processing fails mid-document: `status = "failed"`, partial chunks preserved, retry allowed
- Each step logged to `processing_log` for debugging
- Partial success is acceptable — 95% of sheets parsing cleanly while 5 need manual review still provides value
- Documents without PDF bookmarks flagged but still processed via pattern-matching fallback

## Performance Expectations

- 500-page spec book: ~2-5 minutes (mostly AI summary/embedding calls)
- 200-sheet drawing set: ~1-3 minutes
- Runs once at project setup; processing time is acceptable

## Dependencies

- `pypdf` — already in use
- `pytesseract` + `Pillow` — new, for OCR fallback on scanned pages
- `sqlite-vss` — new, for vector search in SQLite
- No new external services or cloud dependencies

---

## Files to Create

| File | Purpose |
|---|---|
| `src/document_intelligence/__init__.py` | Module init |
| `src/document_intelligence/service.py` | Pipeline orchestrator |
| `src/document_intelligence/extractors/__init__.py` | Extractors subpackage |
| `src/document_intelligence/extractors/pdf_extractor.py` | Page-by-page extraction + OCR |
| `src/document_intelligence/extractors/bookmark_parser.py` | PDF bookmark navigation |
| `src/document_intelligence/parsers/__init__.py` | Parsers subpackage |
| `src/document_intelligence/parsers/spec_parser.py` | Spec TOC detection + section splitting |
| `src/document_intelligence/parsers/drawing_parser.py` | Sheet index + title block parsing |
| `src/document_intelligence/validators/__init__.py` | Validators subpackage |
| `src/document_intelligence/validators/spec_validator.py` | TOC-to-content validation |
| `src/document_intelligence/validators/drawing_validator.py` | Index-to-sheet reconciliation |
| `src/document_intelligence/storage/__init__.py` | Storage subpackage |
| `src/document_intelligence/storage/chunk_store.py` | SQLite + sqlite-vss operations |
| `src/document_intelligence/storage/schema.sql` | Table definitions |
| `src/document_intelligence/query.py` | Agent-facing query interface |
| `scripts/process_project_documents.py` | Standalone processing script |

## Files to Modify

| File | Change |
|---|---|
| `src/knowledge_graph/client.py` | Add methods for SpecSection/DrawingSheet MERGE, relationship creation, cross-reference queries |
| `pyproject.toml` | Add pytesseract, Pillow, sqlite-vss dependencies |
