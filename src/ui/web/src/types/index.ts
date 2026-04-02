// ---------------------------------------------------------------------------
// Domain types mirroring the Python API response models
// ---------------------------------------------------------------------------

export type UserRole = 'CA_STAFF' | 'ADMIN' | 'REVIEWER'

export interface UserInfo {
  uid: string
  email: string
  display_name: string
  role: UserRole
}

export type TaskStatus =
  | 'PENDING_CLASSIFICATION'
  | 'CLASSIFYING'
  | 'ASSIGNED_TO_AGENT'
  | 'PROCESSING'
  | 'STAGED_FOR_REVIEW'
  | 'ESCALATED_TO_HUMAN'
  | 'APPROVED'
  | 'REJECTED'
  | 'ERROR'

export type DocumentType =
  | 'RFI'
  | 'SUBMITTAL'
  | 'SUBSTITUTION'
  | 'CHANGE_ORDER'
  | 'PAY_APP'
  | 'MEETING_MINUTES'
  | 'GENERAL'
  | 'UNKNOWN'

export type Urgency = 'HIGH' | 'MEDIUM' | 'LOW'

export type Phase = 'bid' | 'construction' | 'closeout' | 'UNKNOWN'

export interface TaskSummary {
  task_id: string
  status: TaskStatus
  urgency: Urgency
  document_type: DocumentType
  document_number?: string
  project_number?: string
  sender_name?: string
  subject?: string
  created_at?: string
  response_due?: string
  classification_confidence?: number
  assigned_agent?: string
}

export interface TaskDetail extends TaskSummary {
  draft_content?: string
  draft_version?: string
  agent_id?: string
  agent_version?: string
  confidence_score?: number
  citations: string[]
  thought_chain_file_id?: string
  source_email?: Record<string, unknown>
  attachments: Attachment[]
  referenced_specs?: Array<Record<string, string>>
  referenced_drawings?: Array<Record<string, string>>
  phase?: Phase
  rejection_reason?: string
  rejection_notes?: string
  delivered_path?: string
}

export interface ApproveResponse {
  status: string
  task_id: string
  delivery_triggered: boolean
  delivered_path?: string
}

export interface Attachment {
  file_id: string
  filename: string
  mime_type: string
  size_bytes?: number
}

export type RejectionReason =
  | 'CitationError'
  | 'ContentError'
  | 'ToneStyle'
  | 'MissingInfo'
  | 'ScopeIssue'
  | 'Other'

export interface ProjectSummary {
  project_id: string
  project_number: string
  name: string
  phase: string
  active: boolean
  created_at?: string
}

export interface UserSummary {
  uid: string
  email: string
  display_name: string
  role: UserRole
  active: boolean
}

export interface ModelRegistryEntry {
  capability_class: string
  tier_1: string
  tier_2?: string
  tier_3?: string
}

export interface AuditEntrySummary {
  log_id: string
  log_type: string
  timestamp?: string
  task_id?: string
  agent_id?: string
  reviewer_uid?: string
  action?: string
  status?: string
  details: Record<string, unknown>
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user: UserInfo
}

// ---------------------------------------------------------------------------
// Submittal Review types
// ---------------------------------------------------------------------------

export type ReviewItemSeverity = 'OK' | 'MINOR_NOTE' | 'MAJOR_WARNING'
export type WarningType = 'MAJOR_WARNING' | 'MISSING_INFO_WARNING'

export interface SubmittalComparisonItem {
  id: string
  category: string
  item: string
  specified_value: string
  submitted_value: string
  difference: string
  compliance: boolean
  severity: ReviewItemSeverity
  comments: string
}

export interface SubmittalWarningItem {
  id: string
  type: WarningType
  description: string
  recommendation: string
}

export interface SubmittalModelResult {
  provider: string
  model: string
  error?: string
  items: {
    comparison_table: SubmittalComparisonItem[]
    warnings: SubmittalWarningItem[]
    missing_info: SubmittalWarningItem[]
    summary: string
  }
}

export interface SubmittalReviewData {
  task_id: string
  model_results: {
    tier_1?: SubmittalModelResult
    tier_2?: SubmittalModelResult
    tier_3?: SubmittalModelResult
  }
  selected_items: Record<string, boolean>
}

// ---------------------------------------------------------------------------
// Red Team Audit types
// ---------------------------------------------------------------------------

export interface CritiqueItem {
  field: string
  original: string
  critique: string
  severity: 'AGREE' | 'MINOR_REVISION' | 'MAJOR_REVISION' | 'REJECT'
  revised_value?: string | null
}

export interface RedTeamResult {
  critique_items: CritiqueItem[]
  summary: string
  overall_severity: 'AGREE' | 'MINOR_REVISION' | 'MAJOR_REVISION' | 'REJECT'
}

export interface RedTeamAuditData {
  initial_review: Record<string, unknown>
  red_team_critique: RedTeamResult
  final_output: Record<string, unknown>
}

// ---------------------------------------------------------------------------
// Closeout types
// ---------------------------------------------------------------------------

export type CloseoutItemStatus =
  | 'NOT_RECEIVED'
  | 'RECEIVED'
  | 'UNDER_REVIEW'
  | 'ACCEPTED'
  | 'DEFICIENT'

export type CloseoutDocType =
  | 'WARRANTY'
  | 'OM_MANUAL'
  | 'AS_BUILT'
  | 'TESTING_REPORT'
  | 'GOV_PAPERWORK'
  | 'PROJECT_DIRECTORY'
  | 'RFI_LOG'

export interface CloseoutChecklistItem {
  item_id: string
  project_id: string
  spec_section: string
  spec_title: string
  document_type: CloseoutDocType
  label: string
  urgency: Urgency
  status: CloseoutItemStatus
  responsible_party?: string
  document_path?: string
  reviewed_by?: string
  reviewed_at?: string
  deficiency_notes?: string
  notes?: string
}

export interface CloseoutDeficiency {
  deficiency_id: string
  item_id: string
  project_id: string
  description: string
  severity: string
  status: 'OPEN' | 'RESOLVED' | 'WAIVED'
  created_at?: string
  resolved_at?: string
  resolved_by?: string
  notes?: string
}

export interface CloseoutSummary {
  project_id: string
  project_name: string
  total_items: number
  not_received: number
  received: number
  under_review: number
  accepted: number
  deficient: number
  completion_pct: number
  items: CloseoutChecklistItem[]
  deficiencies: CloseoutDeficiency[]
}

export interface CloseoutScanResult {
  matched: Array<{
    item_id: string
    file_path: string
    spec_section: string
    document_type: string
  }>
  unmatched: string[]
}

// ---------------------------------------------------------------------------
// Document Analysis types (Multi-Model)
// ---------------------------------------------------------------------------

export type AnalysisStatus = 'SUCCESS' | 'FAILED' | 'TIMEOUT' | 'RATE_LIMITED'

export interface AnalysisMetadata {
  model_id: string
  provider: string
  model: string
  tier: number
  latency_ms: number
  input_tokens: number
  output_tokens: number
  timestamp: string
}

export interface ModelAnalysisResponse {
  status: AnalysisStatus
  content?: string
  metadata?: AnalysisMetadata
  error?: string
  summary?: string
  key_findings?: string[]
  recommendations?: string[]
  confidence_score?: number
}

export interface MultiModelAnalysisResult {
  analysis_id: string
  document_id?: string
  document_name?: string
  document_type?: string
  analysis_purpose?: string
  started_at: string
  completed_at?: string
  tier_1_response?: ModelAnalysisResponse
  tier_2_response?: ModelAnalysisResponse
  tier_3_response?: ModelAnalysisResponse
  total_latency_ms?: number
  successful_models?: number
}

export interface ComparisonColumn {
  model_name: string
  provider: string
  tier: number
  status: AnalysisStatus
  latency_ms?: number
  content?: string
  summary?: string
  key_findings?: string[]
  recommendations?: string[]
  confidence?: number
  error?: string
}

// ---------------------------------------------------------------------------
// Grading types (AI + Human Comparison)
// ---------------------------------------------------------------------------

export type GradingCriterion = 'ACCURACY' | 'COMPLETENESS' | 'RELEVANCE' | 'CITATION_QUALITY'
export type GradeSource = 'AI_JUDGE' | 'HUMAN'
export type DivergenceLevel = 'NONE' | 'LOW' | 'MEDIUM' | 'HIGH'

export interface CriterionScore {
  score: number  // 0-10
  reasoning: string
  evidence?: string[]
}

export interface ModelGrade {
  grade_id: string
  session_id: string
  model_id: string
  model_name: string
  tier: number
  source: GradeSource
  accuracy: CriterionScore
  completeness: CriterionScore
  relevance: CriterionScore
  citation_quality: CriterionScore
  overall_score: number
  grader_id?: string
  graded_at: string
  notes?: string
}

export interface CriterionDivergence {
  criterion: GradingCriterion
  ai_score: number
  human_score: number
  difference: number
  level: DivergenceLevel
}

export interface DivergenceAnalysis {
  analysis_id: string
  session_id: string
  model_id: string
  model_name: string
  criterion_divergences: CriterionDivergence[]
  overall_ai_score: number
  overall_human_score: number
  overall_difference: number
  overall_level: DivergenceLevel
  analyzed_at: string
  calibration_notes?: string
  action_items?: string[]
}

export interface GradingSession {
  session_id: string
  analysis_id: string
  document_id?: string
  document_name?: string
  status: string
  ai_grades: Record<string, ModelGrade>
  human_grades: Record<string, ModelGrade>
  divergence_analyses: Record<string, DivergenceAnalysis>
  created_at: string
  completed_at?: string
}

export interface GradingSessionSummary {
  session_id: string
  analysis_id: string
  document_name?: string
  status: string
  model_count: number
  ai_graded_count: number
  human_graded_count: number
  avg_ai_score?: number
  avg_divergence?: number
  created_at: string
}

export interface DivergenceReport {
  total_sessions: number
  total_analyses: number
  avg_divergence: number
  divergence_by_criterion: Record<GradingCriterion, number>
  high_divergence_count: number
  trends: Array<{
    period: string
    avg_divergence: number
    count: number
  }>
  recommendations: string[]
  generated_at: string
}
