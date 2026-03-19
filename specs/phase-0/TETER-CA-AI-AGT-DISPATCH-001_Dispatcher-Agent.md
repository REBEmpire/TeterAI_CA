# TETER-CA-AI-AGT-DISPATCH-001 — Dispatcher Agent

| Field | Value |
|-------|-------|
| Document ID | TETER-CA-AI-AGT-DISPATCH-001 |
| Version | v0.1.0 |
| Status | In Progress |
| Phase | Phase 0 — Foundation |
| Last Updated | 2026-03-18 |

---

## 1. Purpose & Scope

The Dispatcher Agent (AGENT-DISPATCH-001) is the orchestration hub of the TeterAI_CA system. Every email ingest passes through the Dispatcher before reaching a specialist agent. The Dispatcher is responsible for:

- **Email classification** — determining project, phase, document type, and urgency
- **Task routing** — assigning classified tasks to the correct specialist agent
- **Ambiguity handling** — escalating low-confidence classifications to human review
- **Queue management** — running a 20-minute sweep to pick up any missed tasks

The Dispatcher never drafts documents — it only classifies and routes.

**In scope (Phase 0):** Email classification, task creation/assignment, confidence-based escalation, 15-minute email poll trigger response, 20-minute task queue sweep.

**Out of scope:** Direct document processing, outbound communication, multi-step orchestration across agents (future phase).

---

## 2. Dependencies

| Dependency | Type | Notes |
|-----------|------|-------|
| TETER-CA-AI-AEC-001 | Internal spec | AI Engine for CLASSIFY capability class |
| TETER-CA-AI-INT-GMAIL-001 | Internal spec | Consumes EmailIngest records |
| TETER-CA-AI-WF-001 | Internal spec | Creates and transitions tasks |
| TETER-CA-AI-KG-001 | Internal spec | Playbook rules for classification |
| TETER-CA-AI-AUDIT-001 | Internal spec | All classification decisions logged |
| Firestore | GCP service | Reads EmailIngest, writes/updates Tasks |
| Cloud Scheduler | GCP service | 15-min email poll + 20-min queue review |

---

## 3. Architecture Overview

```
Cloud Scheduler (every 15 min)       Cloud Scheduler (every 20 min)
          │                                      │
          ▼                                      ▼
  POST /email-poll                    POST /queue-review
          │                                      │
          └──────────────┬───────────────────────┘
                         ▼
                  Dispatcher Agent
                         │
                ┌────────┴────────┐
                ▼                 ▼
        Fetch new           Sweep stale/
        EmailIngest          unassigned
        records              tasks
                │
                ▼
        Classify Email
        (AI Engine: CLASSIFY)
                │
        ┌───────┴────────┐
        ▼                ▼
   High confidence   Low confidence
   (≥ 0.80)          (< 0.80)
        │                │
        ▼                ▼
  Assign to         Escalate to
  Specialist        Human Queue
  Agent
```

---

## 4. Classification Dimensions

The Dispatcher classifies each email across four dimensions:

| Dimension | Values | Example |
|-----------|--------|---------|
| `project_id` | Project ID from registry, or `UNKNOWN` | `2026-003` |
| `phase` | `bid` \| `construction` \| `closeout` \| `UNKNOWN` | `construction` |
| `document_type` | See routing table below | `RFI` |
| `urgency` | `HIGH` \| `MEDIUM` \| `LOW` | `MEDIUM` |

Each dimension has an independent confidence score (0.0–1.0). The minimum confidence across all dimensions determines whether the task is routed or escalated.

### 4.1 Confidence Thresholds

| Threshold | Action |
|-----------|--------|
| All dimensions ≥ 0.80 | Route to specialist agent |
| Any dimension < 0.80 | Escalate to human (`ESCALATED_TO_HUMAN`) with classification notes |

The human reviewer sees the Dispatcher's best-guess classification and can confirm or correct it before routing.

---

## 5. Classification Prompt Design

The Dispatcher uses the `CLASSIFY` capability class. The classification prompt is structured as a single LLM call returning a JSON object:

### 5.1 Input

```
System: You are a construction administration document classifier for Teter Architects.
        Your job is to classify incoming emails by project, phase, document type, and urgency.
        Known projects: {project_list}
        Known document types: {doc_type_list}
        Return a JSON object with the schema below.

User:   Email from: {sender_email} ({sender_name})
        Subject: {subject}
        Body (first 2000 chars): {body_excerpt}
        Attachments: {attachment_names}
        Subject hints: {subject_hints}
```

### 5.2 Output Schema (from AI Engine)

```json
{
  "project_id": "2026-003",
  "project_confidence": 0.95,
  "phase": "construction",
  "phase_confidence": 0.90,
  "document_type": "RFI",
  "doc_type_confidence": 0.88,
  "urgency": "MEDIUM",
  "urgency_confidence": 0.85,
  "reasoning": "Subject contains 'RFI #045', sender is known contractor ABC Contractors on project 2026-003, no deadline mentioned."
}
```

---

## 6. Document Type → Agent Routing Table

| Document Type | Phase | Assigned Agent (Phase 0) | Phase 1+ Agent |
|--------------|-------|--------------------------|----------------|
| `RFI` | Construction | `AGENT-RFI-001` | — |
| `SUBMITTAL` | Construction | `ESCALATED_TO_HUMAN` (Phase 0) | `AGENT-SUBMITTAL-001` |
| `SUBSTITUTION_REQUEST` | Construction | `ESCALATED_TO_HUMAN` (Phase 0) | `AGENT-SUBST-001` |
| `PCO_COR` | Construction | `ESCALATED_TO_HUMAN` (Phase 0) | `AGENT-CO-001` |
| `BULLETIN` | Construction | `ESCALATED_TO_HUMAN` (Phase 0) | `AGENT-BULLETIN-001` |
| `CHANGE_ORDER` | Construction | `ESCALATED_TO_HUMAN` (Phase 0) | `AGENT-CO-001` |
| `PAY_APPLICATION` | Construction | `ESCALATED_TO_HUMAN` (Phase 0) | `AGENT-PAY-001` |
| `MEETING_MINUTES` | Construction | `ESCALATED_TO_HUMAN` (Phase 0) | `AGENT-MM-001` |
| `PB_RFI` | Bid | `ESCALATED_TO_HUMAN` (Phase 0) | `AGENT-PBRFI-001` |
| `ADDENDUM` | Bid | `ESCALATED_TO_HUMAN` (Phase 0) | `AGENT-ADDENDA-001` |
| `UNKNOWN` | Any | `ESCALATED_TO_HUMAN` | — |

In Phase 0, only `RFI` (Construction) routes to a specialist agent. All other types are escalated to human with the classification attached so CA staff can act on them manually.

---

## 7. Project Registry Lookup

The Dispatcher maintains a local (Firestore-backed) project registry mapping:
- Known sender email addresses → project IDs
- Known project numbers (from subject hints) → project IDs
- Active project names → project IDs

```
project_registry/
  {project_id}/
    project_number: String           # e.g., "2026-003"
    project_name: String
    known_senders: [String]          # contractor/client email addresses
    phase: String                    # current active phase
    is_active: Boolean
```

This registry is managed by the Admin via the Web App Config Panel.

---

## 8. Escalation Message

When a task is escalated to human, the Dispatcher writes an escalation note to the task:

```
Classification Confidence Below Threshold

Best guess:
  Project: 2026-003 (confidence: 0.95)
  Phase: construction (confidence: 0.90)
  Document type: SUBMITTAL (confidence: 0.72)  ← below threshold
  Urgency: MEDIUM (confidence: 0.85)

Reasoning: Subject mentions "submittal" but no submittal number found.
           Sender is a known contractor but submittals are not yet handled automatically.

Action required: Please confirm classification and route manually.
```

---

## 9. Execution Schedule

| Trigger | Schedule | Cloud Run Endpoint | Action |
|---------|----------|--------------------|--------|
| Email poll response | Every 15 min (via Cloud Scheduler) | `POST /email-poll` | Fetch and classify new EmailIngest records |
| Queue review | Every 20 min (via Cloud Scheduler) | `POST /queue-review` | Sweep unassigned tasks, re-queue rejected tasks |

---

## 10. Configuration & Environment Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `DISPATCH_CLASSIFICATION_CONFIDENCE_THRESHOLD` | Env var (default: 0.80) | Min confidence for auto-routing |
| `DISPATCH_MAX_EMAILS_PER_CYCLE` | Env var (default: 50) | Safety cap per poll cycle |
| `DISPATCH_STALE_TASK_TIMEOUT_MINUTES` | Env var (default: 10) | Minutes before a classifying task is flagged stale |

---

## 11. Error Handling

| Error | Behavior |
|-------|----------|
| AI classification fails (all tiers exhausted) | Task transitions to `ERROR`; alert logged; task flagged for human review |
| Project not found in registry | Mark `project_id: UNKNOWN`, confidence 0.0, escalate to human |
| EmailIngest record malformed | Log ERROR, skip record, leave `PENDING_CLASSIFICATION` for retry |
| Firestore write failure | Log CRITICAL, retry up to 3 times with exponential backoff |

---

## 12. Testing Requirements

- Unit: classification prompt generates valid JSON for 20+ diverse email samples
- Unit: confidence threshold routing (mock AI response with varying confidence levels)
- Unit: routing table correctly maps each document type to correct agent/escalation
- Unit: escalation note is correctly formatted
- Integration: full classification cycle (EmailIngest → Task `ASSIGNED_TO_AGENT`)
- Integration: low-confidence email correctly escalated (`ESCALATED_TO_HUMAN`) with notes
- Integration: 20-min queue review sweep picks up missed `PENDING_CLASSIFICATION` tasks

---

## 13. Open Questions

| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | Should the confidence threshold be configurable per document type (e.g., CO requires 0.95)? | Product | Open |
| 2 | For email threads (replies), should the Dispatcher classify the thread or only the latest message? | Tech Lead | Open |
| 3 | How should the Dispatcher handle forwarded emails (e.g., CA staff forwarding a contractor email)? | CA Director | Open |

---

## 14. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v0.1.0 | 2026-03-18 | TeterAI Team | Initial draft |
