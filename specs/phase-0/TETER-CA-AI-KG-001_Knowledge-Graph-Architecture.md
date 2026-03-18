# TETER-CA-AI-KG-001 — Knowledge Graph Architecture & Schema

| Field | Value |
|-------|-------|
| Document ID | TETER-CA-AI-KG-001 |
| Version | v0.1.0 |
| Status | Draft |
| Phase | Phase 0 — Foundation |
| Last Updated | 2026-03-18 |

---

## 1. Purpose & Scope

This specification defines the Knowledge Graph (KG) — the persistent intelligence layer that governs agent behavior, encodes workflow standards, and accumulates company- and industry-specific knowledge over time.

The KG serves as the authoritative source for:
- **Agent playbooks** (how each agent should behave)
- **Workflow process standards** (CA department procedures)
- **Company knowledge** (Teter-specific standards, preferences, past decisions)
- **Industry knowledge** (construction specifications, contract standards, regulatory requirements)

Human corrections to agent outputs flow back into the KG as a continuous improvement loop.

**In scope (Phase 0):**
- Neo4j schema definition (all 4 tiers)
- Phase 0 seed data: Tier 2 (Workflow baseline) + Tier 4 (Industry baseline)
- Vector embedding overlay for semantic search
- Query interface for agents
- Correction ingestion pipeline

**Out of scope (Phase 0):** Full population of Tier 3 (Company Knowledge) — placeholder structure only.

---

## 2. Dependencies

| Dependency | Type | Notes |
|-----------|------|-------|
| Neo4j Aura | GCP-hosted | Managed Neo4j graph database |
| TETER-CA-AI-SEC-001 | Internal spec | Neo4j credentials in Secret Manager |
| TETER-CA-AI-AUDIT-001 | Internal spec | KG writes must be audited |
| TETER-CA-AI-AEC-001 | Internal spec | AI Engine used to generate embeddings |

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                  Knowledge Graph                     │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │ Tier 1: Agent Playbooks                      │   │
│  │   Per-agent decision trees & rules           │   │
│  ├──────────────────────────────────────────────┤   │
│  │ Tier 2: Workflow Process                     │   │
│  │   CA department SOPs & workflow standards    │   │
│  ├──────────────────────────────────────────────┤   │
│  │ Tier 3: Company Knowledge                    │   │
│  │   Teter-specific decisions, preferences      │   │
│  ├──────────────────────────────────────────────┤   │
│  │ Tier 4: Industry Knowledge                   │   │
│  │   CSI specs, AIA contracts, building codes   │   │
│  └──────────────────────────────────────────────┘   │
│                       │                              │
│         Vector Embedding Overlay                     │
│         (semantic search across all tiers)           │
└─────────────────────────────────────────────────────┘
```

---

## 4. 4-Tier Schema Definition

### 4.1 Tier 1 — Agent Playbooks

Stores per-agent behavioral rules, decision trees, and escalation thresholds.

**Node types:**

```cypher
(:Agent {
  agent_id: String,          // e.g., "AGENT-RFI-001"
  name: String,
  version: String,
  phase: String              // "phase-0", "phase-1", etc.
})

(:PlaybookRule {
  rule_id: String,
  description: String,
  condition: String,         // natural language condition
  action: String,            // natural language action
  confidence_threshold: Float,  // below this → escalate to human
  priority: Integer
})

(:EscalationCriteria {
  criteria_id: String,
  trigger: String,
  escalation_type: String    // "human_queue" | "senior_review" | "reject"
})
```

**Relationships:**
```cypher
(:Agent)-[:HAS_RULE]->(:PlaybookRule)
(:Agent)-[:ESCALATES_ON]->(:EscalationCriteria)
(:PlaybookRule)-[:LEADS_TO]->(:PlaybookRule)   // decision tree edges
```

### 4.2 Tier 2 — Workflow Process

Encodes CA department standard operating procedures and document workflows.

**Node types:**

```cypher
(:DocumentType {
  type_id: String,           // e.g., "RFI", "SUBMITTAL", "CHANGE_ORDER"
  name: String,
  phase: String,             // "bid" | "construction" | "closeout"
  numbering_prefix: String,  // e.g., "RFI-"
  response_deadline_days: Integer
})

(:WorkflowStep {
  step_id: String,
  name: String,
  description: String,
  responsible_party: String, // "contractor" | "ca_agent" | "ca_staff" | "client"
  sequence: Integer
})

(:ReviewRequirement {
  requirement_id: String,
  description: String,
  mandatory: Boolean
})
```

**Relationships:**
```cypher
(:DocumentType)-[:FOLLOWS_WORKFLOW]->(:WorkflowStep)
(:WorkflowStep)-[:NEXT_STEP]->(:WorkflowStep)
(:WorkflowStep)-[:REQUIRES_REVIEW]->(:ReviewRequirement)
```

### 4.3 Tier 3 — Company Knowledge

Teter-specific decisions, client preferences, project history, and internal standards.

**Node types (Phase 0: structure only, minimal seed data):**

```cypher
(:Company {
  name: "Teter Architects",
  preferences: Map
})

(:ClientStandard {
  client_id: String,
  standard_id: String,
  description: String,
  applies_to: [String]       // document type IDs
})

(:PastDecision {
  decision_id: String,
  context: String,
  decision_text: String,
  rationale: String,
  date: DateTime,
  applies_to_doc_types: [String]
})
```

**Relationships:**
```cypher
(:Company)-[:HAS_STANDARD]->(:ClientStandard)
(:PastDecision)-[:APPLIES_TO]->(:DocumentType)
```

### 4.4 Tier 4 — Industry Knowledge

Construction industry standards, specification sections, contract templates, and regulatory requirements.

**Node types:**

```cypher
(:SpecSection {
  csi_division: String,      // e.g., "03" (Concrete)
  section_number: String,    // e.g., "03 30 00"
  title: String,
  content_summary: String,
  keywords: [String]
})

(:ContractClause {
  clause_id: String,
  standard: String,          // "AIA-A201", "ConsensusDocs", etc.
  clause_number: String,
  title: String,
  text: String
})

(:RegulatoryRequirement {
  req_id: String,
  jurisdiction: String,
  authority: String,
  description: String,
  applies_to: [String]
})
```

**Relationships:**
```cypher
(:SpecSection)-[:REFERENCES]->(:SpecSection)
(:ContractClause)-[:GOVERNS]->(:DocumentType)
(:RegulatoryRequirement)-[:APPLIES_TO]->(:DocumentType)
```

---

## 5. Vector Embedding Overlay

All node types with text content (`content_summary`, `text`, `description`, `decision_text`) are embedded using the AI Engine's `EXTRACT` capability class and stored as vector properties on the node.

### 5.1 Embedding Schema

```cypher
// Each embeddable node has an additional property:
embedding: [Float]           // 1536-dimension vector (text-embedding-3-small or equivalent)
embedding_model: String      // model used for traceability
embedding_updated_at: DateTime
```

### 5.2 Semantic Search Query Pattern

```cypher
// Find SpecSections most semantically similar to a query vector
CALL db.index.vector.queryNodes('spec_section_embeddings', 5, $query_vector)
YIELD node, score
WHERE score > 0.75
RETURN node.section_number, node.title, node.content_summary, score
ORDER BY score DESC
```

### 5.3 Phase 0 Vector Indexes

| Index Name | Node Label | Property |
|-----------|-----------|---------|
| `spec_section_embeddings` | SpecSection | embedding |
| `contract_clause_embeddings` | ContractClause | embedding |
| `playbook_rule_embeddings` | PlaybookRule | embedding |

---

## 6. Phase 0 Seed Data Plan

### Tier 2 Baseline (required for Phase 0)
- RFI workflow steps (construction phase)
- Submittal workflow steps (placeholder)
- Document type definitions for all Phase 0 document types
- Response deadline standards (RFI: 10 days, Submittal: 14 days)

### Tier 4 Baseline (required for Phase 0)
- CSI MasterFormat division index (16 divisions minimum)
- Key AIA A201 clauses relevant to RFI workflow (Sections 3.2, 4.3, 9.3)
- Common RFI-triggering spec sections (structural, mechanical, electrical basics)

### Tier 1 Baseline (required for Phase 0)
- Dispatcher Agent playbook (email classification rules)
- RFI Agent playbook (RFI processing decision tree)

---

## 7. Continuous Improvement Loop

When a CA staff member modifies an agent's draft:
1. The diff (original draft vs. approved output) is captured by the Workflow Engine (WF-001)
2. A `CorrectionEvent` node is created in the KG:

```cypher
(:CorrectionEvent {
  event_id: String,
  agent_id: String,
  task_id: String,
  original_text: String,
  corrected_text: String,
  correction_type: String,   // "tone" | "content" | "citation" | "format"
  reviewed_by: String,       // staff user ID
  timestamp: DateTime
})
(:CorrectionEvent)-[:UPDATES]->(:PlaybookRule)
```

3. Periodic (weekly) review process: high-frequency corrections are analyzed and used to update PlaybookRules in Tier 1.

---

## 8. Query Interface for Agents

Agents use a structured query layer (not raw Cypher) to interact with the KG:

```python
class KnowledgeGraphClient:
    def get_agent_playbook(self, agent_id: str) -> list[PlaybookRule]: ...
    def search_spec_sections(self, query: str, top_k: int = 5) -> list[SpecSection]: ...
    def get_document_workflow(self, doc_type: str) -> list[WorkflowStep]: ...
    def get_contract_clause(self, clause_id: str) -> ContractClause: ...
    def log_correction(self, correction: CorrectionEvent) -> None: ...
```

---

## 9. Configuration & Environment Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `NEO4J_URI` | Secret Manager: `kg/neo4j-uri` | Neo4j Aura connection URI |
| `NEO4J_USERNAME` | Secret Manager: `kg/neo4j-username` | Neo4j username |
| `NEO4J_PASSWORD` | Secret Manager: `kg/neo4j-password` | Neo4j password |
| `KG_EMBEDDING_SIMILARITY_THRESHOLD` | Env var (default: 0.75) | Min score for semantic results |
| `KG_VECTOR_TOP_K` | Env var (default: 5) | Max results per semantic search |

---

## 10. Testing Requirements

- Unit: verify Cypher queries return correct node types
- Unit: vector similarity search returns results above threshold
- Integration: seed data loads correctly into Neo4j Aura
- Integration: correction events are persisted and linked to playbook rules
- Integration: KnowledgeGraphClient methods return typed Python objects
- Performance: semantic search completes in < 500ms for top-5 results

---

## 11. Open Questions

| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | Which embedding model to use? (Prefer same provider as Tier 1 AI calls for cost consolidation) | Tech Lead | Open |
| 2 | How granular should Tier 4 spec content be — full text or summaries only? | CA Director | Open |
| 3 | What triggers a Tier 1 playbook update from correction events — manual review or automatic? | Product | Open |

---

## 12. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v0.1.0 | 2026-03-18 | TeterAI Team | Initial draft |
