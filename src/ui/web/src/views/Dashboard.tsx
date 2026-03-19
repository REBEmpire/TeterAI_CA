import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { UrgencyBadge } from '../components/common/UrgencyBadge'
import { ConfidenceMeter } from '../components/common/ConfidenceMeter'
import { useTaskQueue } from '../hooks/useTaskQueue'
import type { DocumentType, TaskSummary, Urgency } from '../types'

const DOC_TYPES: DocumentType[] = [
  'RFI', 'SUBMITTAL', 'SUBSTITUTION', 'CHANGE_ORDER',
  'PAY_APP', 'MEETING_MINUTES', 'GENERAL', 'UNKNOWN',
]

function ageLabel(createdAt?: string): string {
  if (!createdAt) return ''
  const ms = Date.now() - new Date(createdAt).getTime()
  const mins = Math.floor(ms / 60000)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

function TaskCard({ task, onClick }: { task: TaskSummary; onClick: () => void }) {
  const isEscalated = task.status === 'ESCALATED_TO_HUMAN'

  return (
    <div
      className="card p-4 flex flex-col gap-2"
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
      aria-label={`Open task ${task.document_number ?? task.task_id}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          <UrgencyBadge urgency={task.urgency} />
          {isEscalated && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-purple-100 text-purple-700 uppercase">
              ⚠ Escalated
            </span>
          )}
          <span className="text-sm font-semibold text-teter-dark">
            {task.document_type}
            {task.document_number ? ` — ${task.document_number}` : ''}
          </span>
        </div>

        <div className="text-xs text-teter-gray-text whitespace-nowrap">
          {ageLabel(task.created_at)}
        </div>
      </div>

      <div className="flex items-center gap-2 text-sm text-teter-dark">
        {task.sender_name && (
          <span className="font-semibold">{task.sender_name}</span>
        )}
        {task.sender_name && task.project_number && (
          <span className="text-teter-gray-text">·</span>
        )}
        {task.project_number && (
          <span className="text-teter-gray-text">{task.project_number}</span>
        )}
      </div>

      {task.subject && (
        <p className="text-sm text-teter-gray-text truncate">{task.subject}</p>
      )}

      <div className="flex items-center justify-between pt-1">
        {task.classification_confidence !== undefined && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-teter-gray-text">Confidence</span>
            <ConfidenceMeter score={task.classification_confidence} showBar={false} />
          </div>
        )}
        {task.response_due && (
          <span className="text-xs text-teter-gray-text ml-auto">
            Due {new Date(task.response_due).toLocaleDateString()}
          </span>
        )}
      </div>
    </div>
  )
}

export function Dashboard() {
  const navigate = useNavigate()
  const [filterProject, setFilterProject] = useState('')
  const [filterDocType, setFilterDocType] = useState('')
  const [filterUrgency, setFilterUrgency] = useState('')

  const { tasks, loading, error } = useTaskQueue({
    project: filterProject || undefined,
    docType: filterDocType || undefined,
    urgency: filterUrgency || undefined,
  })

  // Update tab title with unread count
  useEffect(() => {
    document.title = tasks.length > 0 ? `(${tasks.length}) TeterAI` : 'TeterAI'
  }, [tasks.length])

  // Web push notification on new task (if permission granted)
  useEffect(() => {
    if (!('Notification' in window)) return
    if (Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }, [])

  const prevCountRef = { current: 0 }
  useEffect(() => {
    const prev = prevCountRef.current
    if (tasks.length > prev && prev > 0 && Notification.permission === 'granted') {
      const newest = tasks[0]
      new Notification('TeterAI — New item ready for review', {
        body: `${newest.document_type}${newest.document_number ? ` ${newest.document_number}` : ''} — ${newest.project_number ?? 'Unknown project'}`,
        icon: '/teter-icon.svg',
      })
    }
    prevCountRef.current = tasks.length
  }, [tasks])

  return (
    <div className="max-w-wide mx-auto px-4 py-6">
      {/* Page header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-teter-dark">Action Dashboard</h1>
          <p className="text-sm text-teter-gray-text mt-0.5">
            {loading
              ? 'Loading…'
              : `${tasks.length} item${tasks.length !== 1 ? 's' : ''} pending review`}
          </p>
        </div>

        {/* Orange accent line matching teterae.com section headers */}
        <div className="hidden sm:block w-1 h-8 bg-teter-orange rounded-sm" />
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap gap-3 mb-5">
        <select
          className="select"
          value={filterProject}
          onChange={(e) => setFilterProject(e.target.value)}
          aria-label="Filter by project"
        >
          <option value="">All Projects</option>
          {/* Projects are populated dynamically; placeholder options shown */}
        </select>

        <select
          className="select"
          value={filterDocType}
          onChange={(e) => setFilterDocType(e.target.value)}
          aria-label="Filter by document type"
        >
          <option value="">All Types</option>
          {DOC_TYPES.map((t) => (
            <option key={t} value={t}>{t.replace('_', ' ')}</option>
          ))}
        </select>

        <select
          className="select"
          value={filterUrgency}
          onChange={(e) => setFilterUrgency(e.target.value)}
          aria-label="Filter by urgency"
        >
          <option value="">All Urgency</option>
          <option value="HIGH">HIGH</option>
          <option value="MEDIUM">MEDIUM</option>
          <option value="LOW">LOW</option>
        </select>

        {(filterProject || filterDocType || filterUrgency) && (
          <button
            className="btn-outline text-sm"
            onClick={() => {
              setFilterProject('')
              setFilterDocType('')
              setFilterUrgency('')
            }}
          >
            Clear filters
          </button>
        )}
      </div>

      {/* Task list */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded p-4 text-sm text-red-700 mb-4">
          Error loading tasks: {error.message}
        </div>
      )}

      {loading ? (
        <div className="flex flex-col gap-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="card p-4 animate-pulse">
              <div className="h-4 bg-teter-gray rounded w-1/3 mb-2" />
              <div className="h-3 bg-teter-gray rounded w-2/3" />
            </div>
          ))}
        </div>
      ) : tasks.length === 0 ? (
        <div className="text-center py-16 text-teter-gray-text">
          <div className="text-4xl mb-3">✓</div>
          <p className="font-semibold text-teter-dark">All caught up</p>
          <p className="text-sm mt-1">No items pending review.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {tasks.map((task) => (
            <TaskCard
              key={task.task_id}
              task={task}
              onClick={() => navigate(`/tasks/${task.task_id}`)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
