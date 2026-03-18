# TETER-CA-AI-AUDIT-001 — Audit Trail & Logging

| Field | Value |
|-------|-------|
| Document ID | TETER-CA-AI-AUDIT-001 |
| Version | v0.1.0 |
| Status | Draft |
| Phase | Phase 0 — Foundation |
| Last Updated | 2026-03-18 |

---

## 1. Purpose & Scope

This specification defines the audit trail and logging system for TeterAI_CA. Every agent action, AI call, human decision, and system event is logged with sufficient detail to reconstruct the full history of any document's lifecycle.

The audit trail serves three purposes:
1. **Accountability** — who did what, when, and why
2. **Debugging** — trace agent behavior for quality improvement
3. **Regulatory compliance** — construction projects require documented decision trails

**Immutability guarantee:** Audit log entries are append-only. No entry may be modified or deleted after creation.

**In scope:** Agent action logs, AI call logs, human review logs, thought chain capture, system event logs.

**Out of scope:** Application-level error logs (handled by GCP Cloud Logging separately), performance metrics (future phase).

---

## 2. Dependencies

| Dependency | Type | Notes |
|-----------|------|-------|
| Firestore | GCP service | Primary audit log store |
| Google Drive | GCP service | Thought chain storage |
| TETER-CA-AI-SEC-001 | Internal spec | Log access is role-controlled |
| TETER-CA-AI-AEC-001 | Internal spec | AI call metadata logged per call |

---

## 3. Architecture Overview

```
Any System Component
        │
        ▼
  Audit Logger (shared library)
        │
        ├──▶ Firestore: audit_logs/{log_id}      ← structured events (all types)
        │
        └──▶ Google Drive: 04 - Agent Workspace/
                           └── Thought Chains/
                               └── {task_id}/    ← full reasoning traces
```

---

## 4. Log Entry Types

### 4.1 Agent Action Log

Written every time an agent completes a processing step.

```json
{
  "log_id": "uuid-v4",
  "log_type": "AGENT_ACTION",
  "timestamp": "2026-03-18T14:32:00Z",
  "agent_id": "AGENT-RFI-001",
  "task_id": "task_abc123",
  "action": "DRAFT_RFI_RESPONSE",
  "input_summary": "RFI-045 from ABC Contractors re: structural spec section 03 30 00",
  "output_summary": "Draft response citing spec section 03 30 00 paragraph 2.3",
  "confidence_score": 0.87,
  "ai_call_ids": ["aicall_xyz789"],
  "duration_ms": 4200,
  "status": "SUCCESS"
}
```

### 4.2 AI Call Log

Written by the AI Engine for every LLM API call (see AEC-001).

```json
{
  "log_id": "uuid-v4",
  "log_type": "AI_CALL",
  "timestamp": "2026-03-18T14:32:01Z",
  "ai_call_id": "aicall_xyz789",
  "task_id": "task_abc123",
  "calling_agent": "AGENT-RFI-001",
  "capability_class": "REASON_DEEP",
  "tier_used": 1,
  "provider": "anthropic",
  "model": "claude-opus-4-6",
  "fallback_triggered": false,
  "input_tokens": 3200,
  "output_tokens": 512,
  "latency_ms": 1842,
  "status": "SUCCESS"
}
```

### 4.3 Human Review Log

Written when a CA staff member takes an action on a staged document.

```json
{
  "log_id": "uuid-v4",
  "log_type": "HUMAN_REVIEW",
  "timestamp": "2026-03-18T15:10:00Z",
  "task_id": "task_abc123",
  "reviewer_uid": "google-uid-staff1",
  "reviewer_name": "Jane Smith",
  "action": "APPROVED",
  "original_draft_version": "v1",
  "edits_made": true,
  "edit_summary": "Corrected spec citation from 03 30 00 to 03 30 10",
  "correction_type": "citation",
  "duration_seconds": 142,
  "delivery_triggered": true
}
```

`action` values: `APPROVED` | `REJECTED` | `EDITED_AND_APPROVED` | `ESCALATED`

### 4.4 System Event Log

Written for infrastructure-level events.

```json
{
  "log_id": "uuid-v4",
  "log_type": "SYSTEM_EVENT",
  "timestamp": "2026-03-18T14:00:00Z",
  "event": "EMAIL_POLL_COMPLETED",
  "component": "AGENT-DISPATCH-001",
  "details": {
    "emails_found": 3,
    "tasks_created": 2,
    "duplicates_skipped": 1
  },
  "status": "SUCCESS"
}
```

### 4.5 Error Log

Written whenever a component encounters a non-fatal or fatal error.

```json
{
  "log_id": "uuid-v4",
  "log_type": "ERROR",
  "timestamp": "2026-03-18T14:05:00Z",
  "component": "AI_ENGINE",
  "task_id": "task_abc123",
  "error_code": "AI_TIER1_TIMEOUT",
  "error_message": "Claude API timeout after 30s",
  "fallback_action": "TIER2_ATTEMPTED",
  "severity": "WARNING"
}
```

`severity` values: `DEBUG` | `INFO` | `WARNING` | `ERROR` | `CRITICAL`

---

## 5. Firestore Collection Structure

```
audit_logs/
  {log_id}/                    # Document per log entry
    log_type: String
    timestamp: Timestamp
    task_id: String (indexed)
    agent_id: String (indexed)
    ... (type-specific fields)

audit_logs_by_task/
  {task_id}/
    logs: [log_id, ...]        # Ordered list of log IDs for a task (fast lookup)
```

### 5.1 Immutability Enforcement

Firestore security rules prevent any modification or deletion of `audit_logs` documents:

```javascript
// Firestore security rules
match /audit_logs/{logId} {
  allow create: if request.auth != null;   // service accounts can write
  allow read: if request.auth.token.role in ['CA_STAFF', 'ADMIN'];
  allow update, delete: never;             // immutable
}
```

---

## 6. Thought Chain Capture

Agent reasoning traces (full prompt + response chains) are too large for Firestore. They are stored in Google Drive:

```
04 - Agent Workspace/
└── Thought Chains/
    └── {task_id}/
        ├── 01_classification.json          # Dispatcher classification reasoning
        ├── 02_rfi_processing.json          # RFI Agent reasoning
        └── 03_draft_generation.json        # Document generation trace
```

### 6.1 Thought Chain Schema

```json
{
  "task_id": "task_abc123",
  "agent_id": "AGENT-RFI-001",
  "step": "rfi_processing",
  "timestamp": "2026-03-18T14:32:00Z",
  "system_prompt": "...",
  "user_prompt": "...",
  "model_response": "...",
  "knowledge_graph_queries": [
    { "query_type": "search_spec_sections", "query": "concrete compressive strength", "results_count": 3 }
  ],
  "confidence_score": 0.87
}
```

---

## 7. Retention Policy

| Log Type | Retention Period | Notes |
|----------|-----------------|-------|
| Agent Action Logs | 7 years | Construction project legal requirement |
| AI Call Logs | 1 year | Cost and performance analysis |
| Human Review Logs | 7 years | Decision trail requirement |
| System Event Logs | 90 days | Operational use only |
| Error Logs | 1 year | Debugging |
| Thought Chains (Drive) | 2 years | Quality improvement |

Retention enforcement: Cloud Firestore TTL policies for time-limited entries; Drive files archived to cold storage after retention period.

---

## 8. Audit Trail Query Interface

For the Admin Panel (UI-001) and debugging:

```python
class AuditLogger:
    def log(self, entry: AuditEntry) -> str: ...               # returns log_id
    def get_task_timeline(self, task_id: str) -> list[AuditEntry]: ...
    def get_agent_activity(self, agent_id: str, since: datetime) -> list[AuditEntry]: ...
    def get_reviewer_history(self, reviewer_uid: str) -> list[HumanReviewLog]: ...
```

---

## 9. Testing Requirements

- Verify `update` and `delete` on `audit_logs` are rejected by Firestore rules
- Verify every AI call generates an `AI_CALL` log entry (integration with AEC-001)
- Verify every human approval/rejection generates a `HUMAN_REVIEW` log entry
- Verify thought chains are written to correct Drive path per task ID
- Verify `get_task_timeline` returns events in chronological order

---

## 10. Open Questions

| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | 7-year retention — should this match the project closeout date or the email receipt date? | Legal/Admin | Open |
| 2 | Should thought chains be encrypted at rest beyond Google's default? | Tech Lead | Open |

---

## 11. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v0.1.0 | 2026-03-18 | TeterAI Team | Initial draft |
