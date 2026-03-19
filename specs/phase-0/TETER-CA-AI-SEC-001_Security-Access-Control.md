# TETER-CA-AI-SEC-001 — Security & Access Control

| Field | Value |
|-------|-------|
| Document ID | TETER-CA-AI-SEC-001 |
| Version | v0.1.0 |
| Status | Draft |
| Phase | Phase 0 — Foundation |
| Last Updated | 2026-03-18 |

---

## 1. Purpose & Scope

This specification defines the security architecture, access control model, and credential management for TeterAI_CA. It governs how all system components authenticate, what permissions they hold, and how sensitive data is protected.

**Core principles:**
- **Least privilege** — every service account holds only the permissions it requires
- **Secrets never in code** — all credentials stored in GCP Secret Manager
- **Immutable audit** — all access events logged (see AUDIT-001)
- **Human approval required** — no agent can send externally without human sign-off

**In scope:** GCP service accounts, Secret Manager structure, OAuth scopes, user role definitions, inter-service auth.

**Out of scope:** End-user authentication implementation details (covered in UI-001), network firewall rules (infrastructure layer).

---

## 2. Dependencies

| Dependency | Type | Notes |
|-----------|------|-------|
| GCP Secret Manager | GCP service | Credential storage |
| GCP IAM | GCP service | Service account management |
| Google Workspace Admin | External | Gmail/Drive OAuth consent |
| TETER-CA-AI-AUDIT-001 | Internal spec | All access events must be logged |

---

## 3. Architecture Overview

```
┌──────────────────────────────────────────────────────┐
│                  Security Boundary                    │
│                                                       │
│  ┌──────────────┐    ┌──────────────────────────┐    │
│  │  GCP IAM     │    │  GCP Secret Manager      │    │
│  │              │    │                          │    │
│  │  Service     │    │  AI Engine keys          │    │
│  │  Accounts:   │    │  Gmail OAuth tokens      │    │
│  │  - AI Engine │    │  Drive service account   │    │
│  │  - Dispatcher│    │  Neo4j credentials       │    │
│  │  - RFI Agent │    │  Firestore config        │    │
│  │  - Web App   │    └──────────────────────────┘    │
│  └──────────────┘                                     │
│                                                       │
│  ┌──────────────────────────────────────────────┐    │
│  │  User Auth (Google OAuth via Web App)        │    │
│  │  Roles: CA_STAFF | ADMIN | REVIEWER          │    │
│  └──────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

---

## 4. GCP Service Accounts

One service account per major system component. Each account is granted only the IAM roles and Secret Manager secrets it requires.

| Service Account | Component | IAM Roles | Secret Access |
|----------------|-----------|-----------|---------------|
| `sa-ai-engine@[project].iam.gserviceaccount.com` | AI Engine | `secretmanager.secretAccessor` | `ai-engine/*` |
| `sa-dispatcher@[project].iam.gserviceaccount.com` | Dispatcher Agent | `secretmanager.secretAccessor`, `datastore.user`, `cloudscheduler.admin` | `integrations/gmail/*`, `ai-engine/*` |
| `sa-rfi-agent@[project].iam.gserviceaccount.com` | RFI Agent | `secretmanager.secretAccessor`, `datastore.user` | `integrations/drive/*`, `ai-engine/*`, `kg/*` |
| `sa-workflow@[project].iam.gserviceaccount.com` | Workflow Engine | `datastore.user`, `secretmanager.secretAccessor` | `workflow/*` |
| `sa-web-app@[project].iam.gserviceaccount.com` | Web Application | `datastore.viewer`, `secretmanager.secretAccessor` | `webapp/*` |
| `sa-cloud-scheduler@[project].iam.gserviceaccount.com` | Cloud Scheduler | `run.invoker` | None |

---

## 5. GCP Secret Manager Structure

All secrets follow a hierarchical naming convention: `{component}/{secret-name}`

```
ai-engine/
  anthropic-key          # Claude API key
  google-ai-key          # Google AI Studio key
  xai-key                # xAI/Grok API key

integrations/
  gmail/
    oauth-client-id      # Gmail OAuth 2.0 client ID
    oauth-client-secret  # Gmail OAuth 2.0 client secret
    oauth-refresh-token  # Long-lived refresh token (rotated annually)
  drive/
    service-account-json # Drive API service account key (JSON)

kg/
  neo4j-uri              # Neo4j Aura connection URI
  neo4j-username         # Neo4j username
  neo4j-password         # Neo4j password

workflow/
  firestore-project-id   # Firestore project ID

webapp/
  google-oauth-client-id     # Web app Google OAuth client ID
  google-oauth-client-secret # Web app Google OAuth client secret
  session-secret             # JWT session signing secret
```

### 5.1 Secret Rotation Policy

| Secret Category | Rotation Frequency | Rotation Method |
|----------------|-------------------|-----------------|
| AI provider API keys | Quarterly | Manual (provider portal) |
| Gmail OAuth refresh token | Annually | Manual re-auth flow |
| Neo4j password | Quarterly | Automated via Secret Manager rotation |
| Session secret | Monthly | Automated |

---

## 6. Gmail OAuth Scopes

The system requests only the minimum Gmail scopes required:

| Scope | Purpose |
|-------|---------|
| `https://www.googleapis.com/auth/gmail.readonly` | Read emails for classification |
| `https://www.googleapis.com/auth/gmail.modify` | Mark emails as read, apply labels |

The system does **not** request `gmail.send` — outbound email is handled separately (future phase) and requires explicit human initiation.

---

## 7. Google Drive OAuth Scopes

| Scope | Purpose |
|-------|---------|
| `https://www.googleapis.com/auth/drive.file` | Read/write files created by the app |
| `https://www.googleapis.com/auth/drive.readonly` | Read source documents for cross-reference |

The system uses a **service account** (not user OAuth) for Drive, with the service account granted Editor access to the project folder hierarchy only.

---

## 8. User Role Definitions

Three roles govern human user access to the Web Application:

| Role | Description | Permissions |
|------|-------------|------------|
| `CA_STAFF` | CA department staff — primary users | View action queue, review staged docs, approve/reject/edit, view audit trail for own tasks |
| `ADMIN` | System administrator | All CA_STAFF permissions + manage user roles, configure agent settings, view full audit trail, manage model registry |
| `REVIEWER` | Read-only stakeholder | View approved/delivered documents only; no queue access |

Role assignment is stored in Firestore collection `users/{uid}/role`. Role changes require `ADMIN` authorization and are logged.

---

## 9. Inter-Service Authentication

All internal Cloud Run services authenticate via **GCP Identity Tokens** (OIDC). Cloud Scheduler invocations are authenticated via the `sa-cloud-scheduler` service account with `run.invoker` role.

No internal service exposes unauthenticated endpoints. All Cloud Run services are deployed with `--no-allow-unauthenticated`.

---

## 10. Sensitive Data Handling

| Data Type | Storage | Encryption |
|----------|---------|-----------|
| AI provider API keys | Secret Manager | Google-managed encryption at rest |
| Email content (raw) | Firestore (tasks collection) | Google-managed encryption at rest |
| Document content | Google Drive | Google-managed encryption at rest |
| Agent thought chains | Google Drive (04 - Agent Workspace/Thought Chains) | Google-managed encryption at rest |
| User sessions | HttpOnly, Secure, SameSite=Strict cookie (server-set) | JWT signed with `session-secret` from Secret Manager; **never stored in `localStorage`** — see UI-001 §7.3 |

No PII or confidential document content is stored in logs. Log entries reference task IDs only; content is retrieved from Firestore/Drive on demand.

---

## 11. Testing Requirements

- Verify each service account cannot access secrets outside its designated path
- Verify Cloud Run services reject unauthenticated requests (return 401)
- Verify Gmail scope is `readonly` + `modify` only (not `send`)
- Verify role-based access in web app (CA_STAFF cannot access admin panel)
- Verify secret rotation does not cause service downtime

---

## 12. Open Questions

| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | Should outbound email (Phase 1+) use a dedicated Teter domain email address or the CA staff member's personal Gmail? | CA Director | Open |
| 2 | Is Google Workspace Enterprise required for the service account approach to Drive, or does the current plan work with standard Workspace? | Tech Lead | Open |
| 3 | What is the data retention policy for email content in Firestore? | Legal/Admin | Open |

---

## 13. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v0.1.0 | 2026-03-18 | TeterAI Team | Initial draft |
| v0.1.1 | 2026-03-19 | AI Agent | Added auth models and Firestore role management implementation |
