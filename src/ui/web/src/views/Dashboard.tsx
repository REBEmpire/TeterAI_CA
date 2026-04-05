import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listProjects, scanProjects, apiClient } from '../api/client'
import type { ScanProjectsResponse } from '../api/client'
import { UrgencyBadge } from '../components/common/UrgencyBadge'
import { STATUS_LABELS, STATUS_COLORS, DOC_TYPE_LABELS } from '../constants/statusLabels'
import { ConfidenceMeter } from '../components/common/ConfidenceMeter'
import { useTaskQueue } from '../hooks/useTaskQueue'
import { useAuth } from '../hooks/useAuth'
import type { DocumentType, ProjectSummary, TaskSummary, Urgency } from '../types'

const DOC_TYPES: DocumentType[] = [
  'RFI', 'SUBMITTAL', 'SUBSTITUTION', 'CHANGE_ORDER',
  'PAY_APP', 'MEETING_MINUTES', 'GENERAL', 'UNKNOWN',
]

/** Urgency → left accent border color */
const URGENCY_ACCENT: Record<string, string> = {
  HIGH: '#c62828',
  MEDIUM: '#e65100',
  LOW: '#bdbdbd',
  ESCALATED: '#6d28d9',
}

/** Pipeline statuses that haven't reached the human-review queue yet */
const PIPELINE_STATUSES = new Set([
  'PENDING_CLASSIFICATION',
  'CLASSIFYING',
  'ASSIGNED_TO_AGENT',
  'PROCESSING',
])

const PIPELINE_STATUS_LABEL: Record<string, string> = {
  PENDING_CLASSIFICATION: 'Queued',
  CLASSIFYING: 'Classifying…',
  ASSIGNED_TO_AGENT: 'Agent assigned',
  PROCESSING: 'Processing…',
}

function ageLabel(createdAt?: string): string {
  if (!createdAt) return ''
  const ms = Date.now() - new Date(createdAt).getTime()
  const mins = Math.floor(ms / 60000)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

function TaskCard({ task, index, onClick }: { task: TaskSummary; index: number; onClick: () => void }) {
  const isEscalated = task.status === 'ESCALATED_TO_HUMAN'
  const isPipeline = PIPELINE_STATUSES.has(task.status)
  const accentColor = isEscalated
    ? URGENCY_ACCENT.ESCALATED
    : isPipeline
    ? '#9e9e9e'
    : (URGENCY_ACCENT[task.urgency] ?? URGENCY_ACCENT.LOW)

  return (
    <div
      className="card p-4 pl-5 flex flex-col gap-2"
      style={{
        '--card-accent': accentColor,
        '--delay': `${index * 50}ms`,
        opacity: isPipeline ? 0.85 : 1,
      } as React.CSSProperties}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
      aria-label={`Open task ${task.document_number ?? task.task_id}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          {isPipeline ? (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-gray-100 text-gray-500 uppercase tracking-wide">
              {/* Spinning dot */}
              <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-pulse" />
              {STATUS_LABELS[task.status] || task.status}
            </span>
          ) : (
            <UrgencyBadge urgency={task.urgency} />
          )}
          {isEscalated && (
            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-purple-100 text-purple-700 uppercase tracking-wide">
              ⚠ Escalated
            </span>
          )}
          <span className="text-sm font-semibold text-teter-ink">
            {DOC_TYPE_LABELS[task.document_type || 'UNKNOWN'] || task.document_type}
            {task.document_number ? ` — ${task.document_number}` : ''}
          </span>
        </div>

        <div className="text-xs text-teter-gray-text whitespace-nowrap font-medium">
          {ageLabel(task.created_at)}
        </div>
      </div>

      <div className="flex items-center gap-2 text-sm">
        {task.sender_name && (
          <span className="font-semibold text-teter-ink">{task.sender_name}</span>
        )}
        {task.sender_name && task.project_number && (
          <span className="text-teter-gray-mid">·</span>
        )}
        {task.project_number && (
          <span className="text-teter-gray-text font-medium">{task.project_number}</span>
        )}
      </div>

      {task.subject && (
        <p className="text-sm text-teter-gray-text truncate">{task.subject}</p>
      )}

      <div className="flex items-center justify-between pt-1">
        {task.classification_confidence !== undefined && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-teter-gray-text font-medium">Confidence</span>
            <ConfidenceMeter score={task.classification_confidence} showBar={false} />
          </div>
        )}
        {task.response_due && (
          <span className="text-xs text-teter-gray-text ml-auto font-medium">
            Due {new Date(task.response_due).toLocaleDateString()}
          </span>
        )}
      </div>
    </div>
  )
}

export function Dashboard() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [filterProject, setFilterProject] = useState('')
  const [filterDocType, setFilterDocType] = useState('')
  const [filterUrgency, setFilterUrgency] = useState('')
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [scanning, setScanning] = useState(false)
  const [scanResult, setScanResult] = useState<ScanProjectsResponse | null>(null)

  useEffect(() => {
    listProjects().then(setProjects).catch(() => {/* non-critical */})
  }, [])

  async function handleScanFromDashboard() {
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

  const { tasks, loading, error } = useTaskQueue({
    project: filterProject || undefined,
    docType: filterDocType || undefined,
    urgency: filterUrgency || undefined,
  })

  const prevCountRef = useRef(0)

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

  // Stats derived from task list
  const reviewCount = tasks.filter(t => !PIPELINE_STATUSES.has(t.status)).length
  const highCount = tasks.filter(t => t.urgency === 'HIGH').length
  const dueToday = tasks.filter(t => {
    if (!t.response_due) return false
    const d = new Date(t.response_due)
    const now = new Date()
    return d.toDateString() === now.toDateString()
  }).length

  return (
    <div className="max-w-wide mx-auto px-4 py-6">
      {/* Page header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-xl font-semibold text-teter-ink tracking-tight">Action Dashboard</h1>
          <p className="text-sm text-teter-gray-text mt-0.5 font-medium">
            {loading
              ? 'Loading…'
              : reviewCount > 0
              ? `${reviewCount} item${reviewCount !== 1 ? 's' : ''} pending review${tasks.length > reviewCount ? `, ${tasks.length - reviewCount} in pipeline` : ''}`
              : tasks.length > 0
              ? `${tasks.length} item${tasks.length !== 1 ? 's' : ''} in pipeline`
              : 'No active items'}
          </p>
        </div>

        {/* Orange accent line */}
        <div className="hidden sm:block w-[3px] h-9 bg-teter-orange rounded-sm" />
      </div>

      {/* Stats row — only shown when data is loaded and there are tasks */}
      {!loading && tasks.length > 0 && (
        <div className="flex gap-3 mb-5">
          <div className="stat-chip">
            <span className="text-xl font-bold text-teter-ink leading-none">{reviewCount}</span>
            <span className="text-[10px] uppercase tracking-widest text-teter-gray-text font-semibold mt-1.5">For Review</span>
          </div>
          {tasks.length > reviewCount && (
            <div className="stat-chip">
              <span className="text-xl font-bold text-gray-400 leading-none">{tasks.length - reviewCount}</span>
              <span className="text-[10px] uppercase tracking-widest text-teter-gray-text font-semibold mt-1.5">In Pipeline</span>
            </div>
          )}
          <div className="stat-chip">
            <span className="text-xl font-bold text-urgency-high leading-none">{highCount}</span>
            <span className="text-[10px] uppercase tracking-widest text-teter-gray-text font-semibold mt-1.5">High</span>
          </div>
          <div className="stat-chip">
            <span className="text-xl font-bold text-teter-orange leading-none">{dueToday}</span>
            <span className="text-[10px] uppercase tracking-widest text-teter-gray-text font-semibold mt-1.5">Due Today</span>
          </div>
        </div>
      )}

      {/* Filter bar */}
      <div className="flex flex-wrap gap-3 mb-5">
        <select
          className="select"
          value={filterProject}
          onChange={(e) => setFilterProject(e.target.value)}
          aria-label="Filter by project"
        >
          <option value="">All Projects</option>
          {projects.map((p) => (
            <option key={p.project_id} value={p.project_number}>
              {p.project_number} — {p.name}
            </option>
          ))}
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
        <div className="bg-red-50 border border-red-200 rounded-[10px] p-4 text-sm text-red-700 mb-4">
          Error loading tasks: {error.message}
        </div>
      )}

      {loading ? (
        <div className="flex flex-col gap-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="bg-white rounded-[10px] border border-teter-gray-mid/60 p-4 animate-pulse shadow-card">
              <div className="h-4 bg-teter-gray rounded w-1/3 mb-3" />
              <div className="h-3 bg-teter-gray rounded w-2/3 mb-2" />
              <div className="h-3 bg-teter-gray rounded w-1/2" />
            </div>
          ))}
        </div>
      ) : tasks.length === 0 ? (
        projects.length === 0 ? (
          <div className="text-center py-20 text-teter-gray-text">
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-white border-2 border-teter-orange/30 shadow-stat mb-4">
              <svg className="w-7 h-7 text-teter-orange" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
            </div>
            <p className="font-semibold text-teter-ink text-base">No projects configured</p>
            <p className="text-sm mt-1 mb-6 max-w-sm mx-auto">
              {user?.role === 'ADMIN'
                ? 'Create a new project or scan your Projects folder to import existing ones.'
                : 'No projects available. Contact your administrator to set up a project.'}
            </p>
            {user?.role === 'ADMIN' && (
              <div className="flex items-center justify-center gap-3">
                <button className="btn-primary text-sm" onClick={() => navigate('/admin')}>
                  + New Project
                </button>
                <button className="btn-outline text-sm" onClick={handleScanFromDashboard} disabled={scanning}>
                  {scanning ? 'Scanning\u2026' : 'Scan Folders'}
                </button>
              </div>
            )}
            {scanResult && (
              <div className="mt-4 text-sm">
                {scanResult.imported.length > 0 && (
                  <span className="text-green-700 font-semibold">{scanResult.imported.length} project(s) imported</span>
                )}
                {scanResult.imported.length === 0 && scanResult.errors.length === 0 && (
                  <span>No new projects found in the Projects root folder.</span>
                )}
                {scanResult.errors.length > 0 && (
                  <span className="text-red-600">{scanResult.errors.join('; ')}</span>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="text-center py-20 text-teter-gray-text">
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-white border-2 border-teter-gray-mid shadow-stat mb-4">
              <svg className="w-7 h-7 text-teter-orange" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <p className="font-semibold text-teter-ink text-base">All caught up</p>
            <p className="text-sm mt-1">No items pending review.</p>
          </div>
        )
      ) : (
        <div className="flex flex-col gap-3">
          {tasks.map((task, index) => (
            <TaskCard
              key={task.task_id}
              task={task}
              index={index}
              onClick={() =>
                task.document_type === 'SUBMITTAL'
                  ? navigate(`/tasks/${task.task_id}/submittal`)
                  : navigate(`/tasks/${task.task_id}`)
              }
            />
          ))}
        </div>
      )}
    </div>
  )
}

function ErrorTaskCard({ task, onRetry }: { task: any, onRetry: () => void }) {
  const [retrying, setRetrying] = useState(false)

  const handleRetry = async () => {
    setRetrying(true)
    try {
      await apiClient.retryTask(task.task_id)
      onRetry()
    } catch (e) {
      console.error(e)
      setRetrying(false)
    }
  }

  return (
    <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex flex-col gap-3 shadow-sm">
      <div className="flex justify-between items-start">
        <h4 className="text-sm font-semibold text-red-900 truncate pr-2" title={task.subject || 'Unknown Document'}>
          {task.subject || 'Unknown Document'}
        </h4>
        <span className="text-[10px] bg-red-100 text-red-800 px-2 py-0.5 rounded uppercase tracking-wider whitespace-nowrap">
          Processing Failed
        </span>
      </div>

      <p className="text-xs text-red-700 font-mono bg-red-100/50 p-2 rounded line-clamp-2">
        {task.error_message || 'Unknown error occurred'}
      </p>

      <div className="flex justify-between items-center mt-auto pt-2">
        <span className="text-xs text-red-500">
          Failed: {new Date(task.updated_at).toLocaleTimeString()}
        </span>
        <button
          onClick={handleRetry}
          disabled={retrying}
          className="text-xs bg-white text-red-700 hover:bg-red-50 hover:text-red-800 border border-red-200 px-3 py-1.5 rounded transition-colors disabled:opacity-50"
        >
          {retrying ? 'Retrying...' : 'Retry Processing'}
        </button>
      </div>
    </div>
  )
}
