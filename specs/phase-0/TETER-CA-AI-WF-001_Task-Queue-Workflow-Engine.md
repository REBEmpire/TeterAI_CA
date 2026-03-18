# TETER-CA-AI-WF-001 — Task Queue & Workflow Engine

| Field | Value |
|-------|-------|
| Document ID | TETER-CA-AI-WF-001 |
| Version | v0.1.0 |
| Status | Draft |
| Phase | Phase 0 — Foundation |
| Last Updated | 2026-03-18 |

---

## 1. Purpose & Scope

This specification defines the Task Queue & Workflow Engine — the central nervous system that tracks every document from ingest through final delivery. Every action taken by agents or humans is mediated through the workflow engine via task state transitions.

The workflow engine ensures:
- **No document is lost** — every ingest creates a task, every task has a state
- **Human review is enforced** — no output leaves the system without an `APPROVED` state transition
- **Full traceability** — task history captures every state change and who/what triggered it
- **Agent coordination** — the Dispatcher assigns tasks; specialist agents pick up their queue

**In scope:** Task schema, state machine, Firestore task store, assignment logic, 20-minute queue review cycle, human staging mechanism, correction capture.

**Out of scope:** Agent-specific processing logic (in agent specs), UI rendering of the queue (in UI-001).

---

## 2. Dependencies

| Dependency | Type | Notes |
|-----------|------|-------|
| Firestore | GCP service | Task store |
| Cloud Scheduler | GCP service | 20-minute queue review trigger |
| TETER-CA-AI-AEC-001 | Internal spec | AI Engine used within agents |
| TETER-CA-AI-AUDIT-001 | Internal spec | All state transitions logged |
| TETER-CA-AI-SEC-001 | Internal spec | Role-based task access |
| TETER-CA-AI-INT-DRIVE-001 | Internal spec | File routing on task state changes |

---

## 3. Architecture Overview

```
EmailIngest (from Gmail)
        │
        ▼
   Task Created (PENDING_CLASSIFICATION)
        │
        ▼ [Dispatcher picks up]
   CLASSIFYING
        │
        ├──▶ ASSIGNED_TO_AGENT → [Specialist agent processes]
        │                               │
        │                               ▼
        │                         PROCESSING
        │                               │
        │                               ▼
        │                         STAGED_FOR_REVIEW  ←── Human sees in Action Dashboard
        │                               │
        │               ┌──────────────┴──────────────┐
        │               ▼                             ▼
        │          APPROVED                       REJECTED
        │               │                             │
        │               ▼                             ▼
        │          DELIVERED                    RETURNED_TO_AGENT (re-process)
        │
        └──▶ ESCALATED_TO_HUMAN (low confidence or UNKNOWN type)
```

---

## 4. Task Schema

```
tasks/
  {task_id}/
    task_id: String                    # UUID v4
    ingest_id: String                  # EmailIngest record ID
    project_id: String | null          # Set after classification
    project_number: String | null      # e.g., "2026-003"
    document_type: String | null       # e.g., "RFI", "SUBMITTAL"
    document_number: String | null     # e.g., "RFI-045" (assigned on filing)
    phase: String | null               # "bid" | "construction" | "closeout"
    urgency: String                    # "HIGH" | "MEDIUM" | "LOW"
    status: TaskStatus
    assigned_agent: String | null      # e.g., "AGENT-RFI-001"
    assigned_reviewer: String | null   # CA staff UID
    created_at: Timestamp
    updated_at: Timestamp
    status_history: [StatusHistoryEntry]
    draft_drive_path: String | null    # Path to agent's draft in Drive
    final_drive_path: String | null    # Path after filing
    classification_confidence: Float | null
    error_message: String | null
    correction_captured: Boolean       # true if human made edits
```

### 4.1 StatusHistoryEntry

```json
{
  "from_status": "PROCESSING",
  "to_status": "STAGED_FOR_REVIEW",
  "triggered_by": "AGENT-RFI-001",
  "trigger_type": "AGENT",
  "timestamp": "2026-03-18T14:35:00Z",
  "notes": null
}
```

`trigger_type` values: `AGENT` | `HUMAN` | `SCHEDULER` | `SYSTEM`

---

## 5. Task State Machine

| State | Description | Allowed Transitions | Trigger |
|-------|-------------|--------------------|---------|
| `PENDING_CLASSIFICATION` | Email ingested, awaiting Dispatcher | → `CLASSIFYING` | Dispatcher picks up |
| `CLASSIFYING` | Dispatcher is classifying the email | → `ASSIGNED_TO_AGENT`, `ESCALATED_TO_HUMAN` | Dispatcher completes |
| `ASSIGNED_TO_AGENT` | Routed to specialist agent, awaiting pickup | → `PROCESSING` | Agent picks up |
| `PROCESSING` | Specialist agent is working | → `STAGED_FOR_REVIEW`, `ERROR` | Agent completes or fails |
| `STAGED_FOR_REVIEW` | Draft ready; in human Action Dashboard | → `APPROVED`, `REJECTED`, `ESCALATED_TO_HUMAN` | Human action |
| `APPROVED` | Human approved (with or without edits) | → `DELIVERED` | Delivery system |
| `REJECTED` | Human rejected; returned for rework | → `ASSIGNED_TO_AGENT` | Workflow engine (re-queue) |
| `DELIVERED` | Final document sent/filed | Terminal state | — |
| `ESCALATED_TO_HUMAN` | Low confidence / unknown type; human handles manually | → `ASSIGNED_TO_AGENT`, `DELIVERED`, `REJECTED` | Human action |
| `ERROR` | Processing failed; requires investigation | → `ASSIGNED_TO_AGENT` (after fix) | Ops/Admin |

---

## 6. Queue Review Cycle (20-Minute Scheduler)

In addition to event-driven processing, a Cloud Scheduler job runs every 20 minutes to:

1. **Sweep stale tasks** — tasks stuck in `CLASSIFYING` or `PROCESSING` for > 10 minutes get an `ERROR` flag and alert
2. **Re-queue rejected tasks** — tasks in `REJECTED` state are reassigned to the original agent with the rejection notes appended
3. **Urgency escalation** — tasks in `STAGED_FOR_REVIEW` for > 24 hours (HIGH urgency) or > 48 hours (MEDIUM) are escalated with a notification
4. **Pickup sweep** — tasks in `ASSIGNED_TO_AGENT` for > 5 minutes without agent pickup trigger a retry

```
Cloud Scheduler (every 20 min)
        │
        ▼
Workflow Engine: POST /queue-review
        ├── stale task detection
        ├── rejected task re-queue
        ├── urgency escalation
        └── pickup sweep
```

---

## 7. Urgency Classification

Urgency is set by the Dispatcher Agent during classification, based on:

| Urgency | Criteria |
|---------|---------|
| `HIGH` | RFI or CO with explicit deadline < 3 days, subject contains "URGENT", or 48-hr response required by contract |
| `MEDIUM` | Standard RFI (10-day response window), most submittals |
| `LOW` | Informational items, meeting minutes, administrative documents |

---

## 8. Human Review Staging

When a task enters `STAGED_FOR_REVIEW`:

1. Task appears in the Action Dashboard (UI-001) sorted by urgency then age
2. Agent's draft is accessible in the Split-Screen Viewer
3. Reviewer can: **Approve** | **Edit + Approve** | **Reject** | **Escalate**
4. On **Edit + Approve**: diff is captured and stored as a `CorrectionEvent` in the Knowledge Graph (KG-001)
5. On **Approve/Edit + Approve**: task transitions to `APPROVED`, delivery is triggered

---

## 9. Correction Capture

When a human edits a draft before approving:

```python
class CorrectionCapture:
    task_id: str
    agent_id: str
    original_draft: str
    edited_draft: str
    correction_type: str   # inferred: "tone" | "content" | "citation" | "format"
    reviewer_uid: str
    timestamp: datetime
```

This is forwarded to the Knowledge Graph (KG-001) `log_correction()` method.

---

## 10. Firestore Indexes Required

| Collection | Index | Purpose |
|-----------|-------|---------|
| `tasks` | `status` ASC, `urgency` ASC, `created_at` ASC | Action Dashboard query |
| `tasks` | `project_id` ASC, `status` ASC | Project-level task view |
| `tasks` | `assigned_agent` ASC, `status` ASC | Agent queue query |
| `tasks` | `assigned_reviewer` ASC, `status` ASC | Reviewer queue query |

---

## 11. Workflow Engine API

```python
class WorkflowEngine:
    def create_task(self, ingest_id: str) -> Task: ...
    def transition(self, task_id: str, new_status: TaskStatus, triggered_by: str, trigger_type: str, notes: str | None) -> Task: ...
    def assign_to_agent(self, task_id: str, agent_id: str) -> Task: ...
    def assign_to_reviewer(self, task_id: str, reviewer_uid: str) -> Task: ...
    def get_agent_queue(self, agent_id: str) -> list[Task]: ...
    def get_review_queue(self, reviewer_uid: str | None = None) -> list[Task]: ...
    def capture_correction(self, task_id: str, original: str, edited: str, reviewer_uid: str) -> None: ...
```

---

## 12. Configuration & Environment Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `WF_STALE_PROCESSING_TIMEOUT_MINUTES` | Env var (default: 10) | Time before a processing task is flagged stale |
| `WF_HIGH_URGENCY_REVIEW_HOURS` | Env var (default: 24) | Hours before HIGH urgency escalation |
| `WF_MEDIUM_URGENCY_REVIEW_HOURS` | Env var (default: 48) | Hours before MEDIUM urgency escalation |

---

## 13. Testing Requirements

- Unit: all valid state transitions succeed; all invalid transitions raise `InvalidTransitionError`
- Unit: urgency escalation fires at correct thresholds
- Unit: correction capture stores diff and routes to KG
- Integration: full task lifecycle (PENDING → DELIVERED) with mock agent and human approval
- Integration: 20-minute scheduler triggers queue review and correctly identifies stale tasks
- Load: 100 concurrent task transitions without Firestore contention

---

## 14. Open Questions

| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | Should rejected tasks go back to the same agent or allow re-assignment to a different one? | Product | Open |
| 2 | Is there a max retry count for rejected tasks before they are permanently escalated to human? | Product | Open |
| 3 | Should the Dispatcher handle all classification, or can Phase 1 agents classify their own incoming tasks? | Tech Lead | Open |

---

## 15. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v0.1.0 | 2026-03-18 | TeterAI Team | Initial draft |
