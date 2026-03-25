# TETER-CA-AI-DESK-001 — Desktop App & Local Storage

| Field | Value |
|-------|-------|
| Document ID | TETER-CA-AI-DESK-001 |
| Version | v0.1.0 |
| Status | Built |
| Phase | Phase 1 — Desktop Distribution |
| Last Updated | 2026-03-25 |

---

## 1. Purpose & Scope

This specification defines the **Desktop App & Local Storage** layer — a self-contained, single-user mode that replaces all GCP cloud dependencies (Firestore, Google Drive, GCP Secret Manager, Firebase Auth, Gmail OAuth) with local equivalents on the user's machine.

The desktop mode targets non-technical executives who need to run TeterAI CA without GCP credentials, a terminal, or a server. The entire system installs as a standard Windows `.exe` double-click installer.

**What DESKTOP_MODE provides:**
- SQLite database in place of Firestore
- Local filesystem (`~/TeterAI/`) in place of Google Drive
- `~/.teterai/config.env` in place of GCP Secret Manager
- Hardcoded ADMIN auth bypass in place of Firebase Auth
- Folder-based inbox watcher in place of Gmail OAuth

**In scope:** SQLite schema, `LocalConfig`, `LocalIntegration`, `LocalStorageService`, `LocalInboxWatcher`, Electron shell, PyInstaller packaging, NSIS installer, splash screen UX, API changes for settings and upload endpoints, React frontend changes.

**Out of scope:** Multi-user/team support (single-user only), Gmail OAuth inbox (replaced by folder watcher), real-time push (replaced by polling), mobile app (DESK-001 is desktop-only), knowledge graph (Neo4j optional in this mode).

---

## 2. Dependencies

| Dependency | Type | Notes |
|-----------|------|-------|
| TETER-CA-AI-WF-001 | Internal spec | Task queue engine — unchanged; SQLiteClient is a drop-in |
| TETER-CA-AI-AEC-001 | Internal spec | AI engine — unchanged; model registry falls back to `default_registry.json` |
| TETER-CA-AI-AUDIT-001 | Internal spec | Audit trail — unchanged; writes to SQLite `audit_logs` table |
| TETER-CA-AI-INT-DRIVE-001 | Internal spec | Drive structure — mirrored to local filesystem tree |
| TETER-CA-AI-INT-GMAIL-001 | Internal spec | Gmail integration — replaced by `LocalInboxWatcher` in desktop mode |
| Electron | External | v33+ — desktop shell, BrowserWindow, IPC |
| electron-builder | External | v25+ — cross-platform packaging, NSIS installer |
| PyInstaller | External | v6+ — bundles Python backend + dependencies into a self-contained binary |
| SQLite | External | stdlib `sqlite3` + `aiosqlite` — local database |
| Python `email` stdlib | External | Parses `.eml` files in inbox watcher |

---

## 3. Architecture Overview

```
User double-clicks installer
        │
        ▼
  TeterAI CA.exe (Electron shell)
        │
        ├── Shows loading.html (branded splash)
        │
        ├── Spawns teterai-backend[.exe]  (PyInstaller bundle)
        │        │
        │        ├── uvicorn starts FastAPI on 127.0.0.1:8000
        │        │
        │        ├── SQLite DB  ~/TeterAI/teterai.db
        │        │
        │        ├── Local filesystem  ~/TeterAI/Projects/
        │        │
        │        └── LocalInboxWatcher thread
        │                └── polls ~/TeterAI/Inbox every 30s
        │                    ├── .eml  → email_ingests table
        │                    ├── .pdf  → ingest + task created
        │                    └── .docx → ingest + task created
        │
        └── waitForAPI() polls /api/docs every 500ms
                │
                ▼  (API ready, ~2-4s)
          BrowserWindow loads http://127.0.0.1:8000
          (React SPA built with VITE_DESKTOP_MODE=true)
```

---

## 4. Storage Layer

### 4.1 SQLite Schema

Database location: `~/TeterAI/teterai.db`
Encoding: WAL mode (`PRAGMA journal_mode=WAL`), `PRAGMA foreign_keys=ON`

| Table | Key Columns | Notes |
|-------|-------------|-------|
| `tasks` | `id TEXT PK`, `project_id`, `type`, `status`, `title`, `description`, `created_at`, `updated_at`, `agent_output JSON`, `metadata JSON` | Central task queue |
| `email_ingests` | `id TEXT PK`, `subject`, `sender`, `received_at`, `raw_path`, `processed`, `task_id`, `source` | Source: `gmail` or `folder_watch` |
| `audit_logs` | `id TEXT PK`, `timestamp`, `user_id`, `action`, `resource_type`, `resource_id`, `details JSON` | Append-only audit trail |
| `audit_logs_by_task` | `task_id`, `audit_id` FK | Junction table for task audit lookup |
| `thought_chains` | `id TEXT PK`, `task_id FK`, `agent`, `step`, `content`, `timestamp` | Agent reasoning trace |
| `submittal_reviews` | `id TEXT PK`, `task_id FK`, `spec_section`, `status`, `notes`, `reviewed_by`, `reviewed_at` | Submittal review records |
| `rfi_log` | `id TEXT PK`, `task_id FK`, `rfi_number`, `question`, `answer`, `status`, `created_at`, `closed_at` | RFI tracking |
| `doc_counters` | `project_id TEXT`, `doc_type TEXT`, `counter INTEGER` | Atomic document numbering (PK composite) |
| `projects` | `id TEXT PK`, `name`, `number`, `client`, `address`, `status`, `created_at`, `metadata JSON` | Project registry |
| `folder_registry` | `project_id TEXT PK`, `paths JSON` | Local folder path map per project |
| `users` | `id TEXT PK`, `email`, `display_name`, `role`, `created_at` | Local user store (single user in desktop mode) |
| `processed_emails` | `message_id TEXT PK`, `processed_at` | Dedup guard for inbox watcher |
| `model_registry` | `id TEXT PK`, `provider`, `model_id`, `tier`, `capabilities JSON`, `active INTEGER` | AI model config (mirrors Firestore in cloud mode) |

### 4.2 Local Filesystem Tree

```
~/TeterAI/
├── teterai.db               # SQLite database
├── Inbox/                   # Drop-in folder for .eml / .pdf / .docx
└── Projects/
    └── {project_id}/
        ├── Submittals/
        ├── RFIs/
        ├── Meeting Notes/
        ├── Correspondence/
        ├── Deliverables/
        └── Archive/
```

### 4.3 Config File

Location: `~/.teterai/config.env`
Format: `KEY=value` (one per line, `#` comments ignored)
Created on first launch with empty values.

| Key | Default | Notes |
|-----|---------|-------|
| `ANTHROPIC_API_KEY` | _(empty)_ | Required for AI processing |
| `GEMINI_API_KEY` | _(empty)_ | Optional tier-2 model |
| `OPENAI_API_KEY` | _(empty)_ | Optional tier-2/3 model |
| `XAI_API_KEY` | _(empty)_ | Optional Grok model |
| `NEO4J_URI` | _(empty)_ | Optional knowledge graph |
| `NEO4J_USER` | _(empty)_ | Optional |
| `NEO4J_PASSWORD` | _(empty)_ | Optional |
| `TETERAI_DATA_DIR` | `~/TeterAI` | Override default data root |
| `TETERAI_INBOX_DIR` | `~/TeterAI/Inbox` | Override inbox folder |
| `TETERAI_INBOX_POLL_INTERVAL` | `30` | Seconds between inbox scans |

---

## 5. Component Specifications

### 5.1 LocalConfig (`src/config/local_config.py`)

Dataclass holding all runtime config for desktop mode.

**Key methods:**
- `LocalConfig.ensure_exists()` — loads `~/.teterai/config.env` if it exists; creates it empty if not. Returns a `LocalConfig` instance.
- `push_to_env()` — writes all non-empty fields to `os.environ` so downstream code (LiteLLM, etc.) can read them as standard env vars.

### 5.2 LocalIntegration (`src/config/local_integration.py`)

Drop-in replacement for `GCPIntegration`. Implements the same interface so all existing agent code works without changes.

| `GCPIntegration` attribute | `LocalIntegration` equivalent |
|----------------------------|-------------------------------|
| `firestore_client` | `SQLiteClient` instance |
| `get_secret(name)` | Maps secret ID → `LocalConfig` field |
| `get_model_registry()` | Reads `model_registry` table; falls back to `src/ai_engine/default_registry.json` |

**Secret → config field mapping:**

| Secret ID | `LocalConfig` field |
|-----------|---------------------|
| `anthropic-api-key` | `anthropic_api_key` |
| `gemini-api-key` | `gemini_api_key` |
| `openai-api-key` | `openai_api_key` |
| `xai-api-key` | `xai_api_key` |

### 5.3 SQLiteClient (`src/db/sqlite/client.py`)

Async-compatible SQLite wrapper with Firestore-compatible fluent API so all existing agent and route code works unchanged.

**Key classes:**

| Class | Firestore equivalent | Notes |
|-------|---------------------|-------|
| `SQLiteClient` | `google.cloud.firestore.Client` | Connection pool via `threading.local()` |
| `CollectionRef` | `CollectionReference` | `.document()`, `.where()`, `.stream()` |
| `CollectionQuery` | `Query` | Chainable `.where()`, `.order_by()`, `.limit()` |
| `DocumentRef` | `DocumentReference` | `.get()`, `.set()`, `.update()` |
| `DocumentSnapshot` | `DocumentSnapshot` | `.to_dict()`, `.exists` |
| `QuerySnapshot` | `QuerySnapshot` | Iterable of `DocumentSnapshot` |

**Atomic document counter:**
`increment_counter(project_id, doc_type)` uses `BEGIN IMMEDIATE` transaction to safely increment `doc_counters` and return the next integer — equivalent to Firestore `FieldValue.increment()` used in the cloud version.

**WAL mode** is enabled on first open: `PRAGMA journal_mode=WAL` — allows concurrent reads while a write is in progress (inbox watcher thread + API requests).

### 5.4 LocalStorageService (`src/storage/local/service.py`)

Drop-in for `DriveService`. Stores all files under `~/TeterAI/Projects/`.

| `DriveService` method | `LocalStorageService` equivalent |
|-----------------------|----------------------------------|
| `create_project_folders(project_id)` | `os.makedirs(...)` for each folder type |
| `upload_file(project_id, folder_type, name, data)` | `Path.write_bytes(data)` |
| `download_file(file_id)` | `Path.read_bytes()` |
| `list_files(project_id, folder_type)` | `os.listdir(...)` |
| `next_doc_number(project_id, doc_type)` | `SQLiteClient.increment_counter(...)` |

Factory function `get_storage_service()` in `src/storage/__init__.py` returns `LocalStorageService` when `DESKTOP_MODE=true`, else `DriveService`.

### 5.5 LocalInboxWatcher (`src/integrations/local_inbox/watcher.py`)

Background thread that polls `~/TeterAI/Inbox` for new documents.

**Poll cycle (every 30s by default):**
1. Scan inbox folder for `.eml`, `.pdf`, `.docx` files
2. For each file: check `processed_emails` table for dedup (keyed on `filename + mtime`)
3. `.eml` → parse with Python `email` stdlib → extract subject/sender/body/attachments → write `email_ingests` record
4. `.pdf` / `.docx` attachment or standalone → write `email_ingests` record with `source='folder_watch'`
5. All ingested files → create a `tasks` record in `PENDING_CLASSIFICATION` state

Started as a **daemon thread** in the FastAPI `lifespan` handler when `DESKTOP_MODE=true` — exits automatically when the server process exits.

---

## 6. API Changes

New and modified endpoints when `DESKTOP_MODE=true`:

| Method | Path | Behavior |
|--------|------|----------|
| `GET` | `/api/v1/settings` | Returns current `LocalConfig` fields (API keys masked) |
| `POST` | `/api/v1/settings` | Saves key/value pairs to `~/.teterai/config.env` and calls `push_to_env()` |
| `POST` | `/api/v1/ingest/upload` | Accepts multipart file upload; saves to inbox folder; triggers immediate ingest |
| `GET` | `/api/v1/gmail/*` | Returns HTTP 501 (Not Implemented) in desktop mode |

**Auth bypass:**
When `DESKTOP_MODE=true`, `src/ui/api/middleware.py` skips JWT validation and returns a hardcoded `UserInfo(uid="local", role="ADMIN")` for every request. No credentials are required.

---

## 7. Frontend Changes

| Component | Change |
|-----------|--------|
| `src/firebase.ts` | Replaced with null stub — `export const app = null; export const db = null` |
| `AuthContext.tsx` | When `VITE_DESKTOP_MODE=true`: skips Firebase, sets hardcoded desktop user, marks auth as loaded immediately |
| `useTaskQueue.ts` | Replaced Firestore `onSnapshot` with 5-second `setInterval` REST polling via `listTasks()` |
| `LoginPage.tsx` | When `VITE_DESKTOP_MODE=true`: immediately redirects to `/dashboard` (no login screen shown) |
| `SettingsPage.tsx` | New page — API key entry fields, folder path picker (calls `window.electronAPI.selectFolder()`), Neo4j connection status |
| `NavBar` | Settings link added when in desktop mode |

The React build for desktop uses a separate Vite config or env flag:
- `VITE_DESKTOP_MODE=true npm run build` → output to `src/ui/web/dist/`

---

## 8. Electron Shell & Packaging

### 8.1 `main.js` Responsibilities

1. **Spawn backend** — calls `getPythonExe()` to find the PyInstaller binary (packaged) or `uv run uvicorn` (dev), spawns as child process with `DESKTOP_MODE=true`
2. **Splash screen** — creates `BrowserWindow` immediately with `show: false`, loads `loading.html`; shows window on `ready-to-show` event
3. **API readiness** — `waitForAPI()` polls `http://127.0.0.1:8000/api/docs` every 500ms for up to 30 seconds
4. **Transition** — once API is ready, calls `mainWindow.loadURL('http://127.0.0.1:8000')` to load the React app
5. **IPC** — `ipcMain.handle('select-folder', ...)` opens native folder picker dialog; `ipcMain.handle('get-app-version', ...)` returns app version
6. **Cleanup** — kills `apiProcess` on `before-quit` and `will-quit`

### 8.2 `preload.js` IPC Surface

Exposed to renderer via `contextBridge.exposeInMainWorld('electronAPI', ...)`:

| Method | IPC channel | Returns |
|--------|-------------|---------|
| `selectFolder()` | `select-folder` | `string \| null` — absolute folder path or null if cancelled |
| `getAppVersion()` | `get-app-version` | `string` — semver app version |

### 8.3 PyInstaller Spec (`teterai-backend.spec`)

| Setting | Value |
|---------|-------|
| Entry point | `desktop_server.py` (repo root) |
| Mode | `onedir` — folder bundle (faster startup than `--onefile`) |
| `console` | `False` — no terminal window on Windows |
| `name` | `teterai-backend` |
| Output | `dist/teterai-backend/teterai-backend.exe` + `_internal/` |

**Data files bundled:**
- `src/` → `src/` (agents, api, config, db, storage, integrations, etc.)
- `src/ui/web/dist/` → `src/ui/web/dist/` (pre-built React app served by FastAPI staticfiles)

**Key hidden imports:** `uvicorn`, `uvicorn.loops.auto`, `uvicorn.protocols.http.auto`, `fastapi`, `starlette`, `pydantic`, `litellm`, `aiosqlite`, `sqlite3`, `jwt`, `pypdf`, `docx`, `email`, `multipart`, `httpx`

**Excluded:** `google.cloud.firestore`, `google.cloud.secretmanager`, `neo4j`, `torch`, `tensorflow`, `sklearn`, `tkinter`

### 8.4 electron-builder Config (`package.json`)

```json
"extraResources": [
  { "from": "../web/dist",              "to": "web-dist"  },
  { "from": "../../dist/teterai-backend", "to": "backend" }
],
"win": {
  "target": [{ "target": "nsis", "arch": ["x64"] }],
  "icon": "build-resources/icon.ico",
  "requestedExecutionLevel": "asInvoker"
},
"nsis": {
  "oneClick": false,
  "perMachine": false,
  "allowToChangeInstallationDirectory": true,
  "createDesktopShortcut": true,
  "createStartMenuShortcut": true,
  "shortcutName": "TeterAI CA"
},
"asar": true
```

### 8.5 Build Sequence

```bash
# Step 1 — React web build (with desktop env flag)
cd src/ui/web
VITE_DESKTOP_MODE=true npm run build
# Output: src/ui/web/dist/

# Step 2 — Python backend bundle (run from repo root, on Windows target machine)
pip install pyinstaller
pyinstaller teterai-backend.spec
# Output: dist/teterai-backend/  (~150-200 MB self-contained folder)

# Step 3 — Electron NSIS installer
cd src/ui/desktop
npm install
npm run build
# Output: dist-electron/TeterAI-CA-Setup-0.1.0.exe
```

---

## 9. Environment Variables

| Variable | Set By | Default | Effect |
|----------|--------|---------|--------|
| `DESKTOP_MODE` | `desktop_server.py` (via `os.environ.setdefault`) | `false` | Activates all local-mode behavior in backend |
| `VITE_DESKTOP_MODE` | Build script / `.env` | `false` | Activates auth bypass and REST polling in React build |
| `ANTHROPIC_API_KEY` | `LocalConfig.push_to_env()` | _(empty)_ | LiteLLM uses this for Anthropic calls |
| `GEMINI_API_KEY` | `LocalConfig.push_to_env()` | _(empty)_ | LiteLLM uses this for Gemini calls |
| `OPENAI_API_KEY` | `LocalConfig.push_to_env()` | _(empty)_ | LiteLLM uses this for OpenAI calls |
| `XAI_API_KEY` | `LocalConfig.push_to_env()` | _(empty)_ | LiteLLM uses this for Grok calls |
| `NEO4J_URI` | `LocalConfig.push_to_env()` | _(empty)_ | Optional Neo4j knowledge graph |
| `TETERAI_DATA_DIR` | `config.env` | `~/TeterAI` | Root for SQLite, Projects, Inbox |
| `TETERAI_INBOX_DIR` | `config.env` | `~/TeterAI/Inbox` | Inbox watcher scan target |
| `TETERAI_INBOX_POLL_INTERVAL` | `config.env` | `30` | Seconds between inbox polls |

---

## 10. First-Launch Experience

1. User double-clicks `TeterAI-CA-Setup-0.1.0.exe`
2. NSIS installer wizard: choose install directory → Next → Install → Finish
3. Start Menu shortcut "TeterAI CA" created; optional Desktop shortcut
4. User double-clicks shortcut
5. **TeterAI CA** window opens immediately showing branded dark splash screen ("TeterAI CA — Construction Administration" + spinner)
6. FastAPI backend starts in background (~2-4 seconds on a modern laptop)
7. Splash transitions to the full React dashboard (no visible blank white flash)
8. First run: dashboard is empty; user navigates to **Settings**
9. User enters `ANTHROPIC_API_KEY` (required) and optionally other API keys; selects data folder if desired
10. Settings are saved to `~/.teterai/config.env` and applied immediately (no restart required)
11. User places project emails (`.eml`) or PDFs into `~/TeterAI/Inbox/`
12. Within 30 seconds, inbox watcher picks up the files and creates tasks in the queue
13. User reviews tasks in the **Action Dashboard** → approves/rejects → AI processes → output staged for review

---

## 11. Limitations vs. Cloud Mode

| Feature | Cloud Mode | Desktop Mode |
|---------|-----------|--------------|
| Real-time updates | Firestore `onSnapshot` (instant) | 5-second REST polling |
| Gmail inbox | OAuth integration, automatic | Manual `.eml` drop to `~/TeterAI/Inbox` |
| Multi-user | Yes (Firebase Auth, roles) | Single user only (hardcoded ADMIN) |
| Authentication | Firebase JWT | Bypassed (`DESKTOP_MODE=true`) |
| Mobile app | Flutter iOS/Android | Not supported |
| Knowledge graph | Neo4j (cloud or self-hosted) | Optional; connection configured in Settings |
| File storage | Google Drive | Local filesystem `~/TeterAI/Projects/` |
| Secrets | GCP Secret Manager | `~/.teterai/config.env` |
| Backups | GCP-managed | User responsibility (copy `~/TeterAI/`) |

---

## 12. Testing Requirements

- [ ] `python desktop_server.py` from repo root → server starts on `:8000` with `DESKTOP_MODE=true`
- [ ] `pyinstaller teterai-backend.spec` completes without errors → `dist/teterai-backend/teterai-backend.exe` exists
- [ ] Running `dist/teterai-backend/teterai-backend.exe` directly → FastAPI starts on `:8000` with no console window
- [ ] `npm start` in `src/ui/desktop/` (dev mode) → branded splash screen shown, transitions to app within 5s
- [ ] Packaged: NSIS installer runs without elevation prompt, creates Start Menu + optional Desktop shortcut
- [ ] App launches on double-click: splash → dashboard (no terminal, no Python required)
- [ ] Settings page: API key saved → `~/.teterai/config.env` updated → key reflected in subsequent API calls
- [ ] Inbox watcher: `.eml` file dropped in `~/TeterAI/Inbox` → task appears in dashboard within 35s
- [ ] Document upload via `/api/v1/ingest/upload` → file saved, task created
- [ ] Atomic counter: concurrent task creation for same project → sequential doc numbers, no duplicates
- [ ] SQLite WAL: inbox watcher write + simultaneous API read → no locked-database errors

---

## 13. Revision History

| Version | Date | Author | Notes |
|---------|------|--------|-------|
| v0.1.0 | 2026-03-25 | Claude / TeterAI team | Initial spec — documents desktop mode implementation |
