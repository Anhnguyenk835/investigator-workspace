/** The shapes the UI renders. `src/api/adapt.ts` builds them from the API's responses. */

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
  | 'issue_change'
  | 'issue_comment'
  | 'page'
  | 'page_comment'

export type TimestampPrecision = 'exact' | 'date_only' | 'unknown'

export interface EvidenceRecord {
  id: string
  provider: SourceProvider
  recordType: RecordType
  title: string
  author?: string
  /** Whether the directory knows the author as the customer's or ours. */
  authorSide?: 'customer' | 'internal' | 'third_party'
  authorRole?: string
  /** Absent when the source gave no time. Never filled in by the UI. */
  timestamp?: string
  timestampPrecision: TimestampPrecision
  excerpt: string
  /** `flagged`: the text reads as instructions to an AI. `tainted`: those parts were also withheld from the AI. */
  trust: 'normal' | 'flagged' | 'tainted'
  /** Character ranges of `excerpt` that read as instructions to an AI. */
  flaggedSpans: { start: number; end: number }[]
  url?: string
  threadId?: string
}

export type InvestigationStatus = 'queued' | 'investigating' | 'needs_review' | 'blocked' | 'resolved' | 'failed'

/** What a paused run is waiting for. */
export type Awaiting = 'clarification' | 'review' | 'draft_approval'

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
  warning?: string
}

export interface ValidationIssue {
  findingId?: string
  code: string
  severity: 'error' | 'warning'
  detail: string
}

export interface Investigation {
  id: string
  /** First line of the problem statement; the API has no separate title. */
  title: string
  problemStatement: string
  status: InvestigationStatus
  /** Who is looking after it: a name a person set, not an account. */
  owner?: string
  /** A shared sample in the demo: read-only for everyone. */
  sample?: boolean
  runNo: number
  awaiting?: Awaiting
  pending?: Record<string, unknown>
  ticketIds: string[]
  customerId?: string
  projectId?: string
  /** How the case was narrowed, in words (set when the directory matched the question). */
  scopeNote?: string
  dateFrom?: string
  dateTo?: string
  /** Sources the person limited the run to; empty means every connected source. */
  providers: SourceProvider[]
  coverage: SourceCoverage[]
  summary: string
  searchNotes?: string
  validationPassed: boolean
  validationIssues: ValidationIssue[]
  reviewerNotes: string[]
  failureReason?: string
  createdAt: string
  updatedAt: string
  resolvedBy?: string
  resolvedAt?: string
}

/** Whether the cited records actually say what a claim says, as judged against their text. */
export type SupportStatus = 'unchecked' | 'supported' | 'partial' | 'unsupported'

export interface SupportCheck {
  evidenceId: string
  verdict: 'supported' | 'partial' | 'unsupported'
  /** The passage of the record that backs the claim, copied from it. */
  quote?: string
}

export type FindingStatus = 'verified' | 'needs_verification' | 'conflicting' | 'unknown'

export interface Finding {
  id: string
  title: string
  claim: string
  explanation: string
  status: FindingStatus
  basis: 'direct' | 'inference'
  supportingEvidenceIds: string[]
  contradictingEvidenceIds: string[]
  reviewerNote?: string
  /** Why this deserves a look before it is believed (set by the checks, not by a person). */
  reviewFlag?: string
  support: SupportCheck[]
  supportStatus: SupportStatus
}

export type TimelineEventType =
  | 'customer_request'
  | 'internal_discussion'
  | 'commitment'
  | 'assignment'
  | 'status_change'
  | 'document_update'
  | 'blocker'
  | 'deadline_change'
  | 'delivery'
  | 'escalation'
  | 'other'

export interface TimelineEvent {
  id: string
  title: string
  description: string
  eventType: TimelineEventType
  /** From the cited evidence. Absent when no cited record has a time. */
  occurredAt?: string
  precision: TimestampPrecision
  actor?: string
  provider?: SourceProvider
  evidenceIds: string[]
  support: SupportCheck[]
  supportStatus: SupportStatus
}

export type CommitmentStatus = 'confirmed' | 'fulfilled' | 'at_risk' | 'overdue' | 'unverified'

export interface Commitment {
  id: string
  statement: string
  committedBy?: string
  owner?: string
  promisedAt?: string
  dueDate?: string
  basis: 'explicit' | 'inferred'
  status: CommitmentStatus
  evidenceIds: string[]
  fulfilledByEvidenceIds: string[]
  support: SupportCheck[]
  supportStatus: SupportStatus
}

export interface Blocker {
  id: string
  description: string
  kind: 'blocker' | 'dependency' | 'probable_cause'
  basis: 'stated' | 'inferred'
  evidenceIds: string[]
}

export interface Gap {
  id: string
  missing: string
  whyItMatters: string
  resolvingEvidence: string
  followUp: string
  origin: 'coverage' | 'analysis' | 'quality'
}

export interface ContradictionClaim {
  text: string
  evidenceIds: string[]
}

export interface Contradiction {
  id: string
  claimA: ContradictionClaim
  claimB: ContradictionClaim
  explanation: string
  resolved: boolean
}

export interface RecommendedAction {
  id: string
  title: string
  rationale: string
  suggestedOwner?: string
  priority: 'low' | 'medium' | 'high'
  relatedFindingIds: string[]
  evidenceIds: string[]
}

export type DraftStatus = 'none' | 'drafted' | 'approved' | 'changes_requested' | 'not_possible'

export interface ResponseDraft {
  body: string
  status: DraftStatus
  warnings: string[]
}

/** Connection state of one source, derived from the provider connection that unlocks it. */
export type ConnectorStatus = 'not_connected' | 'connected' | 'reauth_required' | 'unavailable'

export interface Connector {
  provider: SourceProvider
  /** The OAuth connection that serves this source (Jira and Confluence share one). */
  integration: string
  /** Every source that connection unlocks. */
  sharedWith: SourceProvider[]
  status: ConnectorStatus
  account?: string
  scopes: string[]
  connectedAt?: string
}

export interface InvestigationBundle {
  investigation: Investigation
  evidence: EvidenceRecord[]
  findings: Finding[]
  timeline: TimelineEvent[]
  commitments: Commitment[]
  blockers: Blocker[]
  gaps: Gap[]
  contradictions: Contradiction[]
  actions: RecommendedAction[]
  draft: ResponseDraft
}

export interface WorkspaceSettings {
  timezone: string
}

/** One search the assistant ran while answering. Metadata only; no content. */
export interface ChatTool {
  tool: string
  source?: SourceProvider
  status: string
  records: number
  newRecords: number
  note?: string
}

/** One thread of questions and answers about an investigation. */
export interface Conversation {
  id: string
  title: string
  createdAt: string
  updatedAt: string
  messageCount: number
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations: string[]
  warnings: string[]
  tools: ChatTool[]
  createdAt: string
}

export type AnnotationKind = 'note' | 'reviewed' | 'disputed'

/** A note, review or dispute a person attached to a claim. */
export interface Annotation {
  id: string
  targetId: string
  kind: AnnotationKind
  text: string
  author: string
  createdAt: string
}
