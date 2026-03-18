# TETER-CA-AI-AGT-RFI-001 — RFI Agent (Construction Phase)

| Field | Value |
|-------|-------|
| Document ID | TETER-CA-AI-AGT-RFI-001 |
| Version | v0.1.0 |
| Status | Draft |
| Phase | Phase 0 — Foundation |
| Last Updated | 2026-03-18 |

---

## 1. Purpose & Scope

The RFI Agent (AGENT-RFI-001) is the first specialist agent in the TeterAI_CA system and the primary proof-of-concept for Phase 0. It handles Requests for Information (RFIs) submitted by contractors during the construction phase.

The RFI Agent is selected as the Phase 0 priority because:
- **Highest volume** — RFIs are the most frequent CA document type during construction
- **Clearest test case** — well-defined input (contractor question) and output (spec-cited response)
- **Demonstrable value** — reduces CA staff time on repetitive spec lookups

The RFI Agent processes each RFI through a structured pipeline:
1. **Information extraction** — parse RFI number, question, referenced specs/drawings, contractor
2. **Knowledge graph lookup** — find relevant spec sections and industry standards
3. **Drawing cross-reference** — identify relevant drawing sheets if applicable
4. **Response drafting** — draft a professional response with spec citations
5. **RFI log update** — maintain the project's running RFI log

**In scope (Phase 0):** Construction phase RFIs only. Input is email + PDF attachments.

**Out of scope (Phase 0):** Bid phase pre-bid RFIs (Phase 1), multi-party RFI threads, drawing markup, formal AIA G716 form generation.

---

## 2. Dependencies

| Dependency | Type | Notes |
|-----------|------|-------|
| TETER-CA-AI-AEC-001 | Internal spec | AI Engine: REASON_DEEP, EXTRACT, MULTIMODAL |
| TETER-CA-AI-KG-001 | Internal spec | Spec section lookup, playbook rules |
| TETER-CA-AI-INT-DRIVE-001 | Internal spec | Source docs, RFI log, draft filing |
| TETER-CA-AI-WF-001 | Internal spec | Task state management |
| TETER-CA-AI-AUDIT-001 | Internal spec | All processing steps logged |

---

## 3. Architecture Overview

```
Task assigned by Dispatcher (doc_type: RFI, phase: construction)
        │
        ▼
RFI Agent picks up task
        │
        ├── Step 1: Extract RFI details (EXTRACT)
        │
        ├── Step 2: Knowledge Graph — spec section semantic search
        │
        ├── Step 3: Source document retrieval (drawings/specs from Drive)
        │
        ├── Step 4: Optional — MULTIMODAL drawing analysis
        │
        ├── Step 5: Draft response (REASON_DEEP)
        │
        ├── Step 6: Update RFI log
        │
        └── Step 7: Stage for human review (WF: STAGED_FOR_REVIEW)
```

---

## 4. RFI Processing Pipeline

### Step 1: RFI Extraction

**Capability class:** `EXTRACT`

Extract structured information from the email body and attachments:

```json
{
  "rfi_number_submitted": "045",        // contractor's numbering
  "contractor_name": "ABC Contractors",
  "contractor_contact": "John Smith",
  "question": "Specification Section 03 30 00 paragraph 2.3 calls for 4000 PSI concrete. The structural drawings sheet S-101 note 3 calls for 5000 PSI. Which governs?",
  "referenced_spec_sections": ["03 30 00"],
  "referenced_drawing_sheets": ["S-101"],
  "date_submitted": "2026-03-18",
  "response_requested_by": "2026-03-28",
  "attachments_analyzed": ["RFI-045.pdf"]
}
```

### Step 2: Knowledge Graph Lookup

Query KG for relevant spec sections and playbook guidance:

```python
# 1. Semantic search for spec sections
kg.search_spec_sections("concrete compressive strength PSI requirements", top_k=5)

# 2. Fetch RFI agent playbook
kg.get_agent_playbook("AGENT-RFI-001")

# 3. Fetch RFI workflow steps
kg.get_document_workflow("RFI")
```

The playbook guides the agent's response approach (e.g., "when spec and drawings conflict, the Conditions of the Contract govern — cite AIA A201 Section 1.2.1").

### Step 3: Source Document Retrieval

Retrieve the actual spec sections and drawing pages from Drive:

```
[Project]/02 - Construction/Source Docs/
  ├── Project Specifications.pdf    ← search for relevant sections
  └── Drawings/
      └── S-101.pdf                 ← retrieve sheet for analysis
```

Source docs are stored in `04 - Agent Workspace/Source Docs/` as copies placed there at project onboarding.

### Step 4: MULTIMODAL Drawing Analysis (conditional)

If the RFI references drawing sheets AND the sheet can be retrieved from Drive:

**Capability class:** `MULTIMODAL`

- Extract the relevant drawing area/note
- Identify the specification requirement shown
- Note any discrepancy with the spec document

This step is skipped if no drawings are referenced or if the drawing cannot be found.

### Step 5: Draft Response

**Capability class:** `REASON_DEEP`

The agent drafts a professional RFI response using:
- Extracted RFI question
- Relevant spec sections found in Steps 2-4
- Playbook guidance (tone, citation format, escalation rules)
- Contract clause (if conflict resolution is needed)

**Response format:**

```
PROJECT: [YYYY-NNN] - [Project Name]
RFI #: RFI-[NNN]
DATE: [YYYY-MM-DD]
FROM: Teter Architects
TO: [Contractor Name]
RE: [Subject from original RFI]

RESPONSE:

[Substantive response text with spec citations in format "Specification Section XX XX XX, Paragraph X.X.X"]

REFERENCES:
- Specification Section 03 30 00, Paragraph 2.3 — Concrete Compressive Strength
- Structural Drawings Sheet S-101, Note 3
- AIA A201-2017, Section 1.2.1 — Correlation and Intent of Contract Documents

[CA Staff Signature Block Placeholder]
```

**Confidence scoring:**
- The agent assigns a confidence score based on: citation clarity, ambiguity level, completeness of spec information available
- If confidence < 0.75: flag for senior review with reasoning
- If confidence < 0.50: escalate to human immediately without staging a draft

### Step 6: RFI Log Update

The agent maintains a running `RFI_Log.csv` in the project's `02 - Construction/RFIs/` folder:

| RFI# | Date Received | From | Subject | Status | Date Responded | Response Summary |
|------|--------------|------|---------|--------|---------------|-----------------|
| RFI-045 | 2026-03-18 | ABC Contractors | Concrete PSI conflict | STAGED | — | — |

The log is updated to `STAGED` when the draft is created and to `RESPONDED` after human approval.

### Step 7: Stage for Human Review

- Draft response filed to Drive: `04 - Agent Workspace/Thought Chains/{task_id}/draft_rfi_response.md`
- RFI log updated
- Task transitioned to `STAGED_FOR_REVIEW` via WorkflowEngine
- CA staff sees the draft in the Action Dashboard with:
  - Original RFI (from contractor)
  - Agent's draft response
  - Citations used
  - Confidence score
  - Thought chain (accessible via link)

---

## 5. RFI Numbering

The system assigns Teter's internal RFI number (distinct from the contractor's submitted number):

```
RFI-{NNN}
```

The counter is managed by the Drive Integration service (INT-DRIVE-001) atomically. The contractor's original number is preserved in the `rfi_number_submitted` field for cross-reference.

---

## 6. Confidence-Based Escalation

| Confidence | Action |
|-----------|--------|
| ≥ 0.75 | Stage draft for human review |
| 0.50–0.74 | Stage draft with `REVIEW_CAREFULLY` flag and detailed reasoning |
| < 0.50 | Escalate directly to human (`ESCALATED_TO_HUMAN`); do not stage a draft |

The confidence score is displayed prominently in the Action Dashboard for the reviewing CA staff member.

---

## 7. Playbook Rules (Tier 1 KG — Phase 0 Seed)

Key playbook rules seeded into Tier 1 of the Knowledge Graph:

| Rule | Condition | Action |
|------|-----------|--------|
| Spec/Drawing conflict | Spec and drawing show different requirements | Cite AIA A201 Section 1.2.1 (documents are complementary; most stringent governs); flag for CA staff review |
| Incomplete information | RFI question lacks sufficient detail to answer | Draft clarification request back to contractor |
| Out of scope | RFI about work not in Teter's scope | Draft response noting jurisdiction and correct party to contact |
| Design decision required | Question requires architectural judgment | Escalate to CA staff; do not draft a response |
| Code compliance question | Question involves building code interpretation | Include disclaimer that contractor must verify with AHJ |

---

## 8. Thought Chain Capture

All KG queries, prompt inputs/outputs, and reasoning steps are captured per AUDIT-001:

```
04 - Agent Workspace/Thought Chains/{task_id}/
  ├── 01_extraction.json
  ├── 02_kg_queries.json
  ├── 03_drawing_analysis.json   (if applicable)
  ├── 04_draft_generation.json
  └── 05_confidence_assessment.json
```

---

## 9. Configuration & Environment Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `RFI_CONFIDENCE_THRESHOLD_STAGE` | Env var (default: 0.75) | Min confidence to stage draft |
| `RFI_CONFIDENCE_THRESHOLD_ESCALATE` | Env var (default: 0.50) | Below this → escalate without draft |
| `RFI_MAX_SPEC_CITATIONS` | Env var (default: 5) | Max spec sections to include in response |
| `RFI_RESPONSE_DEADLINE_DAYS` | Env var (default: 10) | Standard response window (for urgency calc) |

---

## 10. Testing Requirements

- Unit: RFI extraction correctly parses 10+ diverse RFI email/PDF samples
- Unit: KG spec section search returns relevant results for 5 common RFI topics
- Unit: response draft is formatted per template for each confidence tier
- Unit: RFI log CSV is correctly updated on staging and approval
- Integration: full pipeline from `ASSIGNED_TO_AGENT` → `STAGED_FOR_REVIEW` with a real RFI
- Integration: confidence < 0.50 correctly results in `ESCALATED_TO_HUMAN` (no draft staged)
- Integration: thought chain files created in correct Drive location

---

## 11. Open Questions

| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | Should the RFI Agent attempt to process RFI attachments that are not PDFs (e.g., Word docs, CAD files)? | Tech Lead | Open |
| 2 | What happens when multiple RFIs arrive in the same email? Split into separate tasks or treat as one? | CA Director | Open |
| 3 | Should the RFI log be a CSV, a Google Sheet, or a Firestore collection? | CA Director | Open |
| 4 | Is the "design decision required" escalation rule appropriate for Phase 0, or should the agent always attempt a draft? | CA Director | Open |

---

## 12. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v0.1.0 | 2026-03-18 | TeterAI Team | Initial draft |
