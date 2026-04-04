/**
 * Typed API client for the TeterAI backend (/api/v1).
 * Reads the JWT from localStorage and attaches it as a Bearer token.
 */
import type {
  ApproveResponse,
  AuditEntrySummary,
  CloseoutChecklistItem,
  CloseoutDeficiency,
  CloseoutScanResult,
  CloseoutSummary,
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
// Workflow
// ---------------------------------------------------------------------------

export interface DispatchResult {
  dispatched: number
  agents_run: number
  errors: string[]
}

/** Trigger an on-demand dispatch run: classifier + all tool agents. */
export async function dispatchNow(): Promise<DispatchResult> {
  return request<DispatchResult>('POST', '/workflow/dispatch')
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

export interface ScanProjectsResponse {
  imported: ProjectSummary[]
  skipped: number
  errors: string[]
}

export async function scanProjects(): Promise<ScanProjectsResponse> {
  return request<ScanProjectsResponse>('POST', '/projects/scan')
}

export async function updateProject(
  projectId: string,
  data: { phase?: string; active?: boolean; name?: string },
): Promise<ProjectSummary> {
  return request<ProjectSummary>('PATCH', `/projects/${projectId}`, data)
}

// ---------------------------------------------------------------------------
// Closeout
// ---------------------------------------------------------------------------

export async function getCloseoutSummary(projectId: string): Promise<CloseoutSummary> {
  return request<CloseoutSummary>('GET', `/projects/${projectId}/closeout`)
}

export async function updateChecklistItem(
  projectId: string,
  itemId: string,
  data: { status?: string; document_path?: string; responsible_party?: string; notes?: string },
): Promise<CloseoutChecklistItem> {
  return request<CloseoutChecklistItem>('PATCH', `/projects/${projectId}/closeout/${itemId}`, data)
}

export async function createDeficiency(
  projectId: string,
  itemId: string,
  data: { description: string; severity?: string },
): Promise<CloseoutDeficiency> {
  return request<CloseoutDeficiency>('POST', `/projects/${projectId}/closeout/${itemId}/deficiency`, data)
}

export async function scanCloseoutFolder(projectId: string): Promise<CloseoutScanResult> {
  return request<CloseoutScanResult>('POST', `/projects/${projectId}/closeout/scan`)
}

export async function addChecklistItem(
  projectId: string,
  data: {
    spec_section: string
    spec_title: string
    document_type: string
    urgency?: string
    responsible_party?: string
  },
): Promise<CloseoutChecklistItem> {
  return request<CloseoutChecklistItem>('POST', `/projects/${projectId}/closeout/items`, data)
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

// ---------------------------------------------------------------------------
// Document Analysis (Multi-Model)
// ---------------------------------------------------------------------------

import type {
  MultiModelAnalysisResult,
  ComparisonColumn,
  GradingSession,
  GradingSessionSummary,
  DivergenceReport,
  CriterionScore,
} from '../types'

export interface AnalyzeDocumentResponse {
  analysis: MultiModelAnalysisResult
  comparison_view: {
    columns: ComparisonColumn[]
    document_name: string
    analysis_id: string
  }
}

/**
 * Analyze a document using multi-model analysis (Claude, Gemini, Grok).
 * @param file The document file to analyze
 * @param purpose Optional analysis purpose for context
 */
export async function analyzeDocument(
  file: File,
  purpose?: string,
): Promise<AnalyzeDocumentResponse> {
  const token = getToken()
  
  const formData = new FormData()
  formData.append('file', file)
  if (purpose) {
    formData.append('purpose', purpose)
  }

  const res = await fetch(`${BASE}/document-analysis/analyze`, {
    method: 'POST',
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: formData,
  })

  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(res.status, detail?.detail ?? res.statusText)
  }

  return res.json() as Promise<AnalyzeDocumentResponse>
}

/**
 * Get a previously completed analysis by ID
 */
export async function getAnalysis(analysisId: string): Promise<MultiModelAnalysisResult> {
  return request<MultiModelAnalysisResult>('GET', `/document-analysis/${analysisId}`)
}

/**
 * Get the comparison view for an analysis
 */
export async function getComparisonView(analysisId: string): Promise<{ columns: ComparisonColumn[] }> {
  return request<{ columns: ComparisonColumn[] }>('GET', `/document-analysis/${analysisId}/comparison`)
}

// ---------------------------------------------------------------------------
// Grading (AI + Human Comparison)
// ---------------------------------------------------------------------------

export interface GradeAnalysisRequest {
  analysis_id: string
  document_content: string
  analysis_purpose: string
}

export interface HumanGradeInput {
  session_id: string
  model_id: string
  grader_id: string
  scores: {
    accuracy: { score: number; reasoning: string; evidence?: string[] }
    completeness: { score: number; reasoning: string; evidence?: string[] }
    relevance: { score: number; reasoning: string; evidence?: string[] }
    citation_quality: { score: number; reasoning: string; evidence?: string[] }
  }
  notes?: string
}

/**
 * Auto-grade a multi-model analysis result using AI judge (Claude)
 */
export async function gradeAnalysis(
  analysisId: string,
  documentContent: string,
  analysisPurpose: string,
): Promise<GradingSession> {
  return request<GradingSession>('POST', '/grading/grade', {
    analysis_id: analysisId,
    document_content: documentContent,
    analysis_purpose: analysisPurpose,
  })
}

/**
 * Submit human grades for a model in a grading session
 */
export async function submitHumanGrade(input: HumanGradeInput): Promise<GradingSession> {
  return request<GradingSession>('POST', '/grading/human-grade', input)
}

/**
 * Get a grading session by ID
 */
export async function getGradingSession(sessionId: string): Promise<GradingSession> {
  return request<GradingSession>('GET', `/grading/sessions/${sessionId}`)
}

/**
 * Get session formatted for human grading interface
 */
export async function getSessionForGrading(sessionId: string): Promise<{
  session: GradingSession
  models_awaiting_human_grade: string[]
}> {
  return request<{ session: GradingSession; models_awaiting_human_grade: string[] }>(
    'GET',
    `/grading/sessions/${sessionId}/for-grading`,
  )
}

/**
 * Get AI grade details for a specific model
 */
export async function getAIGradeForModel(
  sessionId: string,
  modelId: string,
): Promise<{ grade: import('../types').ModelGrade; model_response: import('../types').ModelAnalysisResponse }> {
  return request('GET', `/grading/sessions/${sessionId}/ai-grade/${modelId}`)
}

/**
 * List grading sessions with optional status filter
 */
export async function listGradingSessions(
  status?: 'pending' | 'ai_graded' | 'human_graded' | 'complete',
): Promise<GradingSessionSummary[]> {
  const params = status ? `?status=${status}` : ''
  return request<GradingSessionSummary[]>('GET', `/grading/sessions${params}`)
}

/**
 * List sessions pending human review
 */
export async function getPendingGradingSessions(): Promise<GradingSessionSummary[]> {
  return request<GradingSessionSummary[]>('GET', '/grading/pending')
}

/**
 * Get divergence report with optional filters
 */
export async function getDivergenceReport(params?: {
  start_date?: string
  end_date?: string
  model_id?: string
}): Promise<DivergenceReport> {
  const qs = new URLSearchParams()
  if (params?.start_date) qs.set('start_date', params.start_date)
  if (params?.end_date) qs.set('end_date', params.end_date)
  if (params?.model_id) qs.set('model_id', params.model_id)
  const query = qs.toString()
  return request<DivergenceReport>('GET', `/grading/divergence-report${query ? `?${query}` : ''}`)
}

/**
 * Add calibration notes to a divergence analysis
 */
export async function addDivergenceNotes(
  sessionId: string,
  modelId: string,
  notes: string,
  actionItems?: string[],
): Promise<void> {
  return request('POST', `/grading/sessions/${sessionId}/divergence/${modelId}/notes`, {
    calibration_notes: notes,
    action_items: actionItems ?? [],
  })
}
export const apiClient = {
  getSettings: () => request<any>('GET', '/settings'),
  post: (path: string, data: any) => request<any>('POST', path, data),
  getHealth: () => request<any>('GET', '/health'),
  retryTask: (taskId: string) => request<any>('POST', `/tasks/${taskId}/retry`)
}
