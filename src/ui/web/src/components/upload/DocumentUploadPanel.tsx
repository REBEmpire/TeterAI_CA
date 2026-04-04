/**
 * DocumentUploadPanel — drag-and-drop document upload UI for Phase C.
 *
 * Sends a multipart POST to /api/v1/upload/document and displays live
 * status feedback. Matches the Teter brand palette (dark #313131, orange #d06f1a).
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Link } from 'react-router-dom'
import { listProjects, uploadDocument } from '../../api/client'
import type { ProjectSummary } from '../../types'

// ---------------------------------------------------------------------------
// Tool type options
// ---------------------------------------------------------------------------

const TOOL_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: 'auto',      label: 'Let the AI decide' },
  { value: 'rfi',       label: 'Request for Information (RFI)' },
  { value: 'submittal', label: 'Submittal' },
  { value: 'cost',      label: 'Cost Analysis / PCO' },
  { value: 'payapp',    label: 'Pay Application' },
  { value: 'schedule',  label: 'Schedule' },
]

const ACCEPTED_EXTS = '.pdf,.docx,.xer,.xml'

// ---------------------------------------------------------------------------
// Dropzone sub-component
// ---------------------------------------------------------------------------

interface DropzoneProps {
  label: string
  hint: string
  multiple?: boolean
  files: File[]
  onFiles: (files: File[]) => void
  disabled?: boolean
}

function Dropzone({ label, hint, multiple = false, files, onFiles, disabled }: DropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragging(false)
    if (disabled) return
    const dropped = Array.from(e.dataTransfer.files)
    onFiles(multiple ? dropped : dropped.slice(0, 1))
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(e.target.files ?? [])
    onFiles(multiple ? selected : selected.slice(0, 1))
    // Reset so the same file can be re-selected if cleared
    e.target.value = ''
  }

  return (
    <div>
      <span className="label">{label}</span>
      <div
        onClick={() => !disabled && inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); if (!disabled) setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={`
          mt-1 border-2 border-dashed rounded-lg p-5 text-center transition-colors duration-150
          ${disabled ? 'opacity-50 cursor-not-allowed bg-teter-gray border-teter-gray-mid' : 'cursor-pointer'}
          ${dragging && !disabled
            ? 'border-teter-orange bg-orange-50'
            : 'border-teter-gray-mid hover:border-teter-orange hover:bg-orange-50/30'}
        `}
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-label={label}
        onKeyDown={(e) => e.key === 'Enter' && !disabled && inputRef.current?.click()}
      >
        {/* Upload icon (inline SVG — no icon library installed) */}
        <svg
          className={`mx-auto mb-2 h-8 w-8 ${dragging ? 'text-teter-orange' : 'text-teter-gray-mid'}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1.5}
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round"
            d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
        </svg>

        {files.length === 0 ? (
          <>
            <p className="text-sm text-teter-dark font-medium">
              {dragging ? 'Drop file here' : 'Drop file here or click to browse'}
            </p>
            <p className="text-xs text-teter-gray-text mt-1">{hint}</p>
          </>
        ) : (
          <ul className="text-sm text-teter-dark space-y-0.5">
            {files.map((f) => (
              <li key={f.name} className="flex items-center justify-center gap-1.5">
                {/* Document icon */}
                <svg className="h-4 w-4 text-teter-orange shrink-0" fill="none" viewBox="0 0 24 24"
                  stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round"
                    d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                </svg>
                <span className="font-medium truncate max-w-xs">{f.name}</span>
                <span className="text-teter-gray-text text-xs whitespace-nowrap">
                  ({(f.size / 1024).toFixed(0)} KB)
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {files.length > 0 && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onFiles([]) }}
          className="mt-1 text-xs text-teter-gray-text hover:text-red-600 transition-colors"
          disabled={disabled}
        >
          Clear {multiple ? 'files' : 'file'}
        </button>
      )}

      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED_EXTS}
        multiple={multiple}
        className="sr-only"
        onChange={handleChange}
        tabIndex={-1}
        aria-hidden="true"
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Upload result type
// ---------------------------------------------------------------------------

interface UploadResult {
  task_id: string
  tool_type: string
  status: string
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export function DocumentUploadPanel() {
  const navigate = useNavigate()
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [projectSearch, setProjectSearch] = useState('')
  const [showProjectDropdown, setShowProjectDropdown] = useState(false)

  useEffect(() => {
    listProjects().then(setProjects).catch(() => {})
  }, [])

  const [projectId, setProjectId] = useState('')
  const [toolType, setToolType] = useState('auto')
  const [primaryFiles, setPrimaryFiles] = useState<File[]>([])
  const [supportingFiles, setSupportingFiles] = useState<File[]>([])

  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<UploadResult | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    listProjects()
      .then(setProjects)
      .catch(() => {/* non-critical */})
  }, [])

  const isReady = primaryFiles.length > 0 && projectId !== ''

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!isReady || submitting) return

    setSubmitting(true)
    setError('')
    setResult(null)

    try {
      const data = await uploadDocument(
        primaryFiles[0],
        supportingFiles,
        projectId,
        toolType === 'auto' ? undefined : toolType,
      )
      setResult(data)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Upload failed.')
    } finally {
      setSubmitting(false)
    }
  }

  function handleReset() {
    setResult(null)
    setError('')
    setPrimaryFiles([])
    setSupportingFiles([])
    setProjectId('')
    setToolType('auto')
  }

  // ---------------------------------------------------------------------------
  // Success state
  // ---------------------------------------------------------------------------
  if (result) {
    return (
      <div className="max-w-content mx-auto px-4 py-8">
        <div className="card p-6 text-center">
          {/* Check circle icon */}
          <svg
            className="mx-auto h-14 w-14 text-green-600 mb-4"
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round"
              d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <h2 className="text-lg font-semibold text-teter-dark mb-1">
            Document queued for review
          </h2>
          <p className="text-sm text-teter-gray-text mb-4">
            Tool type:{' '}
            <span className="font-semibold text-teter-dark capitalize">{result.tool_type}</span>
          </p>
          <div className="flex items-center justify-center gap-3">
            <Link
              to={`/tasks/${result.task_id}`}
              className="btn-primary text-sm"
            >
              View task in dashboard
            </Link>
            <button
              type="button"
              onClick={handleReset}
              className="btn-outline text-sm"
            >
              Upload another
            </button>
          </div>
          <p className="text-xs text-teter-gray-text mt-4">
            Task ID:{' '}
            <code className="bg-teter-gray px-1 rounded">{result.task_id}</code>
          </p>
        </div>
      </div>
    )
  }

  // ---------------------------------------------------------------------------
  // Form state
  // ---------------------------------------------------------------------------
  return (
    <div className="max-w-content mx-auto px-4 py-8">
      <form onSubmit={handleSubmit} noValidate>
        <div className="flex flex-col gap-6">

          {/* Project selector */}
          <div>
            <label htmlFor="project-select" className="label">
              Project <span className="text-red-500">*</span>
            </label>
            <select
              id="project-select"
              className="select w-full mt-1"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              disabled={submitting}
              required
            >
              <option value="">Select a project…</option>
              {projects.map((p) => (
                <option key={p.project_id} value={p.project_id}>
                  {p.project_number} — {p.name}
                </option>
              ))}
            </select>
            {projects.length === 0 && (
              <p className="text-xs text-teter-gray-text mt-1">
                No projects found. Create one in the Admin panel first.
              </p>
            )}
          </div>

          {/* Tool type selector */}
          <div>
            <label htmlFor="tool-type-select" className="label">Tool type</label>
            <select
              id="tool-type-select"
              className="select w-full mt-1"
              value={toolType}
              onChange={(e) => setToolType(e.target.value)}
              disabled={submitting}
            >
              {TOOL_TYPE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>

          {/* Primary document dropzone */}
          <Dropzone
            label="Primary Document *"
            hint="PDF, DOCX, XER, or XML — single file"
            multiple={false}
            files={primaryFiles}
            onFiles={setPrimaryFiles}
            disabled={submitting}
          />

          {/* Supporting documents dropzone */}
          <Dropzone
            label="Supporting Documents"
            hint="PDF, DOCX, XER, or XML — multiple files allowed (optional)"
            multiple={true}
            files={supportingFiles}
            onFiles={setSupportingFiles}
            disabled={submitting}
          />

          {/* Error feedback */}
          {error && (
            <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700" role="alert">
              {error}
            </div>
          )}

          {/* Submit */}
          <div className="flex items-center gap-3 pt-1">
            <button
              type="submit"
              disabled={!isReady || submitting}
              className="btn-primary"
            >
              {submitting ? (
                <span className="flex items-center gap-2">
                  {/* Spinner */}
                  <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24"
                    aria-hidden="true">
                    <circle className="opacity-25" cx="12" cy="12" r="10"
                      stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Uploading…
                </span>
              ) : 'Upload Document'}
            </button>

            {!isReady && !submitting && (
              <span className="text-xs text-teter-gray-text">
                {primaryFiles.length === 0 && projectId === ''
                  ? 'Select a project and primary document to continue'
                  : primaryFiles.length === 0
                  ? 'Add a primary document to continue'
                  : 'Select a project to continue'}
              </span>
            )}
          </div>

        </div>
      </form>
    </div>
  )
}
