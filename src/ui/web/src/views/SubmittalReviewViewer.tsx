import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  approveSubmittalReview,
  escalateTask,
  getSubmittalReview,
  getTask,
  rejectTask,
} from '../api/client'
import { UrgencyBadge } from '../components/common/UrgencyBadge'
import { RejectionDialog } from '../components/modals/RejectionDialog'
import { RedTeamAuditPanel } from '../components/review/RedTeamAuditPanel'
import type {
  RejectionReason,
  ReviewItemSeverity,
  SubmittalComparisonItem,
  SubmittalModelResult,
  SubmittalReviewData,
  SubmittalWarningItem,
  TaskDetail,
} from '../types'

// ---------------------------------------------------------------------------
// Severity styling helpers
// ---------------------------------------------------------------------------

function severityBadge(severity: ReviewItemSeverity) {
  if (severity === 'MAJOR_WARNING') {
    return (
      <span className="inline-block px-1.5 py-0.5 rounded text-xs font-bold bg-red-100 text-red-700 uppercase">
        ⚠ Major
      </span>
    )
  }
  if (severity === 'MINOR_NOTE') {
    return (
      <span className="inline-block px-1.5 py-0.5 rounded text-xs font-semibold bg-yellow-100 text-yellow-700 uppercase">
        Minor
      </span>
    )
  }
  return (
    <span className="inline-block px-1.5 py-0.5 rounded text-xs font-semibold bg-green-100 text-green-700 uppercase">
      OK
    </span>
  )
}

function rowBg(severity: ReviewItemSeverity, selected: boolean): string {
  if (!selected) return 'opacity-40'
  if (severity === 'MAJOR_WARNING') return 'bg-red-50'
  if (severity === 'MINOR_NOTE') return 'bg-yellow-50'
  return ''
}

// ---------------------------------------------------------------------------
// Default selection logic: select non-compliant / warning items by default
// ---------------------------------------------------------------------------

function defaultSelected(data: SubmittalReviewData): Record<string, boolean> {
  const sel: Record<string, boolean> = {}
  for (const tierResult of Object.values(data.model_results)) {
    const result = tierResult as SubmittalModelResult | undefined
    if (!result?.items) continue
    for (const row of result.items.comparison_table) {
      if (!(row.id in sel)) {
        sel[row.id] = !row.compliance || row.severity !== 'OK'
      }
    }
    for (const warn of result.items.warnings) {
      if (!(warn.id in sel)) sel[warn.id] = true
    }
    for (const miss of result.items.missing_info) {
      if (!(miss.id in sel)) sel[miss.id] = true
    }
  }
  return sel
}

// ---------------------------------------------------------------------------
// Model column component
// ---------------------------------------------------------------------------

function ModelColumn({
  tierKey,
  result,
  selections,
  onToggle,
}: {
  tierKey: string
  result: SubmittalModelResult | undefined
  selections: Record<string, boolean>
  onToggle: (id: string) => void
}) {
  const tierLabel = tierKey === 'tier_1' ? 'Model 1' : tierKey === 'tier_2' ? 'Model 2' : 'Model 3'

  if (!result) {
    return (
      <div className="flex flex-col border-r border-teter-gray-mid last:border-r-0 overflow-y-auto">
        <div className="px-3 py-2 bg-teter-gray border-b border-teter-gray-mid flex-shrink-0">
          <span className="text-xs font-semibold text-teter-gray-text">{tierLabel} — Not configured</span>
        </div>
        <div className="p-4 text-xs text-teter-gray-text italic">No data available.</div>
      </div>
    )
  }

  if (result.error) {
    return (
      <div className="flex flex-col border-r border-teter-gray-mid last:border-r-0 overflow-y-auto">
        <div className="px-3 py-2 bg-red-50 border-b border-red-200 flex-shrink-0">
          <span className="text-xs font-semibold text-red-700">{tierLabel} — Error</span>
          <div className="text-xs text-red-600 mt-0.5">{result.provider}/{result.model}</div>
        </div>
        <div className="p-4 bg-red-50 text-xs text-red-700">{result.error}</div>
      </div>
    )
  }

  const { comparison_table, warnings, missing_info, summary } = result.items

  return (
    <div className="flex flex-col border-r border-teter-gray-mid last:border-r-0 overflow-y-auto">
      {/* Column header */}
      <div className="px-3 py-2 bg-teter-gray border-b border-teter-gray-mid flex-shrink-0">
        <div className="text-xs font-semibold text-teter-dark">{tierLabel}</div>
        <div className="text-xs text-teter-gray-text">{result.provider} / {result.model}</div>
      </div>

      <div className="flex flex-col gap-4 p-3 text-xs">
        {/* Comparison Table */}
        {comparison_table.length > 0 && (
          <section>
            <h3 className="text-xs font-semibold text-teter-dark mb-2 uppercase tracking-wide">
              Comparison Table
            </h3>
            <div className="flex flex-col gap-1">
              {comparison_table.map((row) => (
                <ComparisonRow
                  key={row.id}
                  row={row}
                  selected={selections[row.id] ?? false}
                  onToggle={() => onToggle(row.id)}
                />
              ))}
            </div>
          </section>
        )}

        {/* Warnings */}
        {warnings.length > 0 && (
          <section>
            <h3 className="text-xs font-semibold text-red-700 mb-2 uppercase tracking-wide">
              Major Warnings
            </h3>
            <div className="flex flex-col gap-1">
              {warnings.map((warn) => (
                <WarningRow
                  key={warn.id}
                  item={warn}
                  selected={selections[warn.id] ?? false}
                  onToggle={() => onToggle(warn.id)}
                />
              ))}
            </div>
          </section>
        )}

        {/* Missing Info */}
        {missing_info.length > 0 && (
          <section>
            <h3 className="text-xs font-semibold text-yellow-700 mb-2 uppercase tracking-wide">
              Missing Info
            </h3>
            <div className="flex flex-col gap-1">
              {missing_info.map((miss) => (
                <WarningRow
                  key={miss.id}
                  item={miss}
                  selected={selections[miss.id] ?? false}
                  onToggle={() => onToggle(miss.id)}
                />
              ))}
            </div>
          </section>
        )}

        {/* Summary */}
        {summary && (
          <section>
            <h3 className="text-xs font-semibold text-teter-dark mb-1 uppercase tracking-wide">
              Summary
            </h3>
            <p className="text-teter-gray-text leading-relaxed">{summary}</p>
          </section>
        )}

        {comparison_table.length === 0 && warnings.length === 0 && missing_info.length === 0 && !summary && (
          <p className="text-teter-gray-text italic">No review items returned by this model.</p>
        )}
      </div>
    </div>
  )
}

function ComparisonRow({
  row,
  selected,
  onToggle,
}: {
  row: SubmittalComparisonItem
  selected: boolean
  onToggle: () => void
}) {
  return (
    <label
      className={`flex gap-2 p-2 rounded border border-teter-gray-mid cursor-pointer transition-opacity ${rowBg(row.severity, selected)}`}
    >
      <input
        type="checkbox"
        checked={selected}
        onChange={onToggle}
        className="mt-0.5 flex-shrink-0 accent-teter-orange"
      />
      <div className="flex flex-col gap-0.5 min-w-0">
        <div className="flex items-center gap-1 flex-wrap">
          <span className="font-semibold text-teter-dark truncate">{row.category} — {row.item}</span>
          {severityBadge(row.severity)}
          {!row.compliance && (
            <span className="text-red-600 font-bold text-xs">Non-compliant</span>
          )}
        </div>
        <div className="text-teter-gray-text">
          <span className="font-medium">Specified:</span> {row.specified_value}
          {' · '}
          <span className="font-medium">Submitted:</span> {row.submitted_value}
          {row.difference && row.difference !== 'N/A' && (
            <>{' · '}<span className="font-medium text-red-600">Δ {row.difference}</span></>
          )}
        </div>
        {row.comments && (
          <p className="text-teter-gray-text leading-relaxed">{row.comments}</p>
        )}
      </div>
    </label>
  )
}

function WarningRow({
  item,
  selected,
  onToggle,
}: {
  item: SubmittalWarningItem
  selected: boolean
  onToggle: () => void
}) {
  const isMajor = item.type === 'MAJOR_WARNING'
  return (
    <label
      className={`flex gap-2 p-2 rounded border cursor-pointer transition-opacity ${
        selected
          ? isMajor
            ? 'bg-red-50 border-red-200'
            : 'bg-yellow-50 border-yellow-200'
          : 'opacity-40 border-teter-gray-mid'
      }`}
    >
      <input
        type="checkbox"
        checked={selected}
        onChange={onToggle}
        className="mt-0.5 flex-shrink-0 accent-teter-orange"
      />
      <div className="flex flex-col gap-0.5">
        <span className={`font-semibold ${isMajor ? 'text-red-700' : 'text-yellow-700'}`}>
          {item.description}
        </span>
        {item.recommendation && (
          <span className="text-teter-gray-text">
            <span className="font-medium">Recommendation:</span> {item.recommendation}
          </span>
        )}
      </div>
    </label>
  )
}

// ---------------------------------------------------------------------------
// Main SubmittalReviewViewer
// ---------------------------------------------------------------------------

export function SubmittalReviewViewer() {
  const { taskId } = useParams<{ taskId: string }>()
  const navigate = useNavigate()

  const [task, setTask] = useState<TaskDetail | null>(null)
  const [reviewData, setReviewData] = useState<SubmittalReviewData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [selections, setSelections] = useState<Record<string, boolean>>({})
  const [acting, setActing] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [showReject, setShowReject] = useState(false)

  useEffect(() => {
    if (!taskId) return
    setLoading(true)
    Promise.all([getTask(taskId), getSubmittalReview(taskId)])
      .then(([t, r]) => {
        setTask(t)
        setReviewData(r)
        // Initialise selections: use saved selections if present, otherwise apply defaults
        const savedSels = r.selected_items
        if (Object.keys(savedSels).length > 0) {
          setSelections(savedSels)
        } else {
          setSelections(defaultSelected(r))
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [taskId])

  function toggleItem(id: string) {
    setSelections((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  async function handleApprove() {
    if (!taskId) return
    setActing(true)
    setActionError(null)
    try {
      await approveSubmittalReview(taskId, selections)
      navigate('/dashboard')
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : 'Approval failed.')
    } finally {
      setActing(false)
    }
  }

  async function handleReject(reason: RejectionReason, notes: string) {
    if (!taskId) return
    setActing(true)
    setActionError(null)
    try {
      await rejectTask(taskId, reason, notes || undefined)
      navigate('/dashboard')
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : 'Rejection failed.')
    } finally {
      setActing(false)
      setShowReject(false)
    }
  }

  async function handleEscalate() {
    if (!taskId) return
    setActing(true)
    setActionError(null)
    try {
      await escalateTask(taskId)
      navigate('/dashboard')
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : 'Escalation failed.')
    } finally {
      setActing(false)
    }
  }

  // ---------------------------------------------------------------------------
  // Loading / error states
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-teter-gray-text text-sm">Loading submittal review…</div>
      </div>
    )
  }

  if (error || !task || !reviewData) {
    return (
      <div className="max-w-content mx-auto px-4 py-8">
        <div className="bg-red-50 border border-red-200 rounded p-4 text-sm text-red-700">
          {error ?? 'Submittal review data not found.'}
        </div>
        <button className="btn-outline mt-4 text-sm" onClick={() => navigate('/dashboard')}>
          ← Back to Dashboard
        </button>
      </div>
    )
  }

  const selectedCount = Object.values(selections).filter(Boolean).length
  const { tier_1, tier_2, tier_3 } = reviewData.model_results

  return (
    <div className="flex flex-col h-[calc(100vh-3.5rem)]">
      {/* Top meta bar */}
      <div className="bg-teter-dark text-white px-4 py-2 flex items-center gap-4 text-sm border-b border-black/20 flex-shrink-0">
        <button
          className="text-white/50 hover:text-white transition-colors mr-1 text-base"
          onClick={() => navigate('/dashboard')}
          aria-label="Back to dashboard"
        >
          ←
        </button>
        <UrgencyBadge urgency={task.urgency} />
        <span className="font-semibold">
          SUBMITTAL{task.document_number ? ` — ${task.document_number}` : ''}
        </span>
        <span className="text-white/40">·</span>
        <span className="text-white/70">{task.project_number ?? 'Unknown project'}</span>
        {task.sender_name && (
          <>
            <span className="text-white/40">·</span>
            <span className="text-white/70">{task.sender_name}</span>
          </>
        )}
        <span className="ml-auto text-white/50 text-xs">
          {selectedCount} item{selectedCount !== 1 ? 's' : ''} selected for report
        </span>
      </div>

      {/* Instruction banner */}
      <div className="bg-teter-orange/10 border-b border-teter-orange/30 px-4 py-2 text-xs text-teter-dark flex-shrink-0">
        <strong>Review Mode:</strong> All 3 AI models have reviewed this submittal independently. Check or uncheck items to include them in the final report. Click <strong>Finalize &amp; Approve</strong> when ready.
      </div>

      {/* 3-column model output area */}
      <div className="flex flex-1 overflow-hidden">
        <div
          className="grid flex-1 overflow-hidden"
          style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }}
        >
          <ModelColumn
            tierKey="tier_1"
            result={tier_1}
            selections={selections}
            onToggle={toggleItem}
          />
          <ModelColumn
            tierKey="tier_2"
            result={tier_2}
            selections={selections}
            onToggle={toggleItem}
          />
          <ModelColumn
            tierKey="tier_3"
            result={tier_3}
            selections={selections}
            onToggle={toggleItem}
          />
        </div>
      </div>

      {/* Red Team Audit Trail */}
      {taskId && (
        <div className="flex-shrink-0 bg-white border-t border-teter-gray-mid px-4 py-3">
          <RedTeamAuditPanel taskId={taskId} />
        </div>
      )}

      {/* Bottom action bar */}
      <div className="flex-shrink-0 bg-white border-t border-teter-gray-mid px-4 py-3 flex items-center gap-3">
        {actionError && (
          <span className="text-sm text-red-600 mr-2">{actionError}</span>
        )}

        <div className="ml-auto flex items-center gap-3">
          <button
            className="btn-outline text-sm text-red-600 border-red-300 hover:bg-red-50"
            onClick={() => setShowReject(true)}
            disabled={acting}
          >
            Reject
          </button>
          <button
            className="btn-outline text-sm"
            onClick={handleEscalate}
            disabled={acting}
          >
            Escalate
          </button>
          <button
            className="btn-primary text-sm"
            onClick={handleApprove}
            disabled={acting}
          >
            {acting ? 'Saving…' : `Finalize & Approve (${selectedCount} items)`}
          </button>
        </div>
      </div>

      {/* Rejection dialog */}
      {showReject && (
        <RejectionDialog
          onConfirm={handleReject}
          onCancel={() => setShowReject(false)}
          loading={acting}
        />
      )}
    </div>
  )
}
