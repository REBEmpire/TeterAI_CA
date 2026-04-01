# TeterAI_CA — Project Context for AI Assistants

This file gives Claude (and future AI assistants) the full picture of what TeterAI_CA is,
what has been built, where everything lives, and the key gotchas discovered along the way.
Read this before starting any new work session.

---

## What This Project Is

**TeterAI_CA** is a multi-agent AI system for Teter Architects' Construction Administration
(CA) department. It automates the document-heavy CA workflow — RFI processing, submittal
review, change order analysis, pay application tracking — while keeping humans in the loop.
No document is approved or sent externally without a licensed architect clicking "Approve."

The system processes real construction project documents from 5 pilot projects (584+ documents
ingested as of April 2026) into a Neo4j knowledge graph, then surfaces that knowledge through
a React dashboard and AI-powered analysis tools.

---

## Architecture at a Glance

```
Google Drive (CA docs) → Ingestion Pipeline → Neo4j Aura (Knowledge Graph)
                                               ↕
Gmail Ingest → Dispatcher Agent → Tool Agents (RFI / Submittal / CO / etc.)
                                      ↕
                              FastAPI Backend (/api/v1)
                                      ↕
                              React Frontend (Vite + Tailwind)
```

### Key Infrastructure

| Service | Purpose | Location |
|---|---|---|
| **Neo4j Aura** | Knowledge Graph — docs, projects, parties, embeddings | `neo4j+s://2d93324b.databases.neo4j.io` |
| **Firestore** | Task queue, audit log, user auth, model registry | GCP project `teterai-ca` |
| **Google Drive** | Source of truth for CA documents | Folder per project |
| **Vertex AI** | `text-embedding-004` (768-dim) for document embeddings | GCP `us-central1` |
| **LiteLLM** | Unified interface to Anthropic, Google Gemini, xAI | via `engine.py` |
| **FastAPI** | Backend API | `src/ui/api/` |
| **React + Vite** | Frontend | `src/ui/web/` |

---

## Source Layout

```
src/
  ai_engine/
    engine.py           # Core AI engine — tiered model calls, rate limiting, retry
    models.py           # Pydantic models: CapabilityClass, AIRequest, ModelRegistry, etc.
    default_registry.json  # Fallback model config (Firestore is authoritative at runtime)
    agents/             # (placeholder — agents live in their own modules currently)
    gcp.py              # GCP / Vertex AI integration
  knowledge_graph/
    client.py           # KnowledgeGraphClient — all Neo4j queries
    ingestion.py        # DriveToKGIngester — Google Drive → Neo4j pipeline
    seed_kg_baseline.py # One-time seeder for SpecSection/PlaybookRule baseline nodes
  ui/
    api/
      routes.py         # All FastAPI endpoints (/api/v1/...)
      auth.py           # JWT auth, Google OAuth callback
      firestore.py      # Firestore access layer
    web/
      src/
        views/          # React page components (one per major feature)
        components/     # Shared UI (NavBar, AppShell, RoleGuard, etc.)
        api/client.ts   # All typed fetch wrappers for the backend
        types/index.ts  # Shared TypeScript types
  agents/               # Agent implementations (RFI, Submittal, Dispatcher, etc.)
  document_intelligence/ # (planned) Spec-book + drawing-set chunking pipeline
```

---

## Features Built (Chronological)

### Phase 0–3: Core CA Workflow
Dispatcher Agent classifies incoming documents from Gmail/Drive and routes them to the
appropriate tool agent. Humans review AI-drafted responses in a split-pane viewer before
approving. All actions are logged to Firestore audit trail.

**Views:** Dashboard, SplitViewer, SubmittalReviewViewer, LoginPage, AdminPanel, SettingsPage, UploadView

### Phase C: Document Upload
Users can upload CA documents (PDF, DOCX, XER, XML) directly from the web UI.
The backend infers document type, creates a task, and runs the appropriate agent.

**Endpoint:** `POST /api/v1/upload/document`

### Phase D: Knowledge Graph Ingestion (Drive → Neo4j)
`DriveToKGIngester` recursively walks a project's Google Drive folder tree, extracts text
from each document (PDF via pypdf, DOCX via python-docx, Google Docs/Sheets via export API),
calls an AI extraction prompt to pull structured metadata (doc_type, doc_number, parties,
dates, summary), generates a Vertex AI embedding, and UPSERTs a `CADocument` node in Neo4j
linked to its `Project` and `Party` nodes.

**Key file:** `src/knowledge_graph/ingestion.py`
**Script:** `scripts/ingest_project.py` (or similar — check scripts/)

**CADocument node properties:** `doc_id`, `drive_file_id`, `filename`, `drive_folder_path`,
`doc_type`, `doc_number`, `phase`, `date_submitted`, `date_responded`, `summary`,
`embedding` (768-dim list), `embedding_model`, `metadata_only` (bool — True if text
extraction failed or doc was too short to extract structure from).

**Vector index:** `ca_document_embeddings` on `CADocument.embedding`

### Phase E: Project Intelligence Dashboard
Surfaces KG data as an interactive dashboard: KPI cards, inline SVG charts, party tables,
and AI-generated project health narratives.

**New NavBar link:** "Project Intelligence" → `/project-intelligence`
**View:** `src/ui/web/src/views/ProjectIntelligenceView.tsx`

**Backend endpoints:**
- `GET /api/v1/projects/compare` — all-projects side-by-side KPIs (**must be before `/{project_id}/`**)
- `GET /api/v1/projects/{project_id}/intelligence` — aggregate KPIs for one project
- `GET /api/v1/projects/{project_id}/party-network` — submission counts by party
- `GET /api/v1/projects/{project_id}/timeline` — monthly document activity
- `POST /api/v1/projects/{project_id}/ai-summary` — AI health narrative (uses ANALYZE capability)

**KG methods:** `get_project_intelligence`, `get_party_network`, `get_document_timeline`, `get_cross_project_summary`

### Phase F: Pre-Bid Lessons Learned
Mines completed-project RFI and Change Order history via semantic vector search, then uses
AI to synthesise findings into an actionable pre-bid checklist. Helps the design team
eliminate historically-recurring problems before bid documents go out.

**New NavBar link:** "Pre-Bid Review" → `/prebid-review`
**View:** `src/ui/web/src/views/PreBidReviewView.tsx`

**Backend endpoint:**
- `POST /api/v1/prebid-lessons` — takes `{query_text, source_project_ids, doc_types?}`
  Returns: `{similar_docs, doc_type_counts, checklist: {summary, design_risks, spec_sections_to_clarify, bid_checklist}}`

**KG methods:** `get_prebid_lessons` (vector search filtered to RFI/CO types), `get_hotspot_topics` (count-based top issues)

### Planned — Phase G: Document Intelligence Service
Designed in `docs/superpowers/specs/2026-04-01-document-intelligence-service-design.md`.
Chunks spec books and drawing sets into `SpecSection` / `DrawingSheet` nodes so agents
can retrieve exactly the relevant content rather than truncated 3,000-char summaries.
**Not yet implemented.**

---

## AI Engine (`src/ai_engine/engine.py`)

### Capability Classes
Each AI task is assigned a `CapabilityClass` that maps to a tiered model chain in the registry.

| CapabilityClass | Purpose | Default Tier 1 |
|---|---|---|
| `REASON_DEEP` | Complex multi-step reasoning | Claude Sonnet |
| `REASON_STANDARD` | Standard reasoning | Claude Sonnet |
| `CLASSIFY` | Document classification | Gemini Flash |
| `GENERATE_DOC` | Draft responses/letters | Claude Sonnet |
| `EXTRACT` | Metadata extraction from documents | Gemini Flash Lite |
| `MULTIMODAL` | Image/drawing analysis | Claude Sonnet |
| `SUBMITTAL_REVIEW` | Submittal package review | Claude Sonnet |
| `RED_TEAM_CRITIQUE` | Adversarial review of AI outputs | Claude Sonnet |
| `ANALYZE` | Project analytics + narrative synthesis | Claude Sonnet 4.6 |

### Model Registry
- **Firestore** is authoritative at runtime: `ai_engine/model_registry` document.
- `default_registry.json` is the fallback used if Firestore is unreachable.
- `ModelRegistry.capability_classes` uses `Dict[str, CapabilityConfig]` (string keys, not enum)
  so adding new capabilities to Firestore doesn't break running processes that have an older enum.
- **When adding a new CapabilityClass:** (1) add to `CapabilityClass` enum in `models.py`,
  (2) add to `default_registry.json`, (3) add to Firestore `ai_engine/model_registry` document.

### Retry Logic
- Per-tier retry with exponential backoff + jitter before falling through to the next tier.
- Retryable conditions: HTTP 429/500/502/503/504, `ServiceUnavailableError`, `RateLimitError`,
  timeout, "overloaded" in message.
- Configure via env: `AI_ENGINE_RATE_LIMIT_RPM` (default 60), `TIER_MAX_RETRIES` (default 2).

---

## Knowledge Graph (`src/knowledge_graph/client.py`)

### Connection Resilience
Long-running processes (ingestion) can hold idle Neo4j connections that Windows TCP stack
kills (error 10053 / `ConnectionAbortedError`). All write methods use:
- `_run_with_retry(fn)` — retries up to 3× on `ServiceUnavailable`, `SessionExpired`, `OSError`, `ConnectionAbortedError`
- `_reconnect()` — closes and reopens the driver
- `_session()` — creates a fresh session, reconnecting if the driver is dead
- `max_connection_lifetime=300` — rotate connections every 5 minutes

### Vector Indexes
| Index name | Node label | Property | Dimensions |
|---|---|---|---|
| `ca_document_embeddings` | `CADocument` | `embedding` | 768 |
| `rfi_embeddings` | `RFI` | `embedding` | 768 |
| `spec_section_embeddings` | `SpecSection` | `embedding` | 768 |

Similarity threshold configurable via env: `KG_EMBEDDING_SIMILARITY_THRESHOLD` (default 0.70 for
doc search, 0.65 for pre-bid lessons search, 0.75 for spec section search).

### Graph Schema (key nodes)
```
(Project {project_id, project_number, name, phase, drive_root_folder_id})
  -[:HAS_DOCUMENT]->
(CADocument {doc_id, drive_file_id, filename, doc_type, doc_number, phase,
             date_submitted, date_responded, summary, embedding, metadata_only})
  -[:SUBMITTED_BY]->
(Party {party_id, name, type})

(Project)-[:HAS_RFI]->(RFI {rfi_id, rfi_number, question, response_text, embedding, ...})
(RFI)-[:REFERENCES_SPEC]->(SpecSection)
```

### Key Cypher Patterns
```cypher
-- Count non-null date_responded (responded docs)
count(d.date_responded)   -- counts non-null values

-- Extract YYYY-MM from ISO date string
substring(d.date_submitted, 0, 7)

-- /projects/compare MUST be registered before /{project_id}/intelligence in FastAPI
-- or "compare" gets matched as a project_id
```

---

## Google Drive Ingestion (`src/knowledge_graph/ingestion.py`)

### Folder → doc_type Mapping
The ingester infers `doc_type` from the Drive folder name:
`RFI`, `Submittals`, `Change Orders`, `Pay Applications`, `Schedules`, `Correspondence`, etc.
See `FOLDER_TO_DOC_TYPE` dict at top of file.

### Concurrent Processing
Uses `ThreadPoolExecutor(max_workers=4)` for parallel document processing.
Thread-safe stats accumulation via `threading.Lock()`.
Configure via env: `INGEST_MAX_WORKERS` (default 4).

### Google Sheets Handling
`application/vnd.google-apps.spreadsheet` files cannot be downloaded as binary — they must be
exported as CSV via the Drive API export endpoint. The ingester handles this automatically.

### Embeddings
`AIEngine.generate_embedding(text)` → Vertex AI `text-embedding-004` → 768-dim list.
Requires `roles/aiplatform.user` IAM on the service account. The embedding is stored on
the `CADocument` node as a list property.

**If Vertex AI throws 403:** The service account IAM grant may be new and the token stale.
Stop the process and restart — fresh processes pick up the updated IAM.

---

## Frontend (`src/ui/web/`)

### Stack
- Vite + React + TypeScript
- Tailwind CSS with custom Teter brand tokens:
  - `bg-teter-dark` — `#313131` (header/dark background)
  - `text-teter-orange` / `bg-teter-orange` — `#d06f1a` (brand accent)
  - `text-teter-gray-text` — muted body text
  - `card` — standard card container class
  - `btn-primary` — primary orange button
  - `max-w-wide` — wide content container

### SVG Charts
All charts are inline SVG — no npm chart packages. Use `style={{ fill: '#6b6b6b' }}`
on SVG `<text>` elements (Tailwind `fill-*` classes are not reliably supported for SVG).

### API Client (`src/ui/web/src/api/client.ts`)
All API calls go through `request<T>(method, path, body?)` which:
- Reads the JWT from `localStorage.getItem('teterai_token')`
- Attaches it as `Authorization: Bearer <token>`
- Throws `ApiError(status, message)` on non-OK responses

---

## Credentials & Environment Variables

### Primary credential store: `~/.teterai/config.env`

All credentials are stored in `C:\Users\RussellBybee\.teterai\config.env` (plain key=value).
`LocalConfig.ensure_exists().push_to_env()` reads this file and pushes values into
`os.environ` so LiteLLM, Neo4j, and GCP all pick them up.

**The FastAPI server** calls `push_to_env()` automatically at startup via `server.py`.
**CLI scripts** must call it explicitly — see `scripts/ingest_drive_to_kg.py` for the pattern:
```python
from config.local_config import LocalConfig
LocalConfig.ensure_exists().push_to_env()
```

### Credential file location reference

| Credential | File |
|---|---|
| GCP service account JSON | `../service-account.json` (one level above TeterAI_CA/) |
| Google OAuth client secret | `../client_secret_894836945557-...json` |
| All API keys (plaintext reference) | `../credentials.conf.txt` |

### config.env fields

| Field | Maps to env var | Description |
|---|---|---|
| `anthropic_api_key` | `ANTHROPIC_API_KEY` | Claude API |
| `google_api_key` | `GOOGLE_API_KEY` | Gemini API |
| `xai_api_key` | `XAI_API_KEY` | Grok API |
| `google_application_credentials` | `GOOGLE_APPLICATION_CREDENTIALS` | Path to GCP service account JSON |
| `neo4j_uri` | `NEO4J_URI` | `neo4j+s://2d93324b.databases.neo4j.io` |
| `neo4j_username` | `NEO4J_USERNAME` | `neo4j` |
| `neo4j_password` | `NEO4J_PASSWORD` | Aura instance password |

### Other env vars (set at runtime, not in config.env)

| Variable | Default | Description |
|---|---|---|
| `AI_ENGINE_RATE_LIMIT_RPM` | `0` | Max AI requests per minute (0 = disabled) |
| `AI_ENGINE_TIER_MAX_RETRIES` | `2` | Per-tier retry attempts before fallthrough |
| `INGEST_MAX_WORKERS` | `4` | Concurrent Drive ingestion threads |
| `KG_EMBEDDING_SIMILARITY_THRESHOLD` | `0.70` | Cosine similarity floor for vector search |
| `VITE_DESKTOP_MODE` | `false` | Enables Settings page, hides Admin link |

---

## Common Pitfalls & Lessons Learned

1. **`/projects/compare` route ordering** — Must be registered _before_ `/{project_id}/...`
   routes in `routes.py` or FastAPI matches "compare" as a project_id string.

2. **`ModelRegistry` Pydantic validation** — Use `Dict[str, CapabilityConfig]` (not
   `Dict[CapabilityClass, CapabilityConfig]`) so adding new capabilities to Firestore
   doesn't break running processes that have an older version of the enum in memory.

3. **Vertex AI 403 in long-running processes** — IAM grants need a fresh process/token.
   Stop and restart the process after granting new IAM roles.

4. **Neo4j Windows error 10053** — Windows TCP stack kills idle connections. Fix:
   `max_connection_lifetime=300` + `_run_with_retry` + `_reconnect` in `KnowledgeGraphClient`.

5. **Google Sheets MIME type** — `application/vnd.google-apps.spreadsheet` cannot be
   downloaded directly; use the Drive API `files().export(mimeType='text/csv')` method.

6. **`date_responded` null vs empty string** — If ingestion stored `""` instead of `null`
   for unresponded docs, `count(d.date_responded)` in Cypher undercounts. Verify with:
   `MATCH (d:CADocument) RETURN d.date_responded LIMIT 5`

7. **Firestore model_registry** — Adding a new `CapabilityClass` requires updating **both**
   `default_registry.json` AND the Firestore `ai_engine/model_registry` document. The live
   system always reads from Firestore first.

8. **project_id format** — Neo4j stores numeric strings like `"11900"`. Firestore project
   docs use the same IDs. Verify alignment with:
   `MATCH (p:Project) RETURN p.project_id, p.name`

---

## Testing

```bash
# Run all tests
uv run pytest tests/

# Check Neo4j data
# In Neo4j Browser (https://browser.neo4j.io or Aura console):
MATCH (p:Project) RETURN p.project_id, p.name, p.project_number;
MATCH (p:Project)-[:HAS_DOCUMENT]->(d:CADocument) RETURN p.name, count(d) ORDER BY count(d) DESC;
MATCH (d:CADocument) WHERE d.embedding IS NOT NULL RETURN count(d);
```

## Backend API quick test (with JWT)

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/password \
  -H "Content-Type: application/json" \
  -d '{"username":"<email>","password":"<password>"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/projects/11900/intelligence
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/projects/compare
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"query_text":"exterior waterproofing","source_project_ids":["11900"]}' \
  http://localhost:8000/api/v1/prebid-lessons
```
