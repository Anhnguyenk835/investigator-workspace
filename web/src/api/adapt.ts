import type {
  ActionDto,
  AnnotationDto,
  DirectoryDto,
  ChatMessageDto,
  ConversationDto,
  SupportCheckDto,
  ToolEventDto,
  CoverageDto,
  EvidenceDto,
  FindingDto,
  IntegrationDto,
  InvestigationDto,
} from '@/api/dto'
import { PROVIDER_FOR_SOURCE, isSupported } from '@/lib/providers'
import type {
  Annotation,
  ChatMessage,
  Conversation,
  ChatTool,
  Connector,
  ConnectorStatus,
  CoverageStatus,
  EvidenceRecord,
  Finding,
  InvestigationBundle,
  RecommendedAction,
  RecordType,
  SourceCoverage,
  SupportCheck,
  SourceProvider,
} from '@/types/investigator'
import type { DirectoryData } from '@/types/directory'

function providerOf(source: string): SourceProvider | undefined {
  return PROVIDER_FOR_SOURCE[source]
}

/** Which kind of record an id names, from the id scheme the connectors use. */
export function recordTypeOf(source: SourceProvider, id: string): RecordType {
  const comment = id.includes(':comment:')
  switch (source) {
    case 'gmail':
      return 'email'
    case 'slack':
      return 'chat_message'
    case 'jira':
      return comment ? 'issue_comment' : id.includes(':change:') ? 'issue_change' : 'issue'
    default:
      return comment ? 'page_comment' : 'page'
  }
}

export function toEvidence(e: EvidenceDto): EvidenceRecord | undefined {
  const provider = providerOf(e.source)
  if (!provider) return undefined
  return {
    id: e.id,
    provider,
    recordType: recordTypeOf(provider, e.id),
    title: e.title,
    author: e.author ?? undefined,
    authorSide: e.author_side ?? undefined,
    authorRole: e.author_role ?? undefined,
    timestamp: e.occurred_at ?? undefined,
    timestampPrecision: e.timestamp_precision,
    excerpt: e.excerpt,
    trust: e.trust ?? 'normal',
    flaggedSpans: (e.quarantine ?? []).map((s) => ({ start: s.start, end: s.end })),
    url: e.url ?? undefined,
    threadId: e.thread_id ?? undefined,
  }
}

const COVERAGE: Record<CoverageDto['status'], CoverageStatus> = {
  searched: 'searched',
  partial: 'partial',
  no_matches: 'no_matches',
  not_connected: 'not_connected',
  permission_denied: 'permission_denied',
  failed: 'search_failed',
}

function toCoverage(c: CoverageDto): SourceCoverage | undefined {
  const provider = providerOf(c.source)
  return provider ? { provider, status: COVERAGE[c.status], warning: c.detail ?? undefined } : undefined
}

function toSupport(checks: SupportCheckDto[]): SupportCheck[] {
  return checks.map((c) => ({ evidenceId: c.evidence_id, verdict: c.verdict, quote: c.quote ?? undefined }))
}

function toFinding(f: FindingDto): Finding {
  return {
    id: f.id,
    title: f.title,
    claim: f.claim,
    explanation: f.explanation,
    status: f.status,
    basis: f.reasoning_type,
    supportingEvidenceIds: f.supporting_evidence_ids,
    contradictingEvidenceIds: f.contradicting_evidence_ids,
    reviewerNote: f.reviewer_note ?? undefined,
    reviewFlag: f.review_flag ?? undefined,
    support: toSupport(f.support),
    supportStatus: f.support_status,
  }
}

function toAction(a: ActionDto): RecommendedAction {
  return {
    id: a.id,
    title: a.title,
    rationale: a.rationale,
    suggestedOwner: a.owner ?? undefined,
    priority: a.priority,
    relatedFindingIds: a.related_finding_ids,
    evidenceIds: a.evidence_ids,
  }
}

/** The title shown in lists: the first line of the problem statement, shortened. */
export function titleOf(question: string): string {
  const line = question.split('\n')[0]?.trim() ?? ''
  const text = line || 'Untitled investigation'
  return text.length > 90 ? `${text.slice(0, 87).trimEnd()}...` : text
}

export function toInvestigation(d: InvestigationDto): InvestigationBundle['investigation'] {
  return {
    id: d.id,
    title: d.name?.trim() || titleOf(d.question),
    problemStatement: d.question,
    status: d.status,
    owner: d.owner ?? undefined,
    sample: d.sample === true,
    runNo: d.run_no,
    awaiting: d.awaiting ?? undefined,
    pending: d.pending ?? undefined,
    ticketIds: d.context.ticket_ids,
    customerId: d.context.customer_id ?? undefined,
    projectId: d.context.project_id ?? undefined,
    scopeNote: d.scope_note ?? undefined,
    dateFrom: d.context.date_from ?? undefined,
    dateTo: d.context.date_to ?? undefined,
    providers: (d.context.sources ?? []).map(providerOf).filter((p): p is SourceProvider => Boolean(p)),
    coverage: d.coverage.map(toCoverage).filter((c): c is SourceCoverage => Boolean(c)),
    summary: d.summary,
    searchNotes: d.search_notes ?? undefined,
    validationPassed: d.validation.passed,
    validationIssues: d.validation.issues.map((i) => ({
      findingId: i.finding_id ?? undefined,
      code: i.code,
      severity: i.severity,
      detail: i.detail,
    })),
    reviewerNotes: d.reviewer_notes,
    failureReason: d.error ?? undefined,
    createdAt: d.created_at,
    updatedAt: d.updated_at,
    resolvedBy: d.resolved_by ?? undefined,
    resolvedAt: d.resolved_at ?? undefined,
  }
}

export function toBundle(d: InvestigationDto): InvestigationBundle {
  const evidence = d.evidence.map(toEvidence).filter((e): e is EvidenceRecord => Boolean(e))
  const providerById = new Map(evidence.map((e) => [e.id, e.provider]))
  return {
    investigation: toInvestigation(d),
    evidence,
    findings: d.findings.map(toFinding),
    timeline: d.timeline.map((t) => ({
      id: t.id,
      title: t.title,
      description: t.summary,
      eventType: t.event_type as InvestigationBundle['timeline'][number]['eventType'],
      occurredAt: t.occurred_at ?? undefined,
      precision: t.timestamp_precision,
      actor: t.actor ?? undefined,
      provider: providerById.get(t.evidence_ids[0] ?? ''),
      evidenceIds: t.evidence_ids,
      support: toSupport(t.support),
      supportStatus: t.support_status,
    })),
    commitments: d.commitments.map((c) => ({
      id: c.id,
      statement: c.description,
      committedBy: c.committed_by ?? undefined,
      owner: c.owner ?? undefined,
      promisedAt: c.promised_at ?? undefined,
      dueDate: c.due_date ?? undefined,
      basis: c.basis,
      status: c.status,
      evidenceIds: c.evidence_ids,
      fulfilledByEvidenceIds: c.fulfilled_by_evidence_ids,
      support: toSupport(c.support),
      supportStatus: c.support_status,
    })),
    blockers: d.blockers.map((b) => ({
      id: b.id,
      description: b.description,
      kind: b.kind,
      basis: b.basis,
      evidenceIds: b.evidence_ids,
    })),
    gaps: d.gaps.map((g) => ({
      id: g.id,
      missing: g.what_missing,
      whyItMatters: g.why_it_matters,
      resolvingEvidence: g.resolving_evidence,
      followUp: g.follow_up,
      origin: g.origin,
    })),
    contradictions: d.conflicts.map((c) => ({
      id: c.id,
      claimA: { text: c.claim_a.text, evidenceIds: c.claim_a.evidence_ids },
      claimB: { text: c.claim_b.text, evidenceIds: c.claim_b.evidence_ids },
      explanation: c.why,
      resolved: c.resolution === 'resolved',
    })),
    actions: d.actions.map(toAction),
    draft: { body: d.draft, status: d.draft_status, warnings: d.draft_warnings },
  }
}

const CONNECTOR_STATUS: Record<IntegrationDto['state'], ConnectorStatus> = {
  not_configured: 'unavailable',
  not_connected: 'not_connected',
  connected: 'connected',
  reauth_required: 'reauth_required',
}

/** One card per source: Jira and Confluence both come from the one Atlassian connection. */
export function toConnectors(integrations: IntegrationDto[]): Connector[] {
  return integrations.flatMap((i) => {
    const sources = i.sources.map(providerOf).filter((p): p is SourceProvider => Boolean(p) && isSupported(p as SourceProvider))
    return sources.map<Connector>((provider) => ({
      provider,
      integration: i.provider,
      sharedWith: sources.filter((s) => s !== provider),
      status: CONNECTOR_STATUS[i.state],
      account: i.account ?? undefined,
      scopes: i.scopes,
      connectedAt: i.connected_at ?? undefined,
    }))
  })
}

export function toChatTool(t: ToolEventDto): ChatTool {
  return {
    tool: t.tool,
    source: t.source ? providerOf(t.source) : undefined,
    status: t.status,
    records: t.records,
    newRecords: t.new_records,
    note: t.note ?? undefined,
  }
}

export function toConversation(d: ConversationDto): Conversation {
  return { id: d.id, title: d.title, createdAt: d.created_at, updatedAt: d.updated_at, messageCount: d.message_count }
}

/** A stored chat message, plus the records its answer found that the investigation did not hold. */
export function toChatMessage(d: ChatMessageDto): { message: ChatMessage; evidence: EvidenceRecord[] } {
  return {
    message: {
      id: d.id,
      role: d.role,
      content: d.content,
      citations: d.citations,
      warnings: d.warnings,
      tools: d.tools.map(toChatTool),
      createdAt: d.created_at,
    },
    evidence: d.new_evidence.map(toEvidence).filter((e): e is EvidenceRecord => Boolean(e)),
  }
}

export function toDirectory(d: DirectoryDto): DirectoryData {
  return {
    customers: d.customers.map((c) => ({ id: c.id, name: c.name, aliases: c.aliases, emailDomains: c.email_domains })),
    projects: d.projects.map((p) => ({
      id: p.id,
      customerId: p.customer_id ?? undefined,
      name: p.name,
      aliases: p.aliases,
      ticketPrefixes: p.ticket_prefixes,
      jiraProjects: p.jira_projects,
      jiraLabels: p.jira_labels,
      slackChannelIds: p.slack_channel_ids,
      gmailLabels: p.gmail_labels,
      confluenceSpaces: p.confluence_spaces,
    })),
    people: d.people.map((q) => ({
      id: q.id,
      name: q.name,
      aliases: q.aliases,
      emails: q.emails,
      slackIds: q.slack_ids,
      jiraAccountIds: q.jira_account_ids,
      side: q.side,
      role: q.role ?? undefined,
      customerId: q.customer_id ?? undefined,
    })),
  }
}

export function toAnnotation(a: AnnotationDto): Annotation {
  return { id: a.id, targetId: a.target_id, kind: a.kind, text: a.text, author: a.author, createdAt: a.created_at }
}
