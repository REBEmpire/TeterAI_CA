/**
 * Typed API client for the TeterAI backend (/api/v1).
 * Reads the JWT from localStorage and attaches it as a Bearer token.
 */
import type {
  AuditEntrySummary,
  ModelRegistryEntry,
  ProjectSummary,
  SubmittalReviewData,
  TaskDetail,
  TaskSummary,
  TokenResponse,
  UserInfo,
  UserSummary,
} from '../types'

const BASE = '/api/v1'

function getToken(): string | null {
  return localStorage.getItem('teterai_token')
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const token = getToken()
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(res.status, detail?.detail ?? res.statusText)
  }

  return res.json() as Promise<T>
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export async function loginWithGoogleToken(idToken: string): Promise<TokenResponse> {
  return request<TokenResponse>('POST', '/auth/google/callback', { id_token: idToken })
}

export async function loginWithPassword(username: string, password: string): Promise<TokenResponse> {
  return request<TokenResponse>('POST', '/auth/password', { username, password })
}

export async function getMe(): Promise<UserInfo> {
  return request<UserInfo>('GET', '/me')
}

// ---------------------------------------------------------------------------
// Tasks
// ---------------------------------------------------------------------------

export interface TaskFilters {
  project?: string
  doc_type?: string
  urgency?: string
  limit?: number
}

export async function listTasks(filters: TaskFilters = {}): Promise<TaskSummary[]> {
  const params = new URLSearchParams()
  if (filters.project) params.set('project', filters.project)
  if (filters.doc_type) params.set('doc_type', filters.doc_type)
  if (filters.urgency) params.set('urgency', filters.urgency)
  if (filters.limit) params.set('limit', String(filters.limit))
  const qs = params.toString()
  return request<TaskSummary[]>('GET', `/tasks${qs ? `?${qs}` : ''}`)
}

export async function getTask(taskId: string): Promise<TaskDetail> {
  return request<TaskDetail>('GET', `/tasks/${taskId}`)
}

export async function approveTask(taskId: string, editedDraft?: string): Promise<void> {
  return request('POST', `/tasks/${taskId}/approve`, { edited_draft: editedDraft ?? null })
}

export async function rejectTask(
  taskId: string,
  reason: string,
  notes?: string,
): Promise<void> {
  return request('POST', `/tasks/${taskId}/reject`, { reason, notes })
}

export async function escalateTask(taskId: string, notes?: string): Promise<void> {
  return request('POST', `/tasks/${taskId}/escalate`, { notes })
}

// ---------------------------------------------------------------------------
// Projects
// ---------------------------------------------------------------------------

export async function listProjects(): Promise<ProjectSummary[]> {
  return request<ProjectSummary[]>('GET', '/projects')
}

export async function createProject(data: {
  project_number: string
  name: string
  phase?: string
  known_senders?: string[]
}): Promise<ProjectSummary> {
  return request<ProjectSummary>('POST', '/projects', data)
}

// ---------------------------------------------------------------------------
// Users (Admin)
// ---------------------------------------------------------------------------

export async function listUsers(): Promise<UserSummary[]> {
  return request<UserSummary[]>('GET', '/users')
}

export async function updateUserRole(uid: string, role: string): Promise<void> {
  return request('PATCH', `/users/${uid}/role`, { role })
}

// ---------------------------------------------------------------------------
// Model Registry (Admin)
// ---------------------------------------------------------------------------

export async function getModelRegistry(): Promise<ModelRegistryEntry[]> {
  return request<ModelRegistryEntry[]>('GET', '/model-registry')
}

export async function updateModel(
  capabilityClass: string,
  tier: number,
  model: string,
): Promise<void> {
  return request('PATCH', `/model-registry/${capabilityClass}`, { tier, model })
}

// ---------------------------------------------------------------------------
// Submittal Review
// ---------------------------------------------------------------------------

export async function getSubmittalReview(taskId: string): Promise<SubmittalReviewData> {
  return request<SubmittalReviewData>('GET', `/tasks/${taskId}/submittal-review`)
}

export async function approveSubmittalReview(
  taskId: string,
  selectedItems: Record<string, boolean>,
): Promise<void> {
  return request('POST', `/tasks/${taskId}/submittal-review/approve`, { selected_items: selectedItems })
}

// ---------------------------------------------------------------------------
// Audit
// ---------------------------------------------------------------------------

export async function getTaskAudit(taskId: string): Promise<AuditEntrySummary[]> {
  return request<AuditEntrySummary[]>('GET', `/audit/${taskId}`)
}

export function auditExportUrl(taskId: string): string {
  const token = getToken()
  return `${BASE}/audit/${taskId}/export${token ? `?token=${token}` : ''}`
}
