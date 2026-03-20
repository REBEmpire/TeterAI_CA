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
