# TETER-CA-AI-INT-DRIVE-001 — Google Drive Structure & Folder Management

| Field | Value |
|-------|-------|
| Document ID | TETER-CA-AI-INT-DRIVE-001 |
| Version | v0.1.0 |
| Status | Draft |
| Phase | Phase 0 — Foundation |
| Last Updated | 2026-03-18 |

---

## 1. Purpose & Scope

This specification defines the Google Drive integration — the backend file system for all project documents. The system enforces a rigid, standardized folder hierarchy per project, automates folder creation for new projects, and manages file routing from the Holding Folder to classified destinations.

**Key principle:** The folder structure is enforced by the system, not by humans. CA staff should never need to manually create project folders or organize files.

**In scope:** Folder hierarchy definition, automated folder creation, file routing rules, Drive API interaction patterns, folder ID registry.

**Out of scope:** Document content processing (handled by agents), file sharing/permissions management for external parties (future phase), Drive file versioning strategy.

---

## 2. Dependencies

| Dependency | Type | Notes |
|-----------|------|-------|
| Google Drive API v3 | Google API | File and folder operations |
| TETER-CA-AI-SEC-001 | Internal spec | Service account and OAuth scopes |
| TETER-CA-AI-INT-GMAIL-001 | Internal spec | Attachments land in Holding Folder |
| TETER-CA-AI-WF-001 | Internal spec | Task workflow drives file routing |
| TETER-CA-AI-AUDIT-001 | Internal spec | All file operations logged |
| Firestore | GCP service | Folder ID registry (project folder map) |

---

## 3. Canonical Folder Hierarchy

Every project follows this exact structure. Folder names are standardized and must not deviate.

```
[YYYY-NNN] - [Project Name]/
├── 01 - Bid Phase/
│   ├── PB-RFIs/
│   ├── Addenda/
│   ├── Bid Documents/
│   └── Pre-Bid Site Visits/
├── 02 - Construction/
│   ├── RFIs/
│   ├── Submittals/
│   ├── Substitution Requests/
│   ├── PCO-COR/
│   ├── Bulletins/
│   ├── Change Orders/
│   ├── Pay Applications/
│   ├── Meeting Minutes/
│   └── Punchlist/
├── 03 - Closeout/
│   ├── Warranties/
│   ├── O&M Manuals/
│   └── Gov Paperwork/
└── 04 - Agent Workspace/
    ├── Holding Folder/
    ├── Thought Chains/
    ├── Source Docs/
    └── Agent Logs/
```

### 3.1 Project Naming Convention

```
[YYYY-NNN] - [Project Name]
```

- `YYYY`: 4-digit year (project initiation year)
- `NNN`: 3-digit sequential project number (e.g., 001, 042)
- `Project Name`: Official project name from contract documents

Example: `2026-003 - Riverside Elementary Renovation`

---

## 4. Document Numbering Convention

Each document type within a project uses a standardized numbering sequence:

| Document Type | Prefix | Example | Sequence Scope |
|--------------|--------|---------|---------------|
| RFI (Construction) | `RFI-` | `RFI-001` | Per project |
| Pre-Bid RFI | `PB-RFI-` | `PB-RFI-001` | Per project |
| Submittal | `SUB-` | `SUB-001` | Per project |
| Substitution Request | `SUB-REQ-` | `SUB-REQ-001` | Per project |
| PCO/COR | `PCO-` | `PCO-001` | Per project |
| Bulletin | `BUL-` | `BUL-001` | Per project |
| Change Order | `CO-` | `CO-001` | Per project |
| Pay Application | `PAY-` | `PAY-001` | Per project |
| Meeting Minutes | `MM-` | `MM-001` | Per project |
| Addendum | `ADD-` | `ADD-001` | Per project |

Document sequence counters are stored in Firestore:
```
projects/{project_id}/doc_counters/{doc_type}: Integer
```

The Drive Integration service atomically increments the counter and assigns the number when a document is filed.

---

## 5. Folder ID Registry

Folder IDs (Google Drive's internal identifiers) are stored in Firestore for fast lookup. This avoids repeated Drive API traversal.

```
drive_folders/
  {project_id}/
    root_folder_id: String              # e.g., "1aBcDeFgHiJkLmNo"
    folders:
      "01 - Bid Phase": String
      "01 - Bid Phase/PB-RFIs": String
      "01 - Bid Phase/Addenda": String
      ...
      "04 - Agent Workspace/Holding Folder": String
      "04 - Agent Workspace/Thought Chains": String
      ...
    created_at: Timestamp
    last_verified_at: Timestamp
```

Folder IDs are registered when the project folder is created and verified on a weekly basis (Cloud Scheduler job).

---

## 6. Automated Folder Creation

When a new project is onboarded (triggered by Admin via Web App):

1. Admin creates project in Web App (project number, name)
2. Drive service creates root folder: `[YYYY-NNN] - [Project Name]` in the configured Drive root
3. Drive service recursively creates all subfolder levels from the canonical hierarchy
4. All folder IDs are stored in Firestore registry
5. Document counters initialized to `0` for all document types
6. System event logged (`PROJECT_FOLDER_CREATED`)

```python
class DriveService:
    def create_project_folders(self, project: Project) -> ProjectFolderRegistry: ...
    def get_folder_id(self, project_id: str, folder_path: str) -> str: ...
    def upload_file(self, folder_id: str, filename: str, content: bytes, mime_type: str) -> str: ...
    def move_file(self, file_id: str, destination_folder_id: str) -> None: ...
    def next_doc_number(self, project_id: str, doc_type: str) -> str: ...
```

---

## 7. File Routing Rules

After the Dispatcher Agent classifies an email, files move from the Holding Folder to the classified destination.

### 7.1 Routing Table

| Classified Document Type | Phase | Destination Folder |
|-------------------------|-------|-------------------|
| `RFI` | Construction | `02 - Construction/RFIs/` |
| `SUBMITTAL` | Construction | `02 - Construction/Submittals/` |
| `SUBSTITUTION_REQUEST` | Construction | `02 - Construction/Substitution Requests/` |
| `PCO_COR` | Construction | `02 - Construction/PCO-COR/` |
| `BULLETIN` | Construction | `02 - Construction/Bulletins/` |
| `CHANGE_ORDER` | Construction | `02 - Construction/Change Orders/` |
| `PAY_APPLICATION` | Construction | `02 - Construction/Pay Applications/` |
| `MEETING_MINUTES` | Construction | `02 - Construction/Meeting Minutes/` |
| `PB_RFI` | Bid | `01 - Bid Phase/PB-RFIs/` |
| `ADDENDUM` | Bid | `01 - Bid Phase/Addenda/` |
| `UNKNOWN` | Any | Stays in `04 - Agent Workspace/Holding Folder/` (escalated to human) |

### 7.2 File Naming on Filing

When a file is moved from the Holding Folder to its classified destination, it is renamed:

```
{doc_number}_{original_filename}
```

Example: `RFI-045_Structural_Query_ABC_Contractors.pdf`

---

## 8. Agent Workspace Folder

The `04 - Agent Workspace/` folder is managed exclusively by the system. CA staff have read access for audit purposes but should not manually add or move files there.

| Subfolder | Contents | Written By |
|-----------|---------|-----------|
| `Holding Folder/` | Unclassified email attachments | Gmail Integration |
| `Thought Chains/` | Agent reasoning traces (JSON) | All agents |
| `Source Docs/` | Copies of source docs used for cross-reference | RFI Agent, Submittal Agent |
| `Agent Logs/` | Structured agent activity logs | All agents (legacy; primary logs in Firestore) |

---

## 9. Configuration & Environment Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `DRIVE_SERVICE_ACCOUNT_JSON` | Secret Manager: `integrations/drive/service-account-json` | Drive API service account credentials |
| `DRIVE_ROOT_FOLDER_ID` | Env var | Folder ID of the top-level "Projects" folder in Drive |
| `DRIVE_MAX_UPLOAD_SIZE_MB` | Env var (default: 100) | Max file size for upload |

---

## 10. Error Handling

| Error | Behavior |
|-------|----------|
| Drive API 403 (permission) | Log CRITICAL, alert ops, file stays in Holding Folder |
| Drive API 429 (quota) | Log WARNING, retry with exponential backoff (3 attempts) |
| Folder not found in registry | Re-query Drive API, update registry, retry |
| Duplicate filename | Append `_{timestamp}` suffix before filing |
| File > size limit | Log WARNING, flag in task record, file in Holding Folder with note |

---

## 11. Testing Requirements

- Unit: canonical folder hierarchy is created with correct names and nesting
- Unit: document numbering increments correctly and is collision-free (concurrent writes)
- Unit: file routing table routes each document type to correct folder path
- Unit: file rename on filing uses correct `{doc_number}_{filename}` format
- Integration: full project onboarding (folder creation + registry population)
- Integration: attachment upload from Gmail ingest → Holding Folder → classified folder
- Integration: Folder ID registry correctly populated in Firestore

---

## 12. Open Questions

| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | Should each project subfolder be created at project onboarding (all at once), or lazily as each phase begins? | CA Director | Open |
| 2 | What is the Drive root folder where all project folders live? Should it be a Shared Drive or a personal Drive? | CA Director | Open |
| 3 | For Punchlist items — should each punchlist item be a separate file, or a single running log? | CA Director | Open |

---

## 13. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v0.1.0 | 2026-03-18 | TeterAI Team | Initial draft |
