import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { approveTask, dispatchNow, escalateTask, getTask, rejectTask } from '../api/client'
import { ConfidenceMeter } from '../components/common/ConfidenceMeter'
import { UrgencyBadge } from '../components/common/UrgencyBadge'
import { STATUS_LABELS, DOC_TYPE_LABELS } from '../constants/statusLabels'
import { RejectionDialog } from '../components/modals/RejectionDialog'
import { ThoughtChainModal } from '../components/modals/ThoughtChainModal'
import { RedTeamAuditPanel } from '../components/review/RedTeamAuditPanel'
import type { RejectionReason, TaskDetail } from '../types'

type RightTab = 'email' | `attachment_${number}` | `spec_${number}` | `drawing_${number}`

const PIPELINE_STATUSES = new Set([
  'PENDING_CLASSIFICATION',
  'CLASSIFYING',
  'ASSIGNED_TO_AGENT',
  'PROCESSING',
])

const PIPELINE_STATUS_LABEL: Record<string, string> = {
  PENDING_CLASSIFICATION: 'Queued — waiting for classification',
  CLASSIFYING: 'Classifying document…',
  ASSIGNED_TO_AGENT: 'Assigned to agent — processing will begin shortly',
  PROCESSING: 'Agent is processing this document…',
}

export function SplitViewer() {
  const { taskId } = useParams<{ taskId: string }>()
  const navigate = useNavigate()

  const [task, setTask] = useState<TaskDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Draft editing
  const [draftContent, setDraftContent] = useState('')
  const [isEditing, setIsEditing] = useState(false)

  // Right panel tabs
  const [activeTab, setActiveTab] = useState<RightTab>('email')

  // Modals
  const [showReject, setShowReject] = useState(false)
  const [showThoughtChain, setShowThoughtChain] = useState(false)

  // Action states
  const [acting, setActing] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [deliveredPath, setDeliveredPath] = useState<string | null>(null)

  // Pipeline processing state
  const [dispatching, setDispatching] = useState(false)
  const [dispatchMsg, setDispatchMsg] = useState<string | null>(null)

  useEffect(() => {
    if (!taskId) return
    setLoading(true)
    getTask(taskId)
      .then((t) => {
        setTask(t)
        setDraftContent(t.draft_content ?? '')
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [taskId])

  async function handleApprove() {
    if (!taskId) return
    setActing(true)
    setActionError(null)
    try {
      const edited = isEditing && draftContent !== task?.draft_content
        ? draftContent
        : undefined
      const result = await approveTask(taskId, edited)
      if (result?.delivered_path) {
        setDeliveredPath(result.delivered_path)
      } else {
        navigate('/dashboard')
      }
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

  async function handleProcessNow() {
    setDispatching(true)
    setDispatchMsg(null)
    try {
      const result = await dispatchNow()
      const msg = result.dispatched > 0 || result.agents_run > 0
        ? `Processing started — ${result.dispatched} classified, ${result.agents_run} advanced`
        : 'No pending items found. The task may already be processing.'
      setDispatchMsg(msg)
      // Refresh the task after a short delay to pick up the new status
      setTimeout(() => {
        if (!taskId) return
        getTask(taskId).then((t) => {
          setTask(t)
          setDraftContent(t.draft_content ?? '')
        }).catch(() => {/* ignore refresh errors */})
        setDispatchMsg(null)
      }, 2500)
    } catch (e: unknown) {
      setDispatchMsg(e instanceof Error ? e.message : 'Dispatch failed.')
    } finally {
      setDispatching(false)
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
  // Render helpers
  // ---------------------------------------------------------------------------

  function renderRightPanel() {
    if (!task) return null

    if (activeTab === 'email') {
      const email = task.source_email as Record<string, unknown> | undefined
      return (
        <div className="p-4 overflow-auto h-full">
          {email ? (
            <div className="flex flex-col gap-3 text-sm">
              {!!email['from'] && (
                <div>
                  <span className="label">From</span>
                  <p className="text-teter-dark">{String(email['from'])}</p>
                </div>
              )}
              {!!email['subject'] && (
                <div>
                  <span className="label">Subject</span>
                  <p className="text-teter-dark font-semibold">{String(email['subject'])}</p>
                </div>
              )}
              {!!email['date'] && (
                <div>
                  <span className="label">Date</span>
                  <p className="text-teter-gray-text">{String(email['date'])}</p>
                </div>
              )}
              <hr className="border-teter-gray-mid" />
              <div className="whitespace-pre-wrap text-teter-dark leading-relaxed">
                {String(email['body'] ?? '')}
              </div>
            </div>
          ) : (
            <p className="text-teter-gray-text text-sm">No email data available.</p>
          )}
        </div>
      )
    }

    if (activeTab.startsWith('attachment_')) {
      const idx = parseInt(activeTab.split('_')[1], 10)
      const att = task.attachments[idx]
      if (!att) return null
      return (
        <iframe
          className="w-full h-full border-0"
          src={`/api/v1/tasks/${task.task_id}/source/files/${att.file_id}`}
          title={att.filename}
        />
      )
    }

    if (activeTab.startsWith('spec_') || activeTab.startsWith('drawing_')) {
      const [type, idx] = activeTab.split('_')
      const list = type === 'spec' ? task.referenced_specs : task.referenced_drawings
      const item = (list as Array<Record<string, string>> | undefined)?.[parseInt(idx, 10)]
      if (!item) return null
      return (
        <iframe
          className="w-full h-full border-0"
          src={`/api/v1/tasks/${task.task_id}/source/files/${item['file_id']}`}
          title={item['name'] ?? 'Document'}
        />
      )
    }

    return null
  }

  // ---------------------------------------------------------------------------
  // Loading / error states
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-teter-gray-text text-sm">Loading task…</div>
      </div>
    )
  }

  if (error || !task) {
    return (
      <div className="max-w-content mx-auto px-4 py-8">
        <div className="bg-red-50 border border-red-200 rounded p-4 text-sm text-red-700">
          {error ?? 'Task not found.'}
        </div>
        <button className="btn-outline mt-4 text-sm" onClick={() => navigate('/dashboard')}>
          ← Back to Dashboard
        </button>
      </div>
    )
  }

  // ---------------------------------------------------------------------------
  // Main split-screen layout
  // ---------------------------------------------------------------------------

  const specRefs = (task.referenced_specs as Array<Record<string, string>> | undefined) ?? []
  const drawingRefs = (task.referenced_drawings as Array<Record<string, string>> | undefined) ?? []

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
          {task.document_type}
          {task.document_number ? ` — ${task.document_number}` : ''}
        </span>
        <span className="text-white/40">·</span>
        <span className="text-white/70">{task.project_number ?? 'Unknown project'}</span>
        {task.sender_name && (
          <>
            <span className="text-white/40">·</span>
            <span className="text-white/70">{task.sender_name}</span>
          </>
        )}
      </div>

      {/* Split panels */}
      <div className="flex flex-1 overflow-hidden">
        {/* ── LEFT: Agent Draft ─────────────────────────────────── */}
        <div className="w-1/2 flex flex-col border-r border-teter-gray-mid overflow-hidden">
          {/* Left header */}
          <div className="px-4 py-3 border-b border-teter-gray-mid bg-teter-gray flex-shrink-0">
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-2">
                <span className="w-0.5 h-5 bg-teter-orange rounded-sm" />
                <span className="text-sm font-semibold text-teter-dark">Agent Draft</span>
              </div>
              {task.agent_id && (
                <span className="text-xs text-teter-gray-text">
                  {task.agent_id} {task.agent_version ? `v${task.agent_version}` : ''}
                </span>
              )}
            </div>
            {task.confidence_score !== undefined && (
              <div className="flex items-center gap-2 mt-1">
                <span className="text-xs text-teter-gray-text">Confidence</span>
                <ConfidenceMeter score={task.confidence_score} />
              </div>
            )}
          </div>

          {/* Draft text area */}
          <div className="flex-1 overflow-auto p-4">
            {isEditing ? (
              <textarea
                className="w-full h-full input resize-none font-mono text-sm leading-relaxed"
                value={draftContent}
                onChange={(e) => setDraftContent(e.target.value)}
                spellCheck
                aria-label="Edit agent draft"
              />
            ) : (
              <pre className="whitespace-pre-wrap text-sm text-teter-dark leading-relaxed font-sans">
                {draftContent || <span className="text-teter-gray-text italic">No draft content.</span>}
              </pre>
            )}
          </div>

          {/* Citations */}
          {task.citations.length > 0 && (
            <div className="px-4 py-3 border-t border-teter-gray-mid bg-white flex-shrink-0">
              <p className="label mb-1">Citations</p>
              <div className="flex flex-wrap gap-1">
                {task.citations.map((cite, i) => (
                  <button
                    key={i}
                    className="text-xs px-2 py-0.5 rounded border border-teter-orange/40 text-teter-orange hover:bg-teter-orange/10 transition-colors"
                    onClick={() => {
                      // Jump to matching spec tab if it exists
                      const specIdx = specRefs.findIndex(
                        (s) => s['section'] === cite || s['name'] === cite,
                      )
                      if (specIdx >= 0) setActiveTab(`spec_${specIdx}`)
                    }}
                  >
                    {cite}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Edit toggle */}
          <div className="px-4 py-2 border-t border-teter-gray-mid bg-white flex-shrink-0">
            <button
              className="btn-outline text-sm"
              onClick={() => setIsEditing((v) => !v)}
            >
              {isEditing ? 'Preview Draft' : 'Edit Draft'}
            </button>
          </div>

          {/* Red Team Audit Trail */}
          {taskId && (
            <div className="px-4 py-3 border-t border-teter-gray-mid bg-white flex-shrink-0">
              <RedTeamAuditPanel taskId={taskId} />
            </div>
          )}
        </div>

        {/* ── RIGHT: Source Documents ────────────────────────────── */}
        <div className="w-1/2 flex flex-col overflow-hidden">
          {/* Tab bar */}
          <div className="border-b border-teter-gray-mid bg-white flex-shrink-0 overflow-x-auto">
            <div className="flex items-end px-4 gap-1 min-w-max">
              <TabButton
                active={activeTab === 'email'}
                onClick={() => setActiveTab('email')}
              >
                Original Email
              </TabButton>
              {task.attachments.map((att, i) => (
                <TabButton
                  key={att.file_id}
                  active={activeTab === `attachment_${i}`}
                  onClick={() => setActiveTab(`attachment_${i}`)}
                >
                  {att.filename}
                </TabButton>
              ))}
              {specRefs.map((spec, i) => (
                <TabButton
                  key={i}
                  active={activeTab === `spec_${i}`}
                  onClick={() => setActiveTab(`spec_${i}`)}
                >
                  {spec['section'] ?? spec['name'] ?? `Spec ${i + 1}`}
                </TabButton>
              ))}
              {drawingRefs.map((drawing, i) => (
                <TabButton
                  key={i}
                  active={activeTab === `drawing_${i}`}
                  onClick={() => setActiveTab(`drawing_${i}`)}
                >
                  {drawing['sheet'] ?? drawing['name'] ?? `Sheet ${i + 1}`}
                </TabButton>
              ))}
            </div>
          </div>

          {/* Panel content */}
          <div className="flex-1 overflow-hidden bg-white">
            {renderRightPanel()}
          </div>
        </div>
      </div>

      {/* ── Pipeline status banner (shown while task is still being processed) */}
      {PIPELINE_STATUSES.has(task.status) && (
        <div className="flex-shrink-0 bg-amber-50 border-t border-amber-200 px-4 py-2.5 flex items-center gap-3 text-sm">
          {/* Animated dot */}
          <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse shrink-0" />
          <span className="text-amber-800 font-medium">
            {STATUS_LABELS[task.status] || task.status}
          </span>
          <div className="ml-auto flex items-center gap-3">
            {dispatchMsg && (
              <span className="text-amber-700 text-xs">{dispatchMsg}</span>
            )}
            <button
              className="btn-outline text-xs border-amber-400 text-amber-700 hover:bg-amber-100"
              onClick={handleProcessNow}
              disabled={dispatching}
            >
              {dispatching ? 'Processing…' : 'Process Now'}
            </button>
          </div>
        </div>
      )}

      {/* ── Bottom action bar ─────────────────────────────────────── */}
      <div className="flex-shrink-0 bg-white border-t border-teter-gray-mid px-4 py-3 flex items-center gap-3">
        {actionError && (
          <span className="text-sm text-red-600 mr-2">{actionError}</span>
        )}

        <button
          className="btn-outline text-sm"
          onClick={() => setShowThoughtChain(true)}
          disabled={acting || PIPELINE_STATUSES.has(task.status)}
        >
          Thought Chain
        </button>

        <div className="ml-auto flex items-center gap-3">
          <button
            className="btn-outline text-sm text-red-600 border-red-300 hover:bg-red-50"
            onClick={() => setShowReject(true)}
            disabled={acting || PIPELINE_STATUSES.has(task.status)}
          >
            Reject
          </button>
          <button
            className="btn-outline text-sm"
            onClick={handleEscalate}
            disabled={acting || PIPELINE_STATUSES.has(task.status)}
          >
            Escalate
          </button>
          <button
            className="btn-primary text-sm"
            onClick={handleApprove}
            disabled={acting || PIPELINE_STATUSES.has(task.status)}
          >
            {acting ? 'Saving…' : isEditing ? 'Save & Approve' : 'Approve'}
          </button>
        </div>
      </div>

      {/* Delivery confirmation banner */}
      {deliveredPath && (
        <div className="flex-shrink-0 bg-green-50 border-t border-green-200 px-4 py-3 flex items-center gap-3 text-sm">
          <span className="text-green-700 font-medium">Delivered to:</span>
          <span className="text-green-800 font-mono text-xs truncate flex-1" title={deliveredPath}>
            {deliveredPath}
          </span>
          {(window as typeof window & { electronAPI?: { openFolder?: (p: string) => void } }).electronAPI?.openFolder ? (
            <button
              className="btn-outline text-xs shrink-0"
              onClick={() =>
                (window as typeof window & { electronAPI?: { openFolder?: (p: string) => void } }).electronAPI!.openFolder!(deliveredPath)
              }
            >
              Open Folder
            </button>
          ) : (
            <button
              className="btn-outline text-xs shrink-0"
              onClick={() => navigator.clipboard.writeText(deliveredPath)}
            >
              Copy Path
            </button>
          )}
          <button className="btn-primary text-xs shrink-0" onClick={() => navigate('/dashboard')}>
            Back to Dashboard
          </button>
        </div>
      )}

      {/* Modals */}
      {showReject && (
        <RejectionDialog
          onConfirm={handleReject}
          onCancel={() => setShowReject(false)}
          loading={acting}
        />
      )}
      {showThoughtChain && (
        <ThoughtChainModal
          data={task}
          onClose={() => setShowThoughtChain(false)}
        />
      )}
    </div>
  )
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      className={`px-3 py-2.5 text-xs font-semibold whitespace-nowrap transition-colors ${
        active ? 'tab-active' : 'tab-inactive'
      }`}
      onClick={onClick}
    >
      {children}
    </button>
  )
}
