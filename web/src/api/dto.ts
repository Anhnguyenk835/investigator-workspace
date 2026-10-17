/** Wire shapes of the Investigator API (snake_case, as the backend sends them). */

export type CoverageStatusDto = 'searched' | 'partial' | 'no_matches' | 'not_connected' | 'permission_denied' | 'failed'
export type TimestampPrecisionDto = 'exact' | 'date_only' | 'unknown'
export type RunStatusDto = 'queued' | 'investigating' | 'blocked' | 'needs_review' | 'resolved' | 'failed'
export type AwaitingDto = 'clarification' | 'review' | 'draft_approval'

export interface EvidenceDto {
  id: string
  source: string
  title: string
  author: string | null
  occurred_at: string | null
  timestamp_precision: TimestampPrecisionDto
  excerpt: string
  url: string | null
  thread_id: string | null
  customer_id: string | null
  project_id: string | null
  author_id: string | null
  author_side: 'customer' | 'internal' | 'third_party' | null
  author_role: string | null
  participants: string[]
  trust: 'normal' | 'flagged' | 'tainted'
  quarantine: { start: number; end: number; rule: string }[]
}

export interface CoverageDto {
  source: string
  status: CoverageStatusDto
  detail: string | null
}

export interface CaseContextDto {
  customer_id: string | null
  project_id: string | null
  ticket_ids: string[]
  date_from: string | null
  date_to: string | null
  sources: string[] | null
}

export type SupportVerdictDto = 'supported' | 'partial' | 'unsupported'
export type SupportStatusDto = 'unchecked' | 'supported' | 'partial' | 'unsupported'

export interface SupportCheckDto {
  evidence_id: string
  verdict: SupportVerdictDto
  quote: string | null
}

export interface TimelineEventDto {
  support: SupportCheckDto[]
  support_status: SupportStatusDto
  id: string
  title: string
  event_type: string
  actor: string | null
  summary: string
  occurred_at: string | null
  timestamp_precision: TimestampPrecisionDto
  evidence_ids: string[]
}

export interface CommitmentDto {
  support: SupportCheckDto[]
  support_status: SupportStatusDto
  id: string
  description: string
  committed_by: string | null
  owner: string | null
  promised_at: string | null
  due_date: string | null
  basis: 'explicit' | 'inferred'
  status: 'confirmed' | 'fulfilled' | 'at_risk' | 'overdue' | 'unverified'
  evidence_ids: string[]
  fulfilled_by_evidence_ids: string[]
}

export interface BlockerDto {
  id: string
  description: string
  kind: 'blocker' | 'dependency' | 'probable_cause'
  basis: 'stated' | 'inferred'
  evidence_ids: string[]
}

export interface ClaimSideDto {
  text: string
  evidence_ids: string[]
}

export interface ConflictDto {
  id: string
  claim_a: ClaimSideDto
  claim_b: ClaimSideDto
  why: string
  resolution: 'unresolved' | 'resolved'
}

export interface GapDto {
  id: string
  what_missing: string
  why_it_matters: string
  resolving_evidence: string
  follow_up: string
  origin: 'coverage' | 'analysis' | 'quality'
}

export interface FindingDto {
  support: SupportCheckDto[]
  support_status: SupportStatusDto
  id: string
  title: string
  claim: string
  explanation: string
  status: 'verified' | 'needs_verification' | 'conflicting' | 'unknown'
  supporting_evidence_ids: string[]
  contradicting_evidence_ids: string[]
  reasoning_type: 'direct' | 'inference'
  reviewer_note: string | null
  review_flag: string | null
}

export interface ActionDto {
  id: string
  title: string
  rationale: string
  owner: string | null
  priority: 'low' | 'medium' | 'high'
  related_finding_ids: string[]
  evidence_ids: string[]
  status: 'suggested'
}

export interface ValidationIssueDto {
  finding_id: string | null
  code: string
  severity: 'error' | 'warning'
  detail: string
}

export interface ValidationReportDto {
  passed: boolean
  issues: ValidationIssueDto[]
  repaired: number
  dropped: number
}

export interface PendingDto {
  kind?: string
  [key: string]: unknown
}

export interface InvestigationDto {
  owner: string | null
  /** A shared demo investigation: readable by every visitor, writable by none. */
  sample?: boolean
  run_no: number
  scope_note: string | null
  id: string
  question: string
  status: RunStatusDto
  awaiting: AwaitingDto | null
  pending: PendingDto | null
  context: CaseContextDto
  coverage: CoverageDto[]
  evidence: EvidenceDto[]
  timeline: TimelineEventDto[]
  commitments: CommitmentDto[]
  blockers: BlockerDto[]
  conflicts: ConflictDto[]
  gaps: GapDto[]
  summary: string
  findings: FindingDto[]
  rejected_findings: FindingDto[]
  validation: ValidationReportDto
  actions: ActionDto[]
  review_decision: string
  reviewer_notes: string[]
  draft: string
  draft_warnings: string[]
  draft_status: 'none' | 'drafted' | 'approved' | 'changes_requested' | 'not_possible'
  resolved_by: string | null
  resolved_at: string | null
  search_notes: string | null
  error: string | null
  created_at: string
  updated_at: string
}

export interface CreateInvestigationDto {
  question: string
  customer_id?: string
  project_id?: string
  ticket_ids?: string[]
  date_from?: string
  date_to?: string
  sources?: string[]
}

export type ReviewDecisionDto = 'approved' | 'needs_more_evidence' | 'revise'

export type ResumeValueDto =
  | { project_id?: string; customer_id?: string; scope?: Record<string, string[]>; note?: string }
  | { decision: ReviewDecisionDto; note?: string }
  | { approved: boolean; draft?: string; note?: string }

export type IntegrationStateDto = 'not_configured' | 'not_connected' | 'connected' | 'reauth_required'

export interface IntegrationDto {
  provider: string
  label: string
  sources: string[]
  state: IntegrationStateDto
  account: string | null
  scopes: string[]
  connected_at: string | null
}

export interface ToolEventDto {
  tool: string
  source: string | null
  status: string
  records: number
  new_records: number
  note: string | null
}

export interface ConversationDto {
  id: string
  investigation_id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export interface ChatMessageDto {
  id: string
  investigation_id: string
  conversation_id: string | null
  role: 'user' | 'assistant'
  content: string
  citations: string[]
  new_evidence: EvidenceDto[]
  warnings: string[]
  tools: ToolEventDto[]
  created_at: string
}

/** Events of one chat turn, in the order they arrive. */
export type ChatStreamEvent =
  | { event: 'user_message'; data: ChatMessageDto }
  | { event: 'delta'; data: { text: string } }
  | { event: 'turn_end'; data: { tool_calls: boolean } }
  | { event: 'checking'; data: Record<string, never> }
  | { event: 'tool'; data: ToolEventDto }
  | { event: 'done'; data: { message: ChatMessageDto } }
  | { event: 'error'; data: { message: string } }

/** Progress events of an investigation run. */
export type RunEventKind = 'run' | 'step' | 'tool' | 'status' | 'error' | 'done'

export interface RunEventDto {
  kind: RunEventKind
  at?: string
  // Step, tool and status events carry different fields; read them by kind.
  [key: string]: unknown
}

export interface CustomerDto {
  id: string
  name: string
  aliases: string[]
  email_domains: string[]
}

export interface ProjectDto {
  id: string
  customer_id: string | null
  name: string
  aliases: string[]
  ticket_prefixes: string[]
  jira_projects: string[]
  jira_labels: string[]
  slack_channel_ids: string[]
  gmail_labels: string[]
  confluence_spaces: string[]
}

export interface PersonDto {
  id: string
  name: string
  aliases: string[]
  emails: string[]
  slack_ids: string[]
  jira_account_ids: string[]
  side: 'customer' | 'internal' | 'third_party'
  role: string | null
  customer_id: string | null
}

export interface DirectoryDto {
  customers: CustomerDto[]
  projects: ProjectDto[]
  people: PersonDto[]
}

export interface SuggestionsDto {
  source: string
  status: 'ok' | 'not_connected' | 'failed'
  options: { id: string; label: string }[]
}

export interface AnnotationDto {
  id: string
  investigation_id: string
  target_id: string
  kind: 'note' | 'reviewed' | 'disputed'
  text: string
  author: string
  created_at: string
}

/** Who is signed in. `disabled`: this server has no sign-in and everyone is the one local user. */
export interface MeDto {
  mode: 'user' | 'demo' | 'anonymous' | 'disabled'
  user: { id: string; email: string | null; name: string | null; picture: string | null } | null
  providers: { google: boolean; demo: boolean }
}
