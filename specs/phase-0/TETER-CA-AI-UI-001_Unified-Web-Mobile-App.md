# TETER-CA-AI-UI-001 — Unified Web & Mobile Application

| Field | Value |
|-------|-------|
| Document ID | TETER-CA-AI-UI-001 |
| Version | v0.1.0 |
| Status | Draft |
| Phase | Phase 0 — Foundation |
| Last Updated | 2026-03-18 |

---

## 1. Purpose & Scope

This specification defines the Unified Web & Mobile Application — the primary human interface for TeterAI_CA. CA staff interact with the system exclusively through this application: reviewing agent drafts, approving or rejecting outputs, configuring the system, and monitoring activity.

The application is the enforcement point for the **human-in-the-loop** principle. No agent output reaches an external party without a human approval action within this app.

**Three core views (Phase 0 MVP):**
1. **Action Dashboard** — inbox-style queue of documents staged for human review
2. **Split-Screen Viewer** — side-by-side comparison of agent draft (left) and source document (right)
3. **Admin/Config Panel** — system configuration, project management, user management

**Technology stack:**
- Web: React (TypeScript) — primary, full-featured interface
- Mobile: Flutter — secondary, review-and-approve only (Phase 0 scope: read/approve/reject)
- Backend: Firestore real-time listeners for live queue updates
- Auth: Google OAuth 2.0

**Out of scope (Phase 0):** Outbound email delivery UI (Phase 1), Teams bot interface, advanced search/filtering, document creation from scratch.

---

## 2. Dependencies

| Dependency | Type | Notes |
|-----------|------|-------|
| TETER-CA-AI-WF-001 | Internal spec | Task queue is the data source |
| TETER-CA-AI-SEC-001 | Internal spec | Google OAuth, role-based access |
| TETER-CA-AI-AUDIT-001 | Internal spec | Human review actions logged |
| TETER-CA-AI-KG-001 | Internal spec | Correction events routed to KG |
| TETER-CA-AI-INT-DRIVE-001 | Internal spec | Source docs and drafts served from Drive |
| Firestore | GCP service | Real-time data via Firestore SDK |
| Google Drive API | Google API | File access for Split-Screen Viewer |
| Cloud Run | GCP service | Hosts the web app backend API |

---

## 3. Architecture Overview

```
Browser / Mobile App
        │
        ├── Google OAuth 2.0 (authentication)
        │
        ├── Firestore SDK (real-time task queue)
        │
        └── App Backend API (Cloud Run)
              ├── GET  /tasks            → task queue (filtered by role)
              ├── GET  /tasks/{id}       → task detail + draft content
              ├── POST /tasks/{id}/approve
              ├── POST /tasks/{id}/reject
              ├── POST /tasks/{id}/escalate
              ├── GET  /tasks/{id}/draft → agent draft text
              ├── GET  /tasks/{id}/source → source document (Drive proxy)
              ├── GET  /projects         → project list
              ├── POST /projects         → create project (ADMIN only)
              └── GET  /audit/{task_id}  → task audit trail (ADMIN only)
```

---

## 4. View 1 — Action Dashboard

The Action Dashboard is the default landing view for CA_STAFF. It displays all tasks in `STAGED_FOR_REVIEW` and `ESCALATED_TO_HUMAN` states.

### 4.1 Layout

```
┌──────────────────────────────────────────────────────────┐
│  TeterAI  |  Action Dashboard  |  [Jane Smith]  [Logout] │
├──────────────────────────────────────────────────────────┤
│  Filter: [All Projects ▾] [All Types ▾] [Urgency ▾]      │
├──────────────────────────────────────────────────────────┤
│  [!] HIGH    RFI-045  |  ABC Contractors  |  2026-003    │
│              Concrete PSI conflict — Structural          │
│              Received 2h ago  |  Response due 2026-03-28 │
├──────────────────────────────────────────────────────────┤
│  [ ] MEDIUM  RFI-046  |  DEF Mechanical   |  2026-003    │
│              HVAC duct clearance question                │
│              Received 4h ago  |  Response due 2026-03-28 │
├──────────────────────────────────────────────────────────┤
│  [ ] LOW     ESCALATED  |  Unknown Type   |  UNKNOWN     │
│              "RE: RE: FW: meeting notes" — needs routing │
│              Received 1h ago                             │
└──────────────────────────────────────────────────────────┘
```

### 4.2 Task Card Fields

| Field | Source |
|-------|--------|
| Urgency badge (HIGH/MEDIUM/LOW) | `tasks.urgency` |
| Document type + number | `tasks.document_type`, `tasks.document_number` |
| Contractor/sender | EmailIngest `sender_name` |
| Project number | `tasks.project_number` |
| Subject summary | EmailIngest `subject` |
| Age | `tasks.created_at` delta |
| Response due | Derived from document type deadline rules |
| Confidence score | `tasks.classification_confidence` (shown as indicator) |

### 4.3 Sort Order

Default: Urgency DESC, then age ASC (oldest HIGH urgency first).

### 4.4 Real-Time Updates

Firestore real-time listeners update the dashboard without page refresh. New tasks arriving in `STAGED_FOR_REVIEW` appear immediately with a visual notification.

---

## 5. View 2 — Split-Screen Viewer

Opened when a reviewer clicks a task card. This is the core review experience.

### 5.1 Layout

```
┌─────────────────────────────┬──────────────────────────────┐
│  AGENT DRAFT                │  SOURCE DOCUMENT             │
│  RFI-045 — Draft Response   │  [Tab: Original Email]       │
│  Confidence: 87%            │  [Tab: RFI-045.pdf]          │
│  Agent: RFI Agent v0.1      │  [Tab: Spec 03 30 00]        │
│                             │  [Tab: Sheet S-101]          │
│  ┌───────────────────────┐  │                              │
│  │ PROJECT: 2026-003...  │  │  [PDF/email viewer]          │
│  │ RFI #: RFI-045        │  │                              │
│  │ DATE: 2026-03-18      │  │                              │
│  │ FROM: Teter Arch.     │  │                              │
│  │                       │  │                              │
│  │ RESPONSE:             │  │                              │
│  │ Per Specification     │  │                              │
│  │ Section 03 30 00...   │  │                              │
│  │                       │  │                              │
│  └───────────────────────┘  │                              │
│  [Edit Draft]               │                              │
├─────────────────────────────┴──────────────────────────────┤
│  [Thought Chain]  [REJECT]  [ESCALATE]  [APPROVE]         │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 Left Panel (Agent Draft)

- Editable text area showing the agent's draft response
- Confidence score indicator (color-coded: green ≥0.80, yellow 0.50–0.79, red <0.50)
- Agent ID and version
- Citations list (clickable — opens cited spec section in right panel)

### 5.3 Right Panel (Source Documents)

Tabbed viewer showing:
- **Original Email** — the raw email from the contractor
- **Attached PDFs** — each attachment as a separate tab with inline PDF viewer
- **Referenced Spec Sections** — spec section pages from Drive, auto-loaded based on citations
- **Referenced Drawings** — drawing sheets from Drive (if applicable)

Documents are served via the app backend as a Drive proxy (no direct Drive link sharing required).

### 5.4 Action Buttons

| Button | Action | Behavior |
|--------|--------|---------|
| `APPROVE` | Approve draft as-is | Transitions task to `APPROVED`; triggers delivery prep |
| `Edit Draft` + `APPROVE` | Edit then approve | Opens inline editor; on save+approve, captures correction diff, transitions to `APPROVED` |
| `REJECT` | Send back for rework | Opens rejection notes dialog; transitions to `REJECTED`; agent re-queued with notes |
| `ESCALATE` | Escalate to senior review | Transitions to `ESCALATED_TO_HUMAN`; reassigns to a different reviewer |
| `Thought Chain` | View agent reasoning | Opens modal showing full thought chain JSON from Drive |

### 5.5 Rejection Notes Dialog

When rejecting, reviewer selects a reason (required) and optionally adds free-text notes:

```
Rejection Reason: [Citation Error ▾]
                  Content Error
                  Tone/Style
                  Citation Error
                  Missing Information
                  Scope Issue
                  Other

Notes (optional): [____________]

[Cancel]  [REJECT AND SEND BACK]
```

Rejection reason is passed to the agent on re-queue to improve the next attempt.

---

## 6. View 3 — Admin/Config Panel

Accessible to `ADMIN` role only.

### 6.1 Sections

**Project Management**
- List all active/inactive projects
- Create new project (triggers Drive folder creation via INT-DRIVE-001)
- Edit project: name, known senders, current phase, active/inactive

**User Management**
- List all users (from Firestore `users` collection)
- Assign/change roles: CA_STAFF | ADMIN | REVIEWER
- Deactivate users

**Model Registry**
- View current AI model assignments per capability class
- Update model for any tier (writes to Firestore `ai_engine/model_registry`)
- View fallback history (recent AI tier usage from audit logs)

**Agent Configuration**
- View agent status (last run, last task, queue depth)
- Adjust confidence thresholds per agent (writes to Firestore agent config)
- View/edit playbook rules (read-only in Phase 0; full edit in Phase 1)

**Audit Trail**
- Search audit logs by task ID, date range, agent, reviewer
- Export audit logs as CSV

---

## 7. Authentication & Authorization

### 7.1 Authentication Flow

1. User lands on app → redirect to Google OAuth consent screen
2. Google returns OAuth token for `@teter.com` (or allowed domain)
3. App backend validates token → looks up user role in Firestore `users/{uid}`
4. JWT session cookie issued (signed with `session-secret` from Secret Manager)
5. All subsequent requests validate JWT

### 7.2 Role Enforcement

| Route / Feature | CA_STAFF | ADMIN | REVIEWER |
|----------------|----------|-------|---------|
| Action Dashboard | Read + Act | Read + Act | — |
| Split-Screen Viewer | Read + Act | Read + Act | Read only |
| Approve/Reject/Escalate | Yes | Yes | No |
| Admin/Config Panel | No | Yes | No |
| Audit Trail | Own tasks only | All tasks | No |
| Project Management | No | Yes | No |
| User Management | No | Yes | No |

---

## 8. Mobile App Scope (Phase 0)

The Flutter mobile app is a **review-only** companion app for Phase 0. Features:

- Authenticate via Google OAuth
- View Action Dashboard (same task list, mobile-optimized)
- Open Split-Screen Viewer (vertical split on tablet; tabbed on phone)
- Approve or Reject tasks
- View thought chain (JSON viewer)

**Not in mobile Phase 0:** Admin panel, editing drafts, escalation.

---

## 9. Real-Time Notifications

When a new task enters `STAGED_FOR_REVIEW`:
- Action Dashboard updates instantly (Firestore listener)
- Browser tab title shows unread count: `(3) TeterAI`
- Web push notification (if user granted permission): `New RFI ready for review — 2026-003`

---

## 10. Configuration & Environment Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `GOOGLE_OAUTH_CLIENT_ID` | Secret Manager: `webapp/google-oauth-client-id` | Web app OAuth client ID |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Secret Manager: `webapp/google-oauth-client-secret` | Web app OAuth client secret |
| `SESSION_SECRET` | Secret Manager: `webapp/session-secret` | JWT signing secret |
| `ALLOWED_EMAIL_DOMAIN` | Env var (default: `teter.com`) | Restrict login to this domain |
| `FIRESTORE_PROJECT_ID` | Env var | GCP project ID for Firestore |
| `DRIVE_PROXY_MAX_FILE_SIZE_MB` | Env var (default: 50) | Max file size served via Drive proxy |

---

## 11. Testing Requirements

- Unit: role-based route guards block unauthorized access (all 3 roles × all routes)
- Unit: JWT validation rejects expired and tampered tokens
- Unit: correction diff is correctly captured when reviewer edits draft
- Integration: full approval flow (login → Action Dashboard → Split-Screen → Approve)
- Integration: full rejection flow (login → view task → Reject with reason → agent re-queued)
- Integration: Admin creates project → Drive folders created → project appears in Dispatcher registry
- E2E: Firestore listener updates Action Dashboard in < 2 seconds when new task staged
- Mobile: approve and reject actions function correctly on iOS and Android

---

## 12. Open Questions

| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | Should the Split-Screen Viewer allow inline annotation of source PDFs (e.g., highlight a spec section)? | CA Director | Open |
| 2 | Should the mobile app support push notifications via FCM, or is in-app only sufficient for Phase 0? | Product | Open |
| 3 | Does the app need dark mode? | CA Director | Open |
| 4 | Should reviewers be able to assign tasks to other reviewers, or is the queue shared and first-come? | CA Director | Open |

---

## 13. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v0.1.0 | 2026-03-18 | TeterAI Team | Initial draft |
