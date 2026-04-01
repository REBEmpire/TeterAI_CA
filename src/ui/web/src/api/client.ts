/**
 * Typed API client for the TeterAI backend (/api/v1).
 * Reads the JWT from localStorage and attaches it as a Bearer token.
 */
import type {
  ApproveResponse,
  AuditEntrySummary,
  ModelRegistryEntry,
  ProjectSummary,
  RedTeamAuditData,
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

export async function approveTask(taskId: string, editedDraft?: string): Promise<ApproveResponse> {
  return request<ApproveResponse>('POST', `/tasks/${taskId}/approve`, { edited_draft: editedDraft ?? null })
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

export async function getRedTeamAudit(taskId: string): Promise<RedTeamAuditData | null> {
  try {
    return await request<RedTeamAuditData>('GET', `/tasks/${taskId}/red-team-audit`)
  } catch (e: unknown) {
    if (e instanceof ApiError && e.status === 404) return null
    throw e
  }
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

// ---------------------------------------------------------------------------
// Document Upload (Phase C)
// ---------------------------------------------------------------------------

export interface UploadDocumentResponse {
  task_id: string
  ingest_id: string
  tool_type: string
  status: string
}

/**
 * Upload a primary construction document plus optional supporting files.
 *
 * Uses multipart/form-data — does NOT go through the JSON `request()` helper
 * because the backend expects File uploads via FastAPI UploadFile + Form params.
 *
 * @param primaryFile      The main document (PDF/DOCX/XER/XML)
 * @param supportingFiles  Additional reference files (may be empty array)
 * @param projectId        Firestore project doc ID or project_number string
 * @param toolType         One of: rfi | submittal | cost | payapp | schedule
 *                         Omit (or pass undefined) to let the backend auto-detect.
 */
export async function uploadDocument(
  primaryFile: File,
  supportingFiles: File[],
  projectId: string,
  toolType?: string,
): Promise<UploadDocumentResponse> {
  const token = getToken()

  const formData = new FormData()
  formData.append('primary_file', primaryFile)
  for (const sf of supportingFiles) {
    formData.append('supporting_files', sf)
  }
  formData.append('project_id', projectId)
  if (toolType) {
    formData.append('tool_type', toolType)
  }

  const res = await fetch(`${BASE}/upload/document`, {
    method: 'POST',
    // Do NOT set Content-Type — the browser sets it automatically with the multipart boundary
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: formData,
  })

  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(res.status, detail?.detail ?? res.statusText)
  }

  return res.json() as Promise<UploadDocumentResponse>
}

// ---------------------------------------------------------------------------
// Project Intelligence Dashboard
// ---------------------------------------------------------------------------

export interface ProjectIntelligence {
  project_id: string
  total_docs: number
  responded_docs: number
  response_rate: number          // 0–1
  metadata_only_count: number
  metadata_only_ratio: number    // 0–1
  party_count: number
  earliest_date?: string | null
  latest_date?: string | null
  doc_counts_by_type: Record<string, number>
}

export interface PartyEntry {
  party_id: string
  name: string
  type: string
  submissions: Array<{ doc_type: string; count: number }>
  total_submissions: number
}

export interface TimelineMonth {
  month: string                        // "YYYY-MM"
  counts: Record<string, number>       // doc_type → count
}

export interface CrossProjectEntry {
  project_id: string
  name: string
  project_number: string
  total_docs: number
  responded_docs: number
  response_rate: number
  metadata_only_count: number
  party_count: number
}

export interface AINarrative {
  overview: string
  document_status: string
  key_parties: string
  risk_flags: string
  recommendations: string
}

export interface AISummaryResponse {
  project_id: string
  narrative: AINarrative
  generated_at: string
  model_used: string
  tier_used: number
}

export async function getProjectIntelligence(
  projectId: string,
): Promise<ProjectIntelligence> {
  return request<ProjectIntelligence>('GET', `/projects/${projectId}/intelligence`)
}

export async function getPartyNetwork(
  projectId: string,
): Promise<{ parties: PartyEntry[] }> {
  return request<{ parties: PartyEntry[] }>('GET', `/projects/${projectId}/party-network`)
}

export async function getDocumentTimeline(
  projectId: string,
): Promise<{ months: TimelineMonth[] }> {
  return request<{ months: TimelineMonth[] }>('GET', `/projects/${projectId}/timeline`)
}

export async function compareProjects(): Promise<{ projects: CrossProjectEntry[] }> {
  return request<{ projects: CrossProjectEntry[] }>('GET', '/projects/compare')
}

export async function generateAISummary(
  projectId: string,
): Promise<AISummaryResponse> {
  return request<AISummaryResponse>('POST', `/projects/${projectId}/ai-summary`)
}

// ---------------------------------------------------------------------------
// Pre-Bid Lessons Learned
//
// POST /prebid-lessons mines completed-project RFI / Change Order history via
// vector similarity search and synthesises findings into an AI pre-bid checklist.
//
// Usage:
//   const result = await getPreBidLessons(
//     "exterior window waterproofing and head flashing",
//     ["11900", "12556"]
//   )
//   // result.similar_docs   — historically similar issues ranked by score
//   // result.doc_type_counts — volume by doc type in source projects
//   // result.checklist       — AI-generated {summary, design_risks,
//   //                           spec_sections_to_clarify, bid_checklist}
// ---------------------------------------------------------------------------

export interface PreBidSimilarDoc {
  doc_id: string
  filename: string
  doc_type: string
  doc_number?: string | null
  summary?: string | null
  date_submitted?: string | null
  project_id: string
  project_name?: string | null
  project_number?: string | null
  score: number
}

export interface PreBidChecklist {
  summary: string
  design_risks: string
  spec_sections_to_clarify: string
  bid_checklist: string
}

export interface PreBidLessonsResponse {
  query_text: string
  source_project_ids: string[]
  similar_docs: PreBidSimilarDoc[]
  doc_type_counts: Record<string, number>
  checklist: PreBidChecklist
  generated_at: string
  model_used: string
  tier_used: number
}

/**
 * Run a Pre-Bid Lessons Learned review.
 *
 * Embeds `queryText` and searches the Neo4j `ca_document_embeddings` vector index
 * for semantically similar historical RFIs and Change Orders from `sourceProjectIds`.
 * An AI model (CapabilityClass.ANALYZE) then synthesises findings into an actionable
 * checklist the design team can use before bid documents go out.
 *
 * @param queryText        Plain-English design concern (e.g. "exterior window flashing").
 * @param sourceProjectIds IDs of completed projects to mine (must match Neo4j project_id).
 * @param docTypes         Optional doc type filter. Defaults to RFI / CO variants.
 */
export async function getPreBidLessons(
  queryText: string,
  sourceProjectIds: string[],
  docTypes?: string[],
): Promise<PreBidLessonsResponse> {
  return request<PreBidLessonsResponse>('POST', '/prebid-lessons', {
    query_text: queryText,
    source_project_ids: sourceProjectIds,
    ...(docTypes ? { doc_types: docTypes } : {}),
  })
}
