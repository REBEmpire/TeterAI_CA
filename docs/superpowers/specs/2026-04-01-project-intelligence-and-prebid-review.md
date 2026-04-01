# Project Intelligence Dashboard & Pre-Bid Lessons Learned — Feature Spec

**Date:** 2026-04-01
**Status:** Implemented
**Phases:** E (Project Intelligence Dashboard) and F (Pre-Bid Lessons Learned)

---

## Background

With 584+ CA documents ingested across 5 pilot projects, the Teter team needed ways to:

1. **Understand their projects** — visualise document volumes, response rates, active parties,
   and timeline trends using the data already in Neo4j.
2. **Learn from completed projects** — use historical RFI and Change Order patterns to
   identify design issues in new projects _before_ bid documents go out.

These two features answer those needs without requiring any new npm packages (charts are
inline SVG) or new data ingestion — they surface what's already in the Knowledge Graph.

---

## Phase E: Project Intelligence Dashboard

### What It Does

A dashboard page that loads KPI cards, charts, and an AI-generated health narrative for
any project in the system. Also includes a cross-project comparison mode.

### User Flow

1. Navigate to **Project Intelligence** in the top nav.
2. Select a project from the dropdown.
3. KPI cards, bar chart, timeline, and party table all load in parallel.
4. Optionally click **Compare Projects** to see all projects side-by-side.
5. Click **Generate Project Summary** to request an AI health narrative.

### Data Displayed

| Section | What It Shows |
|---|---|
| KPI Cards | Total docs, RFI count, response rate (colour-coded), distinct parties |
| Doc Type Bar Chart | Horizontal SVG bars — doc types ranked by count |
| Timeline Chart | Monthly submission volume as a polyline area chart |
| Party Table | Name, type, total submissions, top doc type |
| AI Narrative | 5-section health narrative: Overview, Document Status, Key Parties, Risk Flags, Recommendations |
| Compare Mode | Grid of per-project KPI cards across all projects |

### Backend Endpoints

All under `/api/v1/`:

```
GET  /projects/compare                     → cross-project summary (registered FIRST — no path param)
GET  /projects/{project_id}/intelligence   → aggregate KPIs for one project
GET  /projects/{project_id}/party-network  → party submission counts
GET  /projects/{project_id}/timeline       → monthly doc activity (YYYY-MM buckets)
POST /projects/{project_id}/ai-summary     → AI health narrative via CapabilityClass.ANALYZE
```

**Critical route ordering:** `/projects/compare` must be registered in `routes.py` _before_
`/projects/{project_id}/...` routes, or FastAPI will try to match `"compare"` as a
`project_id` path parameter and return 404.

### AI Narrative Format

The `POST /ai-summary` endpoint returns JSON with exactly these five keys:
```json
{
  "overview": "...",
  "document_status": "...",
  "key_parties": "...",
  "risk_flags": "...",
  "recommendations": "..."
}
```

If the AI returns non-JSON (e.g. markdown code fences), the endpoint strips fence markers
and retries `json.loads()`. If that fails, the raw text lands in `overview` and the other
four keys are empty strings.

### KG Methods Added (`src/knowledge_graph/client.py`)

| Method | Cypher summary |
|---|---|
| `get_project_intelligence(project_id)` | Aggregate counts + `count(d.date_responded)` for response rate + `substring(date, 0, 7)` date range |
| `get_party_network(project_id)` | Group by Party + doc_type, sum total |
| `get_document_timeline(project_id)` | `substring(d.date_submitted, 0, 7)` month grouping |
| `get_cross_project_summary()` | All-project aggregate with response rate computation |

### Frontend Files

| File | Role |
|---|---|
| `src/ui/web/src/views/ProjectIntelligenceView.tsx` | Main view — state, data loading, layout |
| `src/ui/web/src/api/client.ts` | `ProjectIntelligence`, `PartyEntry`, `TimelineMonth`, `CrossProjectEntry`, `AINarrative`, `AISummaryResponse` types + 5 fetch functions |
| `src/ui/web/src/components/layout/NavBar.tsx` | "Project Intelligence" link with bar-chart icon |
| `src/ui/web/src/App.tsx` | `/project-intelligence` route |

### SVG Chart Notes

- No npm chart packages — all charts are hand-written SVG inside JSX.
- `<text>` elements use `style={{ fill: '#6b6b6b' }}` — Tailwind `fill-*` classes are
  not reliable for SVG in all Tailwind versions.
- `fill="#d06f1a"` matches the `teter-orange` brand colour.
- Response rate is colour-coded: `#16a34a` green ≥70%, `#d97706` amber 50–69%, `#dc2626` red <50%.

---

## Phase F: Pre-Bid Lessons Learned

### What It Does

A reverse-lookup tool: given a design concern (described in plain English) and a selection
of completed projects to mine, it:

1. Embeds the concern description using the same Vertex AI embedding model used during ingestion.
2. Runs a cosine similarity search against the `ca_document_embeddings` vector index,
   filtered to RFI and Change Order document types from the chosen source projects.
3. Returns the most semantically similar historical issues with project attribution and
   similarity scores.
4. Synthesises findings into a 4-section AI checklist via `CapabilityClass.ANALYZE`.

### Example Use Cases

- "Exterior window flashing and waterproofing at punched openings" → finds all past RFIs
  and COs involving waterproofing failures, returns checklist of spec sections to clarify.
- "Structural steel connection at mechanical penthouse parapet" → surfaces coordination
  failures between structural and mechanical from past projects.
- "Concrete flatwork control joints and curing requirements" → finds every CO related to
  concrete cracking from historical projects.

### User Flow

1. Navigate to **Pre-Bid Review** in the top nav.
2. Type a design concern or topic in the text area.
3. Toggle which completed projects to mine (multi-select checkboxes).
4. Click **Run Pre-Bid Review**.
5. Results appear:
   - **4-section AI checklist** (Historical Summary, Design Risks, Spec Sections to Clarify, Bid Checklist)
   - **Issue volume bar chart** — how many RFIs/COs by doc type across source projects
   - **Ranked similar documents** — expandable list with similarity score badges

### Similarity Score Badges

| Score | Badge | Color |
|---|---|---|
| ≥ 0.85 | High Match | Red `#dc2626` |
| 0.75–0.85 | Medium Match | Amber `#d97706` |
| < 0.75 | Low Match | Green `#16a34a` |

### Backend Endpoint

```
POST /api/v1/prebid-lessons
Content-Type: application/json

{
  "query_text": "exterior window flashing...",
  "source_project_ids": ["11900", "12556"],
  "doc_types": ["RFI", "CO"]   // optional — defaults to all RFI/CO variants
}
```

**Response:**
```json
{
  "query_text": "...",
  "source_project_ids": [...],
  "similar_docs": [
    {
      "doc_id": "...", "filename": "...", "doc_type": "RFI",
      "doc_number": "RFI-042", "summary": "...",
      "date_submitted": "2024-03-15", "project_id": "11900",
      "project_name": "Elm Street Mixed Use", "project_number": "11900",
      "score": 0.891
    }, ...
  ],
  "doc_type_counts": {"RFI": 38, "CO": 12},
  "checklist": {
    "summary": "...",
    "design_risks": "...",
    "spec_sections_to_clarify": "...",
    "bid_checklist": "..."
  },
  "generated_at": "2026-04-01T14:22:00Z",
  "model_used": "claude-sonnet-4-6",
  "tier_used": 1
}
```

### AI Prompt Structure

The `prebid_lessons_learned` agent prompt gives Claude:
- The original design concern
- RFI/CO volume counts by doc type
- Top-8 most similar historical docs (truncated summaries, project attribution, similarity scores)
- Top-8 historically-responded docs (the ones that were real problems, not just filed)

It asks for a JSON object with four keys: `summary`, `design_risks`,
`spec_sections_to_clarify`, `bid_checklist`. Same markdown-fence stripping fallback as
the AI summary endpoint.

### KG Methods Added (`src/knowledge_graph/client.py`)

#### `get_prebid_lessons(query_text, source_project_ids, doc_types, top_k=20)`
- Generates a Vertex AI embedding for `query_text`.
- Calls `ca_document_embeddings` vector index with `fetch_k = top_k * 4` (over-fetches
  so post-filter to `source_project_ids` and `doc_types` still returns enough results).
- Post-filters via `MATCH (p:Project)-[:HAS_DOCUMENT]->(d) WHERE p.project_id IN $ids`.
- Returns up to `top_k` results ordered by cosine similarity descending.
- Default `doc_types`: `['RFI', 'CO', 'CHANGE_ORDER', 'Change Order', 'COR', 'POTENTIAL_CO']`
- Default similarity threshold: `0.65` (lower than general search to catch more borderline matches).

#### `get_hotspot_topics(source_project_ids, top_n=20)`
- No vector search — pure count queries.
- Returns `doc_type_counts` (volume by type) and `top_docs` (most-responded issues).
- `top_docs` prioritises documents with a non-null `date_responded` (confirmed real issues
  over unresponded filings).

### Frontend Files

| File | Role |
|---|---|
| `src/ui/web/src/views/PreBidReviewView.tsx` | Main view — project multi-select, query input, results |
| `src/ui/web/src/api/client.ts` | `PreBidSimilarDoc`, `PreBidChecklist`, `PreBidLessonsResponse` types + `getPreBidLessons()` |
| `src/ui/web/src/components/layout/NavBar.tsx` | "Pre-Bid Review" link with clipboard-check icon |
| `src/ui/web/src/App.tsx` | `/prebid-review` route |

---

## Shared Infrastructure Changes (This Session)

### `CapabilityClass.ANALYZE` (new)
Added to `src/ai_engine/models.py` and `src/ai_engine/default_registry.json`.
**Also add to Firestore** `ai_engine/model_registry` document — the live system reads
Firestore, not the JSON file.

Default models: tier 1 = `claude-sonnet-4-6`, tier 2 = `gemini/gemini-2.0-flash`,
tier 3 = `xai/grok-3-mini`.

### `ModelRegistry.capability_classes` type fix
Changed from `Dict[CapabilityClass, CapabilityConfig]` to `Dict[str, CapabilityConfig]`
in `src/ai_engine/models.py`. This makes the registry forward-tolerant — adding a new
capability to Firestore no longer causes Pydantic validation failures in running processes
that have an older `CapabilityClass` enum loaded.

### AI Engine retry improvements
Added per-tier exponential backoff + jitter before falling through to the next model tier.
Retries on 429, 500, 502, 503, 504, ServiceUnavailableError, RateLimitError, timeout, "overloaded".
Configure: `AI_ENGINE_RATE_LIMIT_RPM` (default 60), `TIER_MAX_RETRIES` (default 2).

---

## Verification Checklist

### Neo4j (run in Neo4j Browser first)
```cypher
// Projects have documents
MATCH (p:Project)-[:HAS_DOCUMENT]->(d:CADocument)
RETURN p.project_id, p.name, count(d) ORDER BY count(d) DESC;

// Embeddings exist (needed for vector search)
MATCH (d:CADocument) WHERE d.embedding IS NOT NULL RETURN count(d);

// Check date_responded format (null vs empty string)
MATCH (d:CADocument) RETURN d.date_responded LIMIT 10;

// Check doc_type values for RFI/CO variants
MATCH (d:CADocument)
WHERE d.doc_type IN ['RFI','CO','CHANGE_ORDER','Change Order','COR','POTENTIAL_CO']
RETURN d.doc_type, count(d) ORDER BY count(d) DESC;
```

### Frontend checklist
- [ ] "Project Intelligence" and "Pre-Bid Review" appear in NavBar
- [ ] Project selector populates from Firestore project list
- [ ] KPI cards load on project select (Project Intelligence)
- [ ] Bar chart + timeline render correctly
- [ ] Party table shows top submitters
- [ ] "Generate Project Summary" → spinner → 5-section narrative
- [ ] "Compare Projects" toggle → cross-project grid
- [ ] Multi-select checkboxes work on Pre-Bid Review
- [ ] "Run Pre-Bid Review" → spinner → 4-section checklist + similar docs list
- [ ] Score badges show correct colours (High/Medium/Low Match)
- [ ] Expandable summaries work on similar doc rows
- [ ] Unauthenticated access → redirect to login
