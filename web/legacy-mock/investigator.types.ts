export type SourceProvider =
  | 'gmail'
  | 'outlook'
  | 'slack'
  | 'teams'
  | 'jira'
  | 'linear'
  | 'confluence'
  | 'notion'
  | 'google_drive'
  | 'salesforce'

export type RecordType =
  | 'email'
  | 'chat_message'
  | 'issue'
  | 'issue_comment'
  | 'page'
  | 'project_update'

export type TimestampPrecision = 'exact' | 'date_only' | 'unknown'
export type IndexStatus = 'indexed' | 'partial' | 'unsupported' | 'unavailable'

export interface EvidenceRecord {
  id: string
  provider: SourceProvider
  recordType: RecordType
  externalRecordId: string
  title: string
  author?: string
  authorSide?: 'customer' | 'internal'
  timestamp: string
  timestampPrecision: TimestampPrecision
  excerpt: string
  context?: string
  location?: string
  /** Simulated, non-navigable source path. Demo records never carry a real URL. */
  sourceRef: string
  sourceUrl?: string
  customerName: string
  projectName: string
  ingestedAt: string
  indexedAt?: string
  indexStatus: IndexStatus
  isDemo: boolean
}

export type InvestigationStatus =
  | 'draft'
  | 'queued'
  | 'investigating'
  | 'needs_review'
  | 'blocked'
  | 'resolved'
  | 'failed'

export type CoverageStatus =
  | 'searched'
  | 'partial'
  | 'not_connected'
  | 'permission_denied'
  | 'search_failed'
  | 'no_matches'

export interface SourceCoverage {
  provider: SourceProvider
  status: CoverageStatus
  recordsFound?: number
  searchedAt?: string
  warning?: string
}

export interface CitedText {
  text: string
  evidenceIds?: string[]
}

export interface InvestigationSummary {
  overview: CitedText[]
  status: CitedText[]
  blocker: CitedText[]
  nextStep: CitedText[]
}

export interface RunJob {
  kind: 'initial' | 'rerun'
  stage: number
  startedAt: string
}

export interface Investigation {
  id: string
  title: string
  problemStatement: string
  customerName?: string
  projectName?: string
  ticketId?: string
  people?: string
  dateFrom?: string
  dateTo?: string
  owner: string
  status: InvestigationStatus
  selectedProviders: SourceProvider[]
  coverage: SourceCoverage[]
  summary: InvestigationSummary | null
  summaryReviewedBy?: string
  summaryReviewedAt?: string
  createdAt: string
  updatedAt: string
  lastRunAt?: string
  lastRunNote?: string
  runCount: number
  analysisVersion: number
  job?: RunJob
  failureReason?: string
  resolvedAt?: string
  resolvedBy?: string
  notes?: ActionNote[]
}

export type FindingStatus =
  | 'verified'
  | 'needs_verification'
  | 'conflicting'
  | 'unknown'

export interface Finding {
  id: string
  investigationId: string
  title: string
  claim: string
  explanation: string
  status: FindingStatus
  basis: 'direct' | 'inference'
  supportingEvidenceIds: string[]
  contradictingEvidenceIds: string[]
  /** Customer-safe phrasing used by the response draft. Absent = never shared. */
  customerStatement?: string
  reviewerNote?: string
  reviewedBy?: string
  reviewedAt?: string
}

export type TimelineEventType =
  | 'customer_request'
  | 'commitment'
  | 'internal_discussion'
  | 'ticket_change'
  | 'document_update'
  | 'blocker'
  | 'deadline_change'
  | 'customer_message'

export interface TimelineEvent {
  id: string
  investigationId: string
  title: string
  description: string
  eventType: TimelineEventType
  occurredAt: string
  precision: TimestampPrecision
  actor?: string
  provider: SourceProvider
  evidenceIds: string[]
  relatedFindingIds: string[]
  relatedCommitmentIds: string[]
}

export type CommitmentStatus =
  | 'confirmed'
  | 'fulfilled'
  | 'at_risk'
  | 'overdue'
  | 'unverified'

export interface Commitment {
  id: string
  investigationId: string
  statement: string
  committedBy?: string
  owner?: string
  promisedAt?: string
  dueAt?: string
  status: CommitmentStatus
  evidenceIds: string[]
  reviewerNote?: string
}

export type IssueReview = 'unresolved' | 'reviewed'

export interface Gap {
  id: string
  investigationId: string
  missing: string
  whyItMatters: string
  resolvingEvidence: string
  followUp: string
  relatedEvidenceIds: string[]
  customerQuestion?: string
  review: IssueReview
  reviewerNote?: string
}

export interface ContradictionClaim {
  text: string
  at: string
  evidenceIds: string[]
}

export interface Contradiction {
  id: string
  investigationId: string
  title: string
  claimA: ContradictionClaim
  claimB: ContradictionClaim
  explanation: string
  review: IssueReview
  reviewerNote?: string
}

export type ActionStatus =
  | 'suggested'
  | 'accepted'
  | 'in_progress'
  | 'completed'
  | 'dismissed'

export interface ActionNote {
  id: string
  text: string
  author: string
  at: string
}

export interface RecommendedAction {
  id: string
  investigationId: string
  title: string
  rationale: string
  suggestedOwner?: string
  priority: 'low' | 'medium' | 'high'
  relatedFindingIds: string[]
  relatedEvidenceIds: string[]
  customerStep?: string
  status: ActionStatus
  notes: ActionNote[]
  createdAt: string
  updatedAt: string
}

export type DraftStatus = 'draft' | 'reviewed' | 'approved'

export interface ResponseDraft {
  investigationId: string
  body: string
  generatedBody: string
  status: DraftStatus
  basedOnVersion: number
  savedAt: string
  reviewedBy?: string
  reviewedAt?: string
  approvedBy?: string
  approvedAt?: string
}

export type ConnectorStatus =
  | 'not_connected'
  | 'connecting'
  | 'connected'
  | 'syncing'
  | 'sync_completed'
  | 'needs_attention'
  | 'permission_revoked'
  | 'sync_failed'

export type DateRange = '30d' | '90d' | '1y' | 'all'

export interface ConnectorScope {
  resources: string[]
  dateRange: DateRange
  contentTypes: string[]
  includeArchived: boolean
}

export interface Connector {
  id: SourceProvider
  provider: SourceProvider
  status: ConnectorStatus
  accountLabel?: string
  workspaceLabel?: string
  scope: ConnectorScope
  grantedPermissions: string[]
  lastSuccessfulSyncAt?: string
  lastPermissionCheckAt?: string
  indexedRecordCount: number
  errorMessage?: string
  isDemo: boolean
}

export type SyncStatus = 'queued' | 'running' | 'completed' | 'partial' | 'failed'

export interface SyncJob {
  id: string
  connectorId: SourceProvider
  status: SyncStatus
  trigger: 'setup' | 'manual' | 'retry'
  stage: number
  startedAt: string
  completedAt?: string
  recordsFetched: number
  recordsIndexed: number
  recordsSkipped: number
  errorCode?: string
  errorMessage?: string
}

export type ActivityKind =
  | 'investigation_created'
  | 'investigation_rerun'
  | 'investigation_updated'
  | 'investigation_resolved'
  | 'finding_reviewed'
  | 'issue_reviewed'
  | 'action_updated'
  | 'draft_saved'
  | 'draft_approved'
  | 'connector_connected'
  | 'connector_disconnected'
  | 'scope_changed'
  | 'sync_completed'
  | 'sync_failed'
  | 'demo_reset'

export interface ActivityEvent {
  id: string
  kind: ActivityKind
  label: string
  actor: string
  relatedType: 'investigation' | 'connector' | 'workspace'
  relatedId?: string
  relatedLabel: string
  at: string
  outcome: 'success' | 'warning' | 'failed'
  detail?: string
}

export interface WorkspaceSettings {
  workspaceName: string
  timezone: string
  simulateApiFailure: boolean
}

export interface MockState {
  schemaVersion: number
  investigations: Investigation[]
  findings: Finding[]
  timeline: TimelineEvent[]
  commitments: Commitment[]
  gaps: Gap[]
  contradictions: Contradiction[]
  actions: RecommendedAction[]
  drafts: ResponseDraft[]
  connectors: Connector[]
  syncJobs: SyncJob[]
  activity: ActivityEvent[]
  settings: WorkspaceSettings
}
