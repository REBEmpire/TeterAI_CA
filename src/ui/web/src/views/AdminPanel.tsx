import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  createProject,
  getModelRegistry,
  getTaskAudit,
  listProjects,
  listUsers,
  scanProjects,
  updateModel,
  updateProject,
  updateUserRole,
  auditExportUrl,
} from '../api/client'
import type { ScanProjectsResponse } from '../api/client'
import type {
  AuditEntrySummary,
  ModelRegistryEntry,
  ProjectSummary,
  UserRole,
  UserSummary,
} from '../types'

type AdminTab = 'projects' | 'users' | 'models' | 'audit'

// ---------------------------------------------------------------------------
// Projects tab
// ---------------------------------------------------------------------------

function ProjectsTab() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ project_number: '', name: '', phase: 'construction' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [scanning, setScanning] = useState(false)
  const [scanResult, setScanResult] = useState<ScanProjectsResponse | null>(null)
  const [phaseConfirm, setPhaseConfirm] = useState<{ project: ProjectSummary; newPhase: string } | null>(null)
  const [phaseChanging, setPhaseChanging] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    listProjects().then(setProjects).finally(() => setLoading(false))
  }, [])

  async function handleCreate() {
    if (!form.project_number || !form.name) return
    setSaving(true)
    setError(null)
    try {
      const p = await createProject(form)
      setProjects((prev) => [p, ...prev])
      setShowForm(false)
      setForm({ project_number: '', name: '', phase: 'construction' })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to create project.')
    } finally {
      setSaving(false)
    }
  }

  async function handleScan() {
    setScanning(true)
    setScanResult(null)
    try {
      const result = await scanProjects()
      setScanResult(result)
      if (result.imported.length > 0) {
        setProjects((prev) => [...result.imported, ...prev])
      }
    } catch (e: unknown) {
      setScanResult({ imported: [], skipped: 0, errors: [e instanceof Error ? e.message : 'Scan failed.'] })
    } finally {
      setScanning(false)
    }
  }

  function handlePhaseSelect(project: ProjectSummary, newPhase: string) {
    if (newPhase === project.phase) return
    setPhaseConfirm({ project, newPhase })
  }

  async function confirmPhaseChange() {
    if (!phaseConfirm) return
    const { project, newPhase } = phaseConfirm
    setPhaseChanging(project.project_id)
    setPhaseConfirm(null)
    try {
      const updated = await updateProject(project.project_id, { phase: newPhase })
      setProjects((prev) => prev.map((p) => (p.project_id === project.project_id ? updated : p)))
      const msg = newPhase === 'closeout'
        ? `${project.name} transitioned to Closeout. Checklist initialized.`
        : `${project.name} transitioned to ${newPhase}.`
      setToast(msg)
      setTimeout(() => setToast(null), 4000)
    } catch (e: unknown) {
      setToast(e instanceof Error ? e.message : 'Phase change failed.')
      setTimeout(() => setToast(null), 4000)
    } finally {
      setPhaseChanging(null)
    }
  }

  return (
    <div>
      {/* Toast notification */}
      {toast && (
        <div className="fixed top-4 right-4 z-50 bg-teter-dark text-white px-4 py-3 rounded shadow-lg text-sm flex items-center gap-2">
          {toast}
          <button className="text-white/60 hover:text-white ml-2" onClick={() => setToast(null)}>x</button>
        </div>
      )}

      {/* Phase transition confirmation modal */}
      {phaseConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4">
            <h3 className="text-base font-semibold text-teter-dark mb-3">Confirm Phase Transition</h3>
            <p className="text-sm text-teter-gray-text mb-2">
              Transition <span className="font-semibold text-teter-dark">{phaseConfirm.project.name}</span> from{' '}
              <span className="capitalize font-semibold">{phaseConfirm.project.phase}</span> to{' '}
              <span className="capitalize font-semibold text-teter-orange">{phaseConfirm.newPhase}</span>?
            </p>
            {phaseConfirm.newPhase === 'closeout' && (
              <p className="text-sm text-teter-orange bg-teter-orange/10 rounded p-2 mb-3">
                This will initialize the closeout checklist with default spec section deliverables.
              </p>
            )}
            <div className="flex gap-2 justify-end mt-4">
              <button className="btn-outline text-sm" onClick={() => setPhaseConfirm(null)}>Cancel</button>
              <button className="btn-primary text-sm" onClick={confirmPhaseChange}>Confirm Transition</button>
            </div>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between mb-4">
        <h2 className="text-base font-semibold text-teter-dark">Projects</h2>
        <div className="flex gap-2">
          <button className="btn-primary text-sm" onClick={() => setShowForm((v) => !v)}>
            {showForm ? 'Cancel' : '+ New Project'}
          </button>
          <button className="btn-outline text-sm" onClick={handleScan} disabled={scanning}>
            {scanning ? 'Scanning\u2026' : 'Scan Folders'}
          </button>
        </div>
      </div>

      {scanResult && (
        <div className="bg-teter-gray rounded p-3 mb-4 text-sm flex items-center gap-3">
          {scanResult.imported.length > 0 && (
            <span className="text-green-700 font-semibold">{scanResult.imported.length} imported</span>
          )}
          {scanResult.imported.length === 0 && scanResult.errors.length === 0 && (
            <span className="text-teter-gray-text">No new projects found.</span>
          )}
          {scanResult.skipped > 0 && (
            <span className="text-teter-gray-text">{scanResult.skipped} already registered</span>
          )}
          {scanResult.errors.length > 0 && (
            <span className="text-red-600">{scanResult.errors.join('; ')}</span>
          )}
          <button className="ml-auto text-xs text-teter-gray-text hover:text-teter-dark" onClick={() => setScanResult(null)}>
            Dismiss
          </button>
        </div>
      )}

      {showForm && (
        <div className="bg-teter-gray rounded p-4 mb-4 flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Project Number *</label>
              <input
                className="input"
                value={form.project_number}
                onChange={(e) => setForm({ ...form, project_number: e.target.value })}
                placeholder="2026-003"
              />
            </div>
            <div>
              <label className="label">Project Name *</label>
              <input
                className="input"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Riverfront Medical Center"
              />
            </div>
          </div>
          <div className="w-40">
            <label className="label">Phase</label>
            <select
              className="select w-full"
              value={form.phase}
              onChange={(e) => setForm({ ...form, phase: e.target.value })}
            >
              <option value="bid">Bid</option>
              <option value="construction">Construction</option>
              <option value="closeout">Closeout</option>
            </select>
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex gap-2">
            <button className="btn-primary text-sm" onClick={handleCreate} disabled={saving}>
              {saving ? 'Creating…' : 'Create Project'}
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="text-sm text-teter-gray-text">Loading…</div>
      ) : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-teter-gray-mid text-left">
              <th className="pb-2 font-semibold text-teter-gray-text pr-4">Number</th>
              <th className="pb-2 font-semibold text-teter-gray-text pr-4">Name</th>
              <th className="pb-2 font-semibold text-teter-gray-text pr-4">Phase</th>
              <th className="pb-2 font-semibold text-teter-gray-text pr-4">Status</th>
              <th className="pb-2 font-semibold text-teter-gray-text">Actions</th>
            </tr>
          </thead>
          <tbody>
            {projects.map((p) => (
              <tr key={p.project_id} className="border-b border-teter-gray last:border-0">
                <td className="py-2.5 pr-4 font-semibold text-teter-orange">{p.project_number}</td>
                <td className="py-2.5 pr-4 text-teter-dark">{p.name}</td>
                <td className="py-2.5 pr-4">
                  <select
                    className="select text-xs py-1 capitalize"
                    value={p.phase}
                    onChange={(e) => handlePhaseSelect(p, e.target.value)}
                    disabled={phaseChanging === p.project_id}
                  >
                    <option value="bid">Bid</option>
                    <option value="construction">Construction</option>
                    <option value="closeout">Closeout</option>
                  </select>
                </td>
                <td className="py-2.5 pr-4">
                  <span className={`text-xs font-semibold ${p.active ? 'text-green-700' : 'text-teter-gray-text'}`}>
                    {p.active ? 'Active' : 'Inactive'}
                  </span>
                </td>
                <td className="py-2.5">
                  {p.phase === 'closeout' && (
                    <button
                      className="text-xs font-semibold text-teter-orange hover:underline"
                      onClick={() => navigate(`/projects/${p.project_id}/closeout`)}
                    >
                      View Closeout
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Users tab
// ---------------------------------------------------------------------------

const ROLES: UserRole[] = ['CA_STAFF', 'ADMIN', 'REVIEWER']

function UsersTab() {
  const [users, setUsers] = useState<UserSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<string | null>(null)

  useEffect(() => {
    listUsers().then(setUsers).finally(() => setLoading(false))
  }, [])

  async function handleRoleChange(uid: string, role: string) {
    setSaving(uid)
    try {
      await updateUserRole(uid, role)
      setUsers((prev) => prev.map((u) => (u.uid === uid ? { ...u, role: role as UserRole } : u)))
    } catch {
      // ignore
    } finally {
      setSaving(null)
    }
  }

  return (
    <div>
      <h2 className="text-base font-semibold text-teter-dark mb-4">Users</h2>
      {loading ? (
        <div className="text-sm text-teter-gray-text">Loading…</div>
      ) : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-teter-gray-mid text-left">
              <th className="pb-2 font-semibold text-teter-gray-text pr-4">Name</th>
              <th className="pb-2 font-semibold text-teter-gray-text pr-4">Email</th>
              <th className="pb-2 font-semibold text-teter-gray-text pr-4">Role</th>
              <th className="pb-2 font-semibold text-teter-gray-text">Status</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.uid} className="border-b border-teter-gray last:border-0">
                <td className="py-2.5 pr-4 font-semibold text-teter-dark">{u.display_name}</td>
                <td className="py-2.5 pr-4 text-teter-gray-text">{u.email}</td>
                <td className="py-2.5 pr-4">
                  <select
                    className="select text-xs py-1"
                    value={u.role}
                    onChange={(e) => handleRoleChange(u.uid, e.target.value)}
                    disabled={saving === u.uid}
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r}>{r.replace('_', ' ')}</option>
                    ))}
                  </select>
                </td>
                <td className="py-2.5">
                  <span className={`text-xs font-semibold ${u.active ? 'text-green-700' : 'text-teter-gray-text'}`}>
                    {u.active ? 'Active' : 'Inactive'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Model Registry tab
// ---------------------------------------------------------------------------

function ModelsTab() {
  const [entries, setEntries] = useState<ModelRegistryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<{ cap: string; tier: number; value: string } | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    getModelRegistry().then(setEntries).finally(() => setLoading(false))
  }, [])

  async function handleSave() {
    if (!editing) return
    setSaving(true)
    try {
      await updateModel(editing.cap, editing.tier, editing.value)
      setEntries((prev) =>
        prev.map((e) => {
          if (e.capability_class !== editing.cap) return e
          return {
            ...e,
            [`tier_${editing.tier}`]: editing.value,
          }
        }),
      )
      setEditing(null)
    } catch {
      // ignore
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <h2 className="text-base font-semibold text-teter-dark mb-4">AI Model Registry</h2>
      {loading ? (
        <div className="text-sm text-teter-gray-text">Loading…</div>
      ) : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-teter-gray-mid text-left">
              <th className="pb-2 font-semibold text-teter-gray-text pr-4">Capability</th>
              <th className="pb-2 font-semibold text-teter-gray-text pr-4">Tier 1 (Primary)</th>
              <th className="pb-2 font-semibold text-teter-gray-text pr-4">Tier 2 (Fallback)</th>
              <th className="pb-2 font-semibold text-teter-gray-text">Tier 3 (Last resort)</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.capability_class} className="border-b border-teter-gray last:border-0">
                <td className="py-2.5 pr-4 font-semibold text-teter-orange text-xs uppercase">
                  {e.capability_class}
                </td>
                {([1, 2, 3] as const).map((tier) => {
                  const tierKey = `tier_${tier}` as keyof ModelRegistryEntry
                  const isEditing = editing?.cap === e.capability_class && editing?.tier === tier
                  return (
                    <td key={tier} className="py-2.5 pr-4">
                      {isEditing ? (
                        <div className="flex items-center gap-1">
                          <input
                            className="input text-xs py-1 w-48"
                            value={editing.value}
                            onChange={(v) => setEditing({ ...editing, value: v.target.value })}
                            autoFocus
                          />
                          <button className="btn-primary text-xs py-1 px-2" onClick={handleSave} disabled={saving}>
                            ✓
                          </button>
                          <button className="btn-outline text-xs py-1 px-2" onClick={() => setEditing(null)}>
                            ✕
                          </button>
                        </div>
                      ) : (
                        <button
                          className="text-teter-dark text-xs hover:text-teter-orange transition-colors group flex items-center gap-1"
                          onClick={() =>
                            setEditing({
                              cap: e.capability_class,
                              tier,
                              value: String(e[tierKey] ?? ''),
                            })
                          }
                        >
                          {String(e[tierKey] ?? '—')}
                          <span className="opacity-0 group-hover:opacity-100 text-teter-orange">✎</span>
                        </button>
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Audit Trail tab
// ---------------------------------------------------------------------------

function AuditTab() {
  const [taskId, setTaskId] = useState('')
  const [entries, setEntries] = useState<AuditEntrySummary[]>([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)

  async function handleSearch() {
    if (!taskId.trim()) return
    setLoading(true)
    setSearched(true)
    try {
      const results = await getTaskAudit(taskId.trim())
      setEntries(results)
    } catch {
      setEntries([])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h2 className="text-base font-semibold text-teter-dark mb-4">Audit Trail</h2>
      <div className="flex gap-2 mb-5">
        <input
          className="input max-w-xs"
          value={taskId}
          onChange={(e) => setTaskId(e.target.value)}
          placeholder="Task ID…"
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
        />
        <button className="btn-dark text-sm" onClick={handleSearch} disabled={loading}>
          Search
        </button>
        {searched && entries.length > 0 && (
          <a
            href={auditExportUrl(taskId)}
            className="btn-outline text-sm"
            download
          >
            Export CSV
          </a>
        )}
      </div>

      {loading ? (
        <div className="text-sm text-teter-gray-text">Loading…</div>
      ) : searched && entries.length === 0 ? (
        <div className="text-sm text-teter-gray-text">No audit entries found for this task.</div>
      ) : (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-teter-gray-mid text-left">
              <th className="pb-2 font-semibold text-teter-gray-text pr-3">Timestamp</th>
              <th className="pb-2 font-semibold text-teter-gray-text pr-3">Type</th>
              <th className="pb-2 font-semibold text-teter-gray-text pr-3">Action / Status</th>
              <th className="pb-2 font-semibold text-teter-gray-text">Actor</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.log_id} className="border-b border-teter-gray last:border-0">
                <td className="py-2 pr-3 text-teter-gray-text text-xs">
                  {e.timestamp ? new Date(e.timestamp).toLocaleString() : '—'}
                </td>
                <td className="py-2 pr-3 text-xs font-semibold uppercase text-teter-orange">
                  {e.log_type}
                </td>
                <td className="py-2 pr-3 text-teter-dark">
                  {e.action ?? e.status ?? '—'}
                </td>
                <td className="py-2 text-teter-gray-text text-xs">
                  {e.reviewer_uid ?? e.agent_id ?? '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Admin Panel shell
// ---------------------------------------------------------------------------

export function AdminPanel() {
  const [tab, setTab] = useState<AdminTab>('projects')

  const tabs: { id: AdminTab; label: string }[] = [
    { id: 'projects', label: 'Projects' },
    { id: 'users', label: 'Users' },
    { id: 'models', label: 'Model Registry' },
    { id: 'audit', label: 'Audit Trail' },
  ]

  return (
    <div className="max-w-wide mx-auto px-4 py-6">
      <div className="flex items-center gap-3 mb-6">
        <span className="w-1 h-8 bg-teter-orange rounded-sm" />
        <div>
          <h1 className="text-xl font-semibold text-teter-dark">Admin / Config</h1>
          <p className="text-sm text-teter-gray-text mt-0.5">System configuration and management</p>
        </div>
      </div>

      {/* Tab nav */}
      <div className="flex border-b border-teter-gray-mid mb-6 gap-1">
        {tabs.map((t) => (
          <button
            key={t.id}
            className={`px-4 py-2.5 text-sm font-semibold transition-colors ${
              tab === t.id ? 'tab-active' : 'tab-inactive'
            }`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="bg-white rounded border border-teter-gray-mid shadow-card p-6">
        {tab === 'projects' && <ProjectsTab />}
        {tab === 'users' && <UsersTab />}
        {tab === 'models' && <ModelsTab />}
        {tab === 'audit' && <AuditTab />}
      </div>
    </div>
  )
}
