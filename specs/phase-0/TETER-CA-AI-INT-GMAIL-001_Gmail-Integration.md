# TETER-CA-AI-INT-GMAIL-001 — Gmail Integration

| Field | Value |
|-------|-------|
| Document ID | TETER-CA-AI-INT-GMAIL-001 |
| Version | v0.2.0 |
| Status | In Progress |
| Phase | Phase 0 — Foundation |
| Last Updated | 2026-03-18 |

---

## 1. Purpose & Scope

This specification defines the Gmail integration layer — the system's primary inbound channel for receiving construction administration documents from contractors, clients, and consultants.

The Gmail integration is responsible for:
- **Polling** a designated Gmail inbox every 15 minutes
- **Parsing** emails (subject, sender, body, attachments)
- **Deduplication** — ensuring each email is processed exactly once
- **Attachment extraction** — routing attachments to the Google Drive Holding Folder
- **Handoff** to the Dispatcher Agent for classification

This integration is read-only from the CA staff's perspective. The system reads and labels emails but does not send any email in Phase 0.

**In scope:** Inbound email polling, parsing, deduplication, attachment routing, Dispatcher handoff.

**Out of scope:** Outbound email (Phase 1+), spam filtering, calendar events.

---

## 2. Dependencies

| Dependency | Type | Notes |
|-----------|------|-------|
| Gmail API v1 | Google API | Email read/modify |
| TETER-CA-AI-SEC-001 | Internal spec | OAuth credentials and scopes |
| TETER-CA-AI-INT-DRIVE-001 | Internal spec | Attachment → Holding Folder path |
| TETER-CA-AI-AGT-DISPATCH-001 | Internal spec | Hands off parsed email to Dispatcher |
| TETER-CA-AI-AUDIT-001 | Internal spec | All poll events logged |
| Cloud Scheduler | GCP service | Triggers poll every 15 minutes |
| Firestore | GCP service | Deduplication store (processed message IDs) |

---

## 3. Architecture Overview

```
Cloud Scheduler (every 15 min)
        │
        ▼
Gmail Poller (Cloud Run service)
        │
        ├── 1. Fetch unread emails from inbox
        ├── 2. Check deduplication (Firestore: processed_emails/{message_id})
        ├── 3. Parse email (subject, sender, body, attachments)
        ├── 4. Download attachments → Drive Holding Folder
        ├── 5. Mark email as read + apply label "AI-Processed"
        └── 6. Create EmailIngest record in Firestore → triggers Dispatcher
```

---

## 4. Email Polling

### 4.1 Poll Trigger

- **Trigger:** Cloud Scheduler job `gmail-poll-15min`
- **Schedule:** `*/15 * * * *` (every 15 minutes)
- **Target:** Cloud Run service `gmail-poller` endpoint `POST /poll`
- **Auth:** Cloud Scheduler service account with `run.invoker` role

### 4.2 Gmail Query Filter

The poller fetches emails matching:

```
is:unread -label:AI-Processed
```

Only emails in the designated CA inbox are processed. The inbox is configured via environment variable `GMAIL_INBOX_ADDRESS`.

### 4.3 Rate Limiting

The Gmail API allows 250 quota units per second per user. Each `messages.list` costs 5 units; each `messages.get` costs 5 units. With a max expected volume of 50 emails per poll cycle, this is well within limits.

---

## 5. Email Parsing

### 5.1 Parsed Email Schema

```python
class ParsedEmail:
    message_id: str              # Gmail message ID (unique)
    thread_id: str               # Gmail thread ID
    received_at: datetime
    sender_email: str
    sender_name: str
    subject: str
    body_text: str               # Plain text body
    body_html: str | None        # HTML body (for attachment extraction fallback)
    attachments: list[EmailAttachment]
    labels: list[str]            # Existing Gmail labels
    in_reply_to: str | None      # Message ID this is a reply to
```

```python
class EmailAttachment:
    filename: str
    mime_type: str               # e.g., "application/pdf", "image/png"
    size_bytes: int
    content: bytes               # Raw attachment content
```

### 5.2 Subject Line Patterns (hints for Dispatcher)

The parser extracts structured hints from common subject line patterns:

| Pattern | Extracted Hint |
|---------|----------------|
| `RFI #045` or `RFI-045` | `doc_type_hint: RFI`, `doc_number_hint: 045` |
| `SUBMITTAL #12` | `doc_type_hint: SUBMITTAL` |
| `[Project 2024-001]` | `project_number_hint: 2024-001` |
| `RE:` prefix | `is_reply: true` |

These are hints only — the Dispatcher Agent makes the authoritative classification.

---

## 6. Deduplication

Every processed Gmail `message_id` is recorded in Firestore:

```
processed_emails/
  {message_id}/
    processed_at: Timestamp
    task_id: String              # Created task ID (for traceability)
```

Before processing any email, the poller checks this collection. If the `message_id` already exists, the email is skipped (with an `INFO` log entry).

---

## 7. Attachment Routing

Attachments are downloaded and placed in the Google Drive Holding Folder pending classification:

```
[Drive Root]/
└── 04 - Agent Workspace/
    └── Holding Folder/
        └── {YYYY-MM-DD}/
            └── {message_id}/
                └── {filename}
```

After classification by the Dispatcher, files are moved to the appropriate project folder by the relevant specialist agent.

---

## 8. Gmail Labeling

After successful processing, the poller applies the Gmail label `AI-Processed` to the message. This label is created if it does not exist.

If processing fails (parsing error, Drive upload failure), the message is left unread and an `ERROR` log entry is written. The next poll cycle will retry.

---

## 9. EmailIngest Firestore Record

After parsing and attachment upload, the poller writes an `EmailIngest` record that triggers the Dispatcher:

```
email_ingests/
  {ingest_id}/
    message_id: String
    ingest_id: String (uuid)
    received_at: Timestamp
    sender_email: String
    sender_name: String
    subject: String
    body_text: String
    body_text_truncated: Boolean   # true if > 10,000 chars
    attachment_drive_paths: [String]
    subject_hints: Map
    status: "PENDING_CLASSIFICATION"
    created_at: Timestamp
```

Firestore triggers or the Dispatcher's 20-minute queue review picks this up.

---

## 10. Configuration & Environment Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `GMAIL_INBOX_ADDRESS` | Env var | Email address to poll |
| `GMAIL_OAUTH_CLIENT_ID` | Secret Manager: `integrations/gmail/oauth-client-id` | OAuth client ID |
| `GMAIL_OAUTH_CLIENT_SECRET` | Secret Manager: `integrations/gmail/oauth-client-secret` | OAuth client secret |
| `GMAIL_OAUTH_REFRESH_TOKEN` | Secret Manager: `integrations/gmail/oauth-refresh-token` | Long-lived refresh token |
| `GMAIL_MAX_EMAILS_PER_POLL` | Env var (default: 50) | Safety cap per poll cycle |
| `GMAIL_ATTACHMENT_MAX_SIZE_MB` | Env var (default: 25) | Skip attachments larger than this |

---

## 11. Error Handling

| Error | Behavior |
|-------|----------|
| Gmail API 401/403 | Log CRITICAL, alert ops (token may be expired), skip cycle |
| Gmail API 429 | Log WARNING, skip cycle (next poll in 15 min) |
| Drive upload failure | Log ERROR, leave email unread, retry next cycle |
| Attachment > size limit | Log WARNING, skip attachment, process email without it, flag in ingest record |
| Empty inbox | Log INFO, no action |

---

## 12. Testing Requirements

- Unit: email parser correctly extracts subject hints from 10+ real subject patterns
- Unit: deduplication check correctly skips already-processed message IDs
- Unit: attachment filename sanitization (no path traversal)
- Integration: full poll cycle with a test Gmail account (3 test emails with attachments)
- Integration: verify Gmail label "AI-Processed" is applied
- Integration: verify attachment appears in correct Drive Holding Folder path
- Integration: verify `EmailIngest` Firestore record is created with `PENDING_CLASSIFICATION` status

---

## 13. Open Questions

| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | Which Gmail inbox should the system poll? A dedicated `ca-ai@teter.com` address or the existing CA inbox? | CA Director | Open |
| 2 | Should the system process emails received while it was offline (backfill), or only emails received after go-live? | Product | Open |
| 3 | What happens to emails that are not CA-related (spam, personal)? Apply a "Not CA Related" label and skip? | CA Director | Open |

---

## 14. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v0.1.0 | 2026-03-18 | TeterAI Team | Initial draft |

---

## 15. Implementation Status

- [x] Create Gmail models (`EmailAttachment`, `ParsedEmail`)
- [x] Implement polling logic & Gmail API auth (`is:unread -label:AI-Processed`)
- [x] Email parsing & Subject hinting logic
- [x] Deduplication logic using Firestore (`processed_emails` collection)
- [x] Emit `EmailIngest` records for Dispatcher agent
- [x] Apply `AI-Processed` label
- [x] Expose Cloud Run HTTP endpoint (`POST /poll`) using FastAPI
- [x] Base mock tests coverage
- [ ] Implement real Google Drive attachment upload (stubbed currently)
