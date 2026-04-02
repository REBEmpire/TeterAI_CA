import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  getCloseoutSummary,
  updateChecklistItem,
  createDeficiency,
  scanCloseoutFolder,
  addChecklistItem,
} from '../api/client'
import type {
  CloseoutChecklistItem,
  CloseoutDeficiency,
  CloseoutSummary,
  CloseoutItemStatus,
} from '../types'
import { UrgencyBadge } from '../components/common/UrgencyBadge'

const STATUS_OPTIONS: CloseoutItemStatus[] = [
  'NOT_RECEIVED',
  'RECEIVED',
  'UNDER_REVIEW',
  'ACCEPTED',
  'DEFICIENT',
]

const STATUS_COLORS: Record<CloseoutItemStatus, string> = {
  NOT_RECEIVED: 'text-red-600',
  RECEIVED: 'text-blue-600',
  UNDER_REVIEW: 'text-yellow-600',
  ACCEPTED: 'text-green-700',
  DEFICIENT: 'text-orange-600',
}

const DOC_TYPE_LABELS: Record<string, string> = {
  WARRANTY: 'Warranty',
  OM_MANUAL: 'O&M Manual',
  AS_BUILT: 'As-Built',
  TESTING_REPORT: 'Testing Report',
  GOV_PAPERWORK: 'Gov Paperwork',
  PROJECT_DIRECTORY: 'Project Directory',
  RFI_LOG: 'RFI Log',
}

function formatStatus(s: string): string {
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export function CloseoutReview() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const [summary, setSummary] = useState<CloseoutSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [scanning, setScanning] = useState(false)
  const [scanMsg, setScanMsg] = useState<string | null>(null)
  const [updatingItem, setUpdatingItem] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  // Deficiency modal
  const [deficiencyTarget, setDeficiencyTarget] = useState<CloseoutChecklistItem | null>(null)
  const [defForm, setDefForm] = useState({ description: '', severity: 'MEDIUM' })
  const [defSaving, setDefSaving] = useState(false)

  // Add item modal
  const [showAddItem, setShowAddItem] = useState(false)
  const [addForm, setAddForm] = useState({
    spec_section: '',
    spec_title: '',
    document_type: 'WARRANTY',
    urgency: 'MEDIUM',
    responsible_party: '',
  })
  const [addSaving, setAddSaving] = useState(false)

  useEffect(() => {
    if (!projectId) return
    setLoading(true)
    getCloseoutSummary(projectId)
      .then(setSummary)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load closeout data.'))
      .finally(() => setLoading(false))
  }, [projectId])

  function showToast(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(null), 4000)
  }

  async function handleStatusChange(item: CloseoutChecklistItem, newStatus: string) {
    if (!projectId) return
    setUpdatingItem(item.item_id)
    try {
      const updated = await updateChecklistItem(projectId, item.item_id, { status: newStatus })
      setSummary((prev) => {
        if (!prev) return prev
        const items = prev.items.map((i) => (i.item_id === item.item_id ? updated : i))
        return recomputeSummary(prev, items, prev.deficiencies)
      })
    } catch (e: unknown) {
      showToast(e instanceof Error ? e.message : 'Update failed.')
    } finally {
      setUpdatingItem(null)
    }
  }

  async function handleScan() {
    if (!projectId) return
    setScanning(true)
    setScanMsg(null)
    try {
      const result = await scanCloseoutFolder(projectId)
      setScanMsg(`Matched ${result.matched.length} file(s). ${result.unmatched.length} unmatched.`)
      // Refresh summary
      const refreshed = await getCloseoutSummary(projectId)
      setSummary(refreshed)
    } catch (e: unknown) {
      setScanMsg(e instanceof Error ? e.message : 'Scan failed.')
    } finally {
      setScanning(false)
    }
  }

  async function handleCreateDeficiency() {
    if (!projectId || !deficiencyTarget || !defForm.description.trim()) return
    setDefSaving(true)
    try {
      const def = await createDeficiency(projectId, deficiencyTarget.item_id, {
        description: defForm.description,
        severity: defForm.severity,
      })
      setSummary((prev) => {
        if (!prev) return prev
        const deficiencies = [...prev.deficiencies, def]
        const items = prev.items.map((i) =>
          i.item_id === deficiencyTarget.item_id ? { ...i, status: 'DEFICIENT' as CloseoutItemStatus } : i
        )
        return recomputeSummary(prev, items, deficiencies)
      })
      setDeficiencyTarget(null)
      setDefForm({ description: '', severity: 'MEDIUM' })
      showToast('Deficiency created.')
    } catch (e: unknown) {
      showToast(e instanceof Error ? e.message : 'Failed to create deficiency.')
    } finally {
      setDefSaving(false)
    }
  }

  async function handleAddItem() {
    if (!projectId || !addForm.spec_section.trim() || !addForm.spec_title.trim()) return
    setAddSaving(true)
    try {
      const item = await addChecklistItem(projectId, {
        spec_section: addForm.spec_section,
        spec_title: addForm.spec_title,
        document_type: addForm.document_type,
        urgency: addForm.urgency,
        responsible_party: addForm.responsible_party || undefined,
      })
      setSummary((prev) => {
        if (!prev) return prev
        const items = [...prev.items, item]
        return recomputeSummary(prev, items, prev.deficiencies)
      })
      setShowAddItem(false)
      setAddForm({ spec_section: '', spec_title: '', document_type: 'WARRANTY', urgency: 'MEDIUM', responsible_party: '' })
      showToast('Checklist item added.')
    } catch (e: unknown) {
      showToast(e instanceof Error ? e.message : 'Failed to add item.')
    } finally {
      setAddSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="max-w-wide mx-auto px-4 py-6">
        <div className="text-sm text-teter-gray-text">Loading closeout data...</div>
      </div>
    )
  }

  if (error || !summary) {
    return (
      <div className="max-w-wide mx-auto px-4 py-6">
        <div className="text-sm text-red-600">{error || 'No closeout data available.'}</div>
        <button className="btn-outline text-sm mt-4" onClick={() => navigate(-1)}>Back</button>
      </div>
    )
  }

  const itemDeficiencies = (itemId: string): CloseoutDeficiency[] =>
    summary.deficiencies.filter((d) => d.item_id === itemId)

  return (
    <div className="max-w-wide mx-auto px-4 py-6">
      {/* Toast */}
      {toast && (
        <div className="fixed top-4 right-4 z-50 bg-teter-dark text-white px-4 py-3 rounded shadow-lg text-sm flex items-center gap-2">
          {toast}
          <button className="text-white/60 hover:text-white ml-2" onClick={() => setToast(null)}>x</button>
        </div>
      )}

      {/* Deficiency modal */}
      {deficiencyTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4">
            <h3 className="text-base font-semibold text-teter-dark mb-1">Add Deficiency</h3>
            <p className="text-xs text-teter-gray-text mb-4">{deficiencyTarget.label}</p>
            <div className="flex flex-col gap-3">
              <div>
                <label className="label">Description *</label>
                <textarea
                  className="input w-full h-20 resize-none"
                  value={defForm.description}
                  onChange={(e) => setDefForm({ ...defForm, description: e.target.value })}
                  placeholder="Describe the deficiency..."
                />
              </div>
              <div className="w-40">
                <label className="label">Severity</label>
                <select
                  className="select w-full"
                  value={defForm.severity}
                  onChange={(e) => setDefForm({ ...defForm, severity: e.target.value })}
                >
                  <option value="LOW">Low</option>
                  <option value="MEDIUM">Medium</option>
                  <option value="HIGH">High</option>
                </select>
              </div>
            </div>
            <div className="flex gap-2 justify-end mt-4">
              <button className="btn-outline text-sm" onClick={() => setDeficiencyTarget(null)}>Cancel</button>
              <button
                className="btn-primary text-sm"
                onClick={handleCreateDeficiency}
                disabled={defSaving || !defForm.description.trim()}
              >
                {defSaving ? 'Creating...' : 'Create Deficiency'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add item modal */}
      {showAddItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4">
            <h3 className="text-base font-semibold text-teter-dark mb-4">Add Spec Section</h3>
            <div className="flex flex-col gap-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Spec Section *</label>
                  <input
                    className="input"
                    value={addForm.spec_section}
                    onChange={(e) => setAddForm({ ...addForm, spec_section: e.target.value })}
                    placeholder="09 68 00"
                  />
                </div>
                <div>
                  <label className="label">Title *</label>
                  <input
                    className="input"
                    value={addForm.spec_title}
                    onChange={(e) => setAddForm({ ...addForm, spec_title: e.target.value })}
                    placeholder="Carpeting"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Document Type</label>
                  <select
                    className="select w-full"
                    value={addForm.document_type}
                    onChange={(e) => setAddForm({ ...addForm, document_type: e.target.value })}
                  >
                    {Object.entries(DOC_TYPE_LABELS).map(([k, v]) => (
                      <option key={k} value={k}>{v}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label">Urgency</label>
                  <select
                    className="select w-full"
                    value={addForm.urgency}
                    onChange={(e) => setAddForm({ ...addForm, urgency: e.target.value })}
                  >
                    <option value="LOW">Low</option>
                    <option value="MEDIUM">Medium</option>
                    <option value="HIGH">High</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="label">Responsible Party</label>
                <input
                  className="input"
                  value={addForm.responsible_party}
                  onChange={(e) => setAddForm({ ...addForm, responsible_party: e.target.value })}
                  placeholder="Subcontractor name (optional)"
                />
              </div>
            </div>
            <div className="flex gap-2 justify-end mt-4">
              <button className="btn-outline text-sm" onClick={() => setShowAddItem(false)}>Cancel</button>
              <button
                className="btn-primary text-sm"
                onClick={handleAddItem}
                disabled={addSaving || !addForm.spec_section.trim() || !addForm.spec_title.trim()}
              >
                {addSaving ? 'Adding...' : 'Add Item'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <span className="w-1 h-8 bg-teter-orange rounded-sm" />
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-teter-dark">{summary.project_name}</h1>
          <p className="text-sm text-teter-gray-text mt-0.5">Closeout Review</p>
        </div>
        <span className="px-3 py-1 rounded-full text-xs font-semibold uppercase bg-teter-orange/10 text-teter-orange">
          Closeout
        </span>
      </div>

      {/* Progress bar */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-1">
          <span className="text-sm font-semibold text-teter-dark">Overall Completion</span>
          <span className="text-sm font-semibold text-teter-orange">{summary.completion_pct}%</span>
        </div>
        <div className="w-full bg-teter-gray rounded-full h-3">
          <div
            className="bg-teter-orange h-3 rounded-full transition-all duration-500"
            style={{ width: `${summary.completion_pct}%` }}
          />
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-white rounded border border-teter-gray-mid shadow-card p-4">
          <div className="text-2xl font-bold text-red-600">{summary.not_received}</div>
          <div className="text-xs text-teter-gray-text font-semibold mt-1">Not Received</div>
        </div>
        <div className="bg-white rounded border border-teter-gray-mid shadow-card p-4">
          <div className="text-2xl font-bold text-blue-600">{summary.received + summary.under_review}</div>
          <div className="text-xs text-teter-gray-text font-semibold mt-1">Received / Under Review</div>
        </div>
        <div className="bg-white rounded border border-teter-gray-mid shadow-card p-4">
          <div className="text-2xl font-bold text-green-700">{summary.accepted}</div>
          <div className="text-xs text-teter-gray-text font-semibold mt-1">Accepted</div>
        </div>
        <div className="bg-white rounded border border-teter-gray-mid shadow-card p-4">
          <div className="text-2xl font-bold text-orange-600">{summary.deficient}</div>
          <div className="text-xs text-teter-gray-text font-semibold mt-1">Deficient</div>
        </div>
      </div>

      {/* Actions bar */}
      <div className="flex items-center gap-2 mb-4">
        <button
          className="btn-primary text-sm"
          onClick={handleScan}
          disabled={scanning}
        >
          {scanning ? 'Scanning...' : 'Scan Closeout Folder'}
        </button>
        <button className="btn-outline text-sm" onClick={() => setShowAddItem(true)}>
          + Add Spec Section
        </button>
        {scanMsg && (
          <span className="text-sm text-teter-gray-text ml-2">{scanMsg}</span>
        )}
      </div>

      {/* Checklist table */}
      <div className="bg-white rounded border border-teter-gray-mid shadow-card overflow-hidden">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-teter-gray-mid text-left bg-teter-gray/50">
              <th className="p-3 font-semibold text-teter-gray-text">Spec Section</th>
              <th className="p-3 font-semibold text-teter-gray-text">Title</th>
              <th className="p-3 font-semibold text-teter-gray-text">Doc Type</th>
              <th className="p-3 font-semibold text-teter-gray-text">Urgency</th>
              <th className="p-3 font-semibold text-teter-gray-text">Status</th>
              <th className="p-3 font-semibold text-teter-gray-text">Responsible Party</th>
              <th className="p-3 font-semibold text-teter-gray-text">Document</th>
              <th className="p-3 font-semibold text-teter-gray-text">Actions</th>
            </tr>
          </thead>
          <tbody>
            {summary.items.map((item) => {
              const defs = itemDeficiencies(item.item_id)
              return (
                <tr
                  key={item.item_id}
                  className={`border-b border-teter-gray last:border-0 ${
                    item.status === 'DEFICIENT' ? 'bg-orange-50' : ''
                  }`}
                >
                  <td className="p-3 font-mono text-xs text-teter-dark">{item.spec_section}</td>
                  <td className="p-3 text-teter-dark">{item.spec_title}</td>
                  <td className="p-3">
                    <span className="text-xs font-semibold text-teter-gray-text">
                      {DOC_TYPE_LABELS[item.document_type] || item.document_type}
                    </span>
                  </td>
                  <td className="p-3">
                    <UrgencyBadge urgency={item.urgency} showDot={false} />
                  </td>
                  <td className="p-3">
                    <select
                      className={`select text-xs py-1 font-semibold ${STATUS_COLORS[item.status] || ''}`}
                      value={item.status}
                      onChange={(e) => handleStatusChange(item, e.target.value)}
                      disabled={updatingItem === item.item_id}
                    >
                      {STATUS_OPTIONS.map((s) => (
                        <option key={s} value={s}>{formatStatus(s)}</option>
                      ))}
                    </select>
                  </td>
                  <td className="p-3 text-xs text-teter-gray-text">
                    {item.responsible_party || '—'}
                  </td>
                  <td className="p-3">
                    {item.document_path ? (
                      <span className="text-xs text-green-700 font-semibold" title={item.document_path}>
                        Received
                      </span>
                    ) : (
                      <span className="text-xs text-red-500">Missing</span>
                    )}
                  </td>
                  <td className="p-3">
                    <div className="flex items-center gap-2">
                      <button
                        className="text-xs text-teter-orange hover:underline font-semibold"
                        onClick={() => setDeficiencyTarget(item)}
                      >
                        + Deficiency
                      </button>
                      {defs.length > 0 && (
                        <span className="text-xs bg-orange-100 text-orange-700 px-1.5 py-0.5 rounded-full font-semibold">
                          {defs.length}
                        </span>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Deficiencies section */}
      {summary.deficiencies.length > 0 && (
        <div className="mt-6">
          <h2 className="text-base font-semibold text-teter-dark mb-3">Deficiency Notices</h2>
          <div className="bg-white rounded border border-teter-gray-mid shadow-card overflow-hidden">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="border-b border-teter-gray-mid text-left bg-teter-gray/50">
                  <th className="p-3 font-semibold text-teter-gray-text">Checklist Item</th>
                  <th className="p-3 font-semibold text-teter-gray-text">Description</th>
                  <th className="p-3 font-semibold text-teter-gray-text">Severity</th>
                  <th className="p-3 font-semibold text-teter-gray-text">Status</th>
                  <th className="p-3 font-semibold text-teter-gray-text">Created</th>
                </tr>
              </thead>
              <tbody>
                {summary.deficiencies.map((d) => {
                  const parentItem = summary.items.find((i) => i.item_id === d.item_id)
                  return (
                    <tr key={d.deficiency_id} className="border-b border-teter-gray last:border-0">
                      <td className="p-3 text-xs text-teter-dark">
                        {parentItem ? `${parentItem.spec_section} — ${parentItem.spec_title}` : d.item_id}
                      </td>
                      <td className="p-3 text-teter-dark">{d.description}</td>
                      <td className="p-3">
                        <span className={`text-xs font-semibold uppercase ${
                          d.severity === 'HIGH' ? 'text-red-600' :
                          d.severity === 'MEDIUM' ? 'text-yellow-600' : 'text-teter-gray-text'
                        }`}>
                          {d.severity}
                        </span>
                      </td>
                      <td className="p-3">
                        <span className={`text-xs font-semibold ${
                          d.status === 'OPEN' ? 'text-red-600' :
                          d.status === 'RESOLVED' ? 'text-green-700' : 'text-teter-gray-text'
                        }`}>
                          {d.status}
                        </span>
                      </td>
                      <td className="p-3 text-xs text-teter-gray-text">
                        {d.created_at ? new Date(d.created_at).toLocaleDateString() : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function recomputeSummary(
  prev: CloseoutSummary,
  items: CloseoutChecklistItem[],
  deficiencies: CloseoutDeficiency[],
): CloseoutSummary {
  const total = items.length
  const counts = { NOT_RECEIVED: 0, RECEIVED: 0, UNDER_REVIEW: 0, ACCEPTED: 0, DEFICIENT: 0 }
  for (const item of items) {
    counts[item.status] = (counts[item.status] || 0) + 1
  }
  return {
    ...prev,
    items,
    deficiencies,
    total_items: total,
    not_received: counts.NOT_RECEIVED,
    received: counts.RECEIVED,
    under_review: counts.UNDER_REVIEW,
    accepted: counts.ACCEPTED,
    deficient: counts.DEFICIENT,
    completion_pct: total > 0 ? Math.round((counts.ACCEPTED / total) * 1000) / 10 : 0,
  }
}
