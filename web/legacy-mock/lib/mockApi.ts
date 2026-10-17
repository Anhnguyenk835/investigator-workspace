import { evidenceById, mockEvidence } from '@/data/mockEvidence'
import { defaultScopeFor, isSupported, providerMeta } from '@/data/mockConnectors'
import { removeKey } from '@/lib/storage'
import { clearAgentConversations } from '@/lib/mock/agentStore'
import type { NewActionInput } from '@/types/agent'
import {
  completeRun,
  computeCoverage,
  customerKeyFor,
  isConnected,
  isSearchable,
} from '@/lib/mock/analysis'
import { generateDraft } from '@/lib/mock/draft'
import {
  CURRENT_USER,
  RUN_STAGES,
  SYNC_STAGES,
  clone,
  createSeedState,
  getState,
  logActivity,
  mutate,
  newId,
  nowIso,
  registerTickHandler,
  replaceState,
  resumeJobs,
  subscribe,
} from '@/lib/mock/store'
import type {
  ActionStatus,
  Commitment,
  Connector,
  ConnectorScope,
  Contradiction,
  EvidenceRecord,
  Finding,
  Gap,
  Investigation,
  InvestigationStatus,
  MockState,
  RecommendedAction,
  ResponseDraft,
  SourceCoverage,
  SourceProvider,
  SyncJob,
  TimelineEvent,
  WorkspaceSettings,
  ActivityEvent,
} from '@/types/investigator'

/**
 * Mock service layer. Everything the UI knows about data goes through this file
 * and returns promises, so it can be swapped for real HTTP calls later.
 * Nothing here talks to a network.
 */

export interface InvestigationBundle {
  investigation: Investigation
  findings: Finding[]
  timeline: TimelineEvent[]
  commitments: Commitment[]
  gaps: Gap[]
  contradictions: Contradiction[]
  actions: RecommendedAction[]
  draft: ResponseDraft | null
}

export interface CreateInvestigationInput {
  problemStatement: string
  customerName?: string
  projectName?: string
  ticketId?: string
  people?: string
  dateFrom?: string
  dateTo?: string
  selectedProviders: SourceProvider[]
}

export interface EvidenceFilters {
  search?: string
  provider?: SourceProvider | 'all'
  recordType?: string
  customer?: string
  dateFrom?: string
  dateTo?: string
  indexStatus?: string
}

export interface EvidenceRelations {
  investigations: { id: string; title: string }[]
  findings: Finding[]
  events: TimelineEvent[]
}

export interface TestConnectionResult {
  ok: boolean
  permissions: string[]
  recordEstimate: number
  errorCode?: string
  errorMessage?: string
}

const tick = () => Promise.resolve()

function guard(): void {
  if (getState().settings.simulateApiFailure) {
    throw new Error('Simulated API failure. The request did not complete. Turn this off in Settings.')
  }
}

function must<T>(value: T | undefined, what: string): T {
  if (value === undefined) throw new Error(`${what} was not found.`)
  return value
}

const findInv = (s: MockState, id: string) =>
  must(s.investigations.find((i) => i.id === id), 'Investigation')
const findConn = (s: MockState, id: string) =>
  must(s.connectors.find((c) => c.id === id), 'Connector')

function touch(inv: Investigation, material = false): void {
  inv.updatedAt = nowIso()
  if (material) inv.analysisVersion += 1
}

const connectorName = (id: SourceProvider) => providerMeta[id].name

function requireSupported(provider: SourceProvider): void {
  if (!isSupported(provider)) throw new Error(`${providerMeta[provider].name} is coming soon and cannot be connected yet.`)
}

// ───────────────────────── job scheduler ─────────────────────────

function baseRecordCount(provider: SourceProvider): number {
  return 120 + ([...provider].reduce((n, ch) => n + ch.charCodeAt(0), 0) % 380)
}

function finishSync(s: MockState, job: SyncJob): void {
  const connector = s.connectors.find((c) => c.id === job.connectorId)
  if (!connector) {
    job.status = 'failed'
    job.errorMessage = 'The connector no longer exists.'
    return
  }
  const name = connectorName(connector.id)
  const prior = connector.indexedRecordCount
  const fetched =
    job.trigger === 'setup'
      ? baseRecordCount(connector.id) * Math.max(1, connector.scope.resources.length)
      : Math.max(prior, baseRecordCount(connector.id)) + 12
  const partial = connector.id === 'jira'
  const skipped = partial ? Math.round(fetched * 0.07) : job.trigger === 'setup' ? Math.round(fetched * 0.01) : 0
  const completedAt = nowIso()

  job.completedAt = completedAt
  job.recordsFetched = fetched
  job.recordsSkipped = skipped
  job.recordsIndexed = fetched - skipped
  job.stage = SYNC_STAGES.length - 1

  connector.indexedRecordCount = job.recordsIndexed
  connector.lastSuccessfulSyncAt = completedAt
  connector.lastPermissionCheckAt = completedAt

  if (partial) {
    job.status = 'partial'
    job.errorCode = 'PARTIAL_PERMISSION'
    job.errorMessage = `Comment history for project ENG could not be read for ${skipped} issues. The connected account lacks access to those comments.`
    connector.status = 'needs_attention'
    connector.errorMessage = 'The last sync was partial: comment history for project ENG could not be fully read.'
  } else {
    job.status = 'completed'
    connector.status = 'sync_completed'
    connector.errorMessage = undefined
  }
  logActivity(s, {
    kind: 'sync_completed',
    label: partial ? 'Sync partially completed' : 'Sync completed',
    actor: 'System',
    relatedType: 'connector',
    relatedId: connector.id,
    relatedLabel: name,
    outcome: partial ? 'warning' : 'success',
    detail: `${job.recordsIndexed.toLocaleString('en-US')} indexed, ${skipped.toLocaleString('en-US')} skipped (simulated).`,
  })
}

registerTickHandler((s) => {
  for (const inv of s.investigations) {
    if (!inv.job) continue
    inv.job.stage += 1
    if (inv.job.stage >= RUN_STAGES.length) completeRun(s, inv)
  }
  for (const job of s.syncJobs) {
    if (job.status !== 'running' && job.status !== 'queued') continue
    job.status = 'running'
    job.stage += 1
    if (job.stage >= SYNC_STAGES.length - 1) finishSync(s, job)
  }
})

function startSyncJob(s: MockState, connector: Connector, trigger: SyncJob['trigger']): SyncJob {
  const job: SyncJob = {
    id: `sync-${String(s.syncJobs.length + 1).padStart(4, '0')}`,
    connectorId: connector.id,
    status: 'running',
    trigger,
    stage: 0,
    startedAt: nowIso(),
    recordsFetched: 0,
    recordsIndexed: 0,
    recordsSkipped: 0,
  }
  s.syncJobs.push(job)
  connector.status = 'syncing'
  connector.errorMessage = undefined
  return job
}

function startRun(inv: Investigation, kind: 'initial' | 'rerun'): void {
  if (inv.job) throw new Error('A run is already in progress for this investigation.')
  inv.job = { kind, stage: 0, startedAt: nowIso() }
  inv.status = 'investigating'
  inv.failureReason = undefined
  touch(inv)
}

// ───────────────────────── public API ─────────────────────────

export const mockApi = {
  subscribe,

  // ── investigations ──
  async listInvestigations(): Promise<Investigation[]> {
    await tick()
    guard()
    return clone(getState().investigations)
  },

  async getInvestigationBundle(id: string): Promise<InvestigationBundle | null> {
    await tick()
    guard()
    const s = getState()
    const investigation = s.investigations.find((i) => i.id === id)
    if (!investigation) return null
    const mine = <T extends { investigationId: string }>(items: T[]) =>
      items.filter((x) => x.investigationId === id)
    return clone({
      investigation,
      findings: mine(s.findings),
      timeline: mine(s.timeline),
      commitments: mine(s.commitments),
      gaps: mine(s.gaps),
      contradictions: mine(s.contradictions),
      actions: mine(s.actions),
      draft: s.drafts.find((d) => d.investigationId === id) ?? null,
    })
  },

  async createInvestigation(input: CreateInvestigationInput): Promise<Investigation> {
    await tick()
    const problem = input.problemStatement.trim()
    if (!problem) throw new Error('Describe what happened before starting.')
    return mutate((s) => {
      const at = nowIso()
      const title =
        input.projectName?.trim() ||
        (problem.length > 64 ? `${problem.slice(0, 61).trimEnd()}…` : problem)
      const inv: Investigation = {
        id: newId('inv'),
        title,
        problemStatement: problem,
        customerName: input.customerName?.trim() || undefined,
        projectName: input.projectName?.trim() || undefined,
        ticketId: input.ticketId?.trim() || undefined,
        people: input.people?.trim() || undefined,
        dateFrom: input.dateFrom || undefined,
        dateTo: input.dateTo || undefined,
        owner: CURRENT_USER,
        status: 'queued',
        selectedProviders: input.selectedProviders,
        coverage: [],
        summary: null,
        createdAt: at,
        updatedAt: at,
        runCount: 0,
        analysisVersion: 0,
      }
      s.investigations.push(inv)
      startRun(inv, 'initial')
      logActivity(s, {
        kind: 'investigation_created',
        label: 'Investigation created',
        relatedType: 'investigation',
        relatedId: inv.id,
        relatedLabel: inv.title,
      })
      return clone(inv)
    })
  },

  async updateInvestigation(
    id: string,
    patch: Partial<Pick<Investigation, 'title' | 'problemStatement' | 'customerName' | 'projectName' | 'ticketId' | 'people' | 'owner'>>,
  ): Promise<Investigation> {
    await tick()
    return mutate((s) => {
      const inv = findInv(s, id)
      if (patch.problemStatement !== undefined && !patch.problemStatement.trim()) {
        throw new Error('The problem statement cannot be empty.')
      }
      Object.assign(inv, patch)
      touch(inv)
      logActivity(s, {
        kind: 'investigation_updated',
        label: 'Context edited',
        relatedType: 'investigation',
        relatedId: id,
        relatedLabel: inv.title,
        detail: 'Re-run the investigation to apply the new context to the search.',
      })
      return clone(inv)
    })
  },

  /** Starts a simulated run (initial for draft/failed cases, otherwise a re-run). */
  async runInvestigation(id: string): Promise<Investigation> {
    await tick()
    return mutate((s) => {
      const inv = findInv(s, id)
      if (inv.status === 'resolved') throw new Error('Reopen this investigation before re-running it.')
      const kind = inv.runCount === 0 ? 'initial' : 'rerun'
      startRun(inv, kind)
      if (kind === 'rerun') {
        logActivity(s, {
          kind: 'investigation_rerun',
          label: 'Investigation re-run started',
          relatedType: 'investigation',
          relatedId: id,
          relatedLabel: inv.title,
          detail: 'Simulated run. Reviewed notes and actions are kept.',
        })
      }
      return clone(inv)
    })
  },

  async retrySourceSearch(id: string, provider: SourceProvider): Promise<SourceCoverage> {
    await tick()
    return mutate((s) => {
      const inv = findInv(s, id)
      const connector = s.connectors.find((c) => c.id === provider)
      if (!connector || !isConnected(connector)) {
        throw new Error(`${connectorName(provider)} is not available. Connect or reconnect it first.`)
      }
      if (connector.status === 'sync_failed' || connector.status === 'permission_revoked') {
        throw new Error(`${connectorName(provider)} needs attention before it can be searched.`)
      }
      const [fresh] = computeCoverage(s, [provider], customerKeyFor(inv))
      inv.coverage = inv.coverage.some((c) => c.provider === provider)
        ? inv.coverage.map((c) => (c.provider === provider ? fresh : c))
        : [...inv.coverage, fresh]
      if (!inv.selectedProviders.includes(provider)) inv.selectedProviders.push(provider)
      touch(inv, true)
      logActivity(s, {
        kind: 'investigation_rerun',
        label: 'Source search retried',
        relatedType: 'investigation',
        relatedId: id,
        relatedLabel: inv.title,
        detail: `${connectorName(provider)}: ${fresh.status.replace('_', ' ')}.`,
        outcome: isSearchable(fresh) ? 'success' : 'warning',
      })
      return clone(fresh)
    })
  },

  async setInvestigationStatus(id: string, status: Extract<InvestigationStatus, 'resolved' | 'needs_review'>): Promise<Investigation> {
    await tick()
    return mutate((s) => {
      const inv = findInv(s, id)
      if (status === 'resolved') {
        const draft = s.drafts.find((d) => d.investigationId === id)
        const issues = s.contradictions.filter((c) => c.investigationId === id && c.review !== 'reviewed')
        if (!inv.summaryReviewedAt) throw new Error('Review the summary before resolving.')
        if (issues.length > 0) throw new Error('Review all contradictions before resolving.')
        if (draft?.status !== 'approved') throw new Error('Approve the customer draft before resolving.')
        inv.status = 'resolved'
        inv.resolvedAt = nowIso()
        inv.resolvedBy = CURRENT_USER
      } else {
        inv.status = 'needs_review'
        inv.resolvedAt = undefined
        inv.resolvedBy = undefined
      }
      touch(inv)
      logActivity(s, {
        kind: 'investigation_resolved',
        label: status === 'resolved' ? 'Investigation resolved' : 'Investigation reopened',
        relatedType: 'investigation',
        relatedId: id,
        relatedLabel: inv.title,
      })
      return clone(inv)
    })
  },

  async markSummaryReviewed(id: string, reviewed: boolean): Promise<Investigation> {
    await tick()
    return mutate((s) => {
      const inv = findInv(s, id)
      if (!inv.summary) throw new Error('There is no summary to review.')
      inv.summaryReviewedBy = reviewed ? CURRENT_USER : undefined
      inv.summaryReviewedAt = reviewed ? nowIso() : undefined
      touch(inv)
      logActivity(s, {
        kind: 'finding_reviewed',
        label: reviewed ? 'Summary reviewed' : 'Summary review withdrawn',
        relatedType: 'investigation',
        relatedId: id,
        relatedLabel: inv.title,
      })
      return clone(inv)
    })
  },

  // ── review items ──
  async updateFinding(
    id: string,
    patch: { reviewerNote?: string; reviewed?: boolean },
  ): Promise<Finding> {
    await tick()
    return mutate((s) => {
      const f = must(s.findings.find((x) => x.id === id), 'Finding')
      if (patch.reviewerNote !== undefined) f.reviewerNote = patch.reviewerNote.trim() || undefined
      if (patch.reviewed !== undefined) {
        f.reviewedBy = patch.reviewed ? CURRENT_USER : undefined
        f.reviewedAt = patch.reviewed ? nowIso() : undefined
      }
      const inv = findInv(s, f.investigationId)
      touch(inv, true)
      logActivity(s, {
        kind: 'finding_reviewed',
        label: patch.reviewed === false ? 'Finding review withdrawn' : 'Finding reviewed',
        relatedType: 'investigation',
        relatedId: inv.id,
        relatedLabel: inv.title,
        detail: f.title,
      })
      return clone(f)
    })
  },

  async updateCommitment(id: string, patch: { reviewerNote: string }): Promise<Commitment> {
    await tick()
    return mutate((s) => {
      const c = must(s.commitments.find((x) => x.id === id), 'Commitment')
      c.reviewerNote = patch.reviewerNote.trim() || undefined
      touch(findInv(s, c.investigationId), true)
      return clone(c)
    })
  },

  async updateGap(id: string, patch: { review?: Gap['review']; reviewerNote?: string }): Promise<Gap> {
    await tick()
    return mutate((s) => {
      const g = must(s.gaps.find((x) => x.id === id), 'Gap')
      if (patch.review) g.review = patch.review
      if (patch.reviewerNote !== undefined) g.reviewerNote = patch.reviewerNote.trim() || undefined
      const inv = findInv(s, g.investigationId)
      touch(inv, true)
      logActivity(s, {
        kind: 'issue_reviewed',
        label: `Gap marked ${g.review}`,
        relatedType: 'investigation',
        relatedId: inv.id,
        relatedLabel: inv.title,
        detail: g.missing,
      })
      return clone(g)
    })
  },

  async updateContradiction(
    id: string,
    patch: { review?: Contradiction['review']; reviewerNote?: string },
  ): Promise<Contradiction> {
    await tick()
    return mutate((s) => {
      const c = must(s.contradictions.find((x) => x.id === id), 'Contradiction')
      if (patch.review) c.review = patch.review
      if (patch.reviewerNote !== undefined) c.reviewerNote = patch.reviewerNote.trim() || undefined
      const inv = findInv(s, c.investigationId)
      touch(inv, true)
      logActivity(s, {
        kind: 'issue_reviewed',
        label: `Contradiction marked ${c.review}`,
        relatedType: 'investigation',
        relatedId: inv.id,
        relatedLabel: inv.title,
        detail: c.title,
      })
      return clone(c)
    })
  },

  async updateAction(
    id: string,
    patch: { status?: ActionStatus; note?: string },
  ): Promise<RecommendedAction> {
    await tick()
    return mutate((s) => {
      const a = must(s.actions.find((x) => x.id === id), 'Action')
      if (patch.status) {
        const allowed: Record<ActionStatus, ActionStatus[]> = {
          suggested: ['accepted', 'dismissed'],
          accepted: ['in_progress', 'completed', 'dismissed'],
          in_progress: ['completed', 'accepted', 'dismissed'],
          completed: ['in_progress'],
          dismissed: ['suggested'],
        }
        if (!allowed[a.status].includes(patch.status)) {
          throw new Error(`An action that is ${a.status.replace('_', ' ')} cannot become ${patch.status.replace('_', ' ')}.`)
        }
        a.status = patch.status
      }
      if (patch.note?.trim()) {
        a.notes.push({ id: newId('note'), text: patch.note.trim(), author: CURRENT_USER, at: nowIso() })
      }
      a.updatedAt = nowIso()
      const inv = findInv(s, a.investigationId)
      touch(inv)
      logActivity(s, {
        kind: 'action_updated',
        label: patch.status ? `Action ${patch.status.replace('_', ' ')}` : 'Action note added',
        relatedType: 'investigation',
        relatedId: inv.id,
        relatedLabel: inv.title,
        detail: a.title,
      })
      return clone(a)
    })
  },

  async createAction(investigationId: string, input: NewActionInput): Promise<RecommendedAction> {
    await tick()
    guard()
    return mutate((s) => {
      const inv = findInv(s, investigationId)
      const existing = s.actions.find((a) => a.id === input.id)
      if (existing) return clone(existing)
      const at = nowIso()
      const action: RecommendedAction = {
        id: input.id,
        investigationId,
        title: input.title,
        rationale: input.rationale,
        suggestedOwner: undefined,
        priority: input.priority,
        relatedFindingIds: input.relatedFindingIds,
        relatedEvidenceIds: input.relatedEvidenceIds,
        customerStep: input.customerStep,
        status: 'suggested',
        notes: [],
        createdAt: at,
        updatedAt: at,
      }
      s.actions.push(action)
      touch(inv)
      logActivity(s, {
        kind: 'action_updated',
        label: 'Action added from agent suggestion',
        relatedType: 'investigation',
        relatedId: inv.id,
        relatedLabel: inv.title,
        detail: action.title,
      })
      return clone(action)
    })
  },

  async addInvestigationNote(investigationId: string, noteId: string, text: string): Promise<Investigation> {
    await tick()
    guard()
    return mutate((s) => {
      const inv = findInv(s, investigationId)
      inv.notes = inv.notes ?? []
      if (!inv.notes.some((n) => n.id === noteId)) {
        inv.notes.push({ id: noteId, text: text.trim(), author: CURRENT_USER, at: nowIso() })
        touch(inv)
        logActivity(s, {
          kind: 'investigation_updated',
          label: 'Investigation note added from agent',
          relatedType: 'investigation',
          relatedId: inv.id,
          relatedLabel: inv.title,
        })
      }
      return clone(inv)
    })
  },

  // ── customer draft ──
  async ensureDraft(investigationId: string): Promise<ResponseDraft> {
    await tick()
    const existing = getState().drafts.find((d) => d.investigationId === investigationId)
    if (existing) return clone(existing)
    return mutate((s) => {
      const inv = findInv(s, investigationId)
      const body = generateDraft(s, investigationId)
      const draft: ResponseDraft = {
        investigationId,
        body,
        generatedBody: body,
        status: 'draft',
        basedOnVersion: inv.analysisVersion,
        savedAt: nowIso(),
      }
      s.drafts.push(draft)
      return clone(draft)
    })
  },

  async saveDraft(investigationId: string, body: string): Promise<ResponseDraft> {
    await tick()
    return mutate((s) => {
      const d = must(s.drafts.find((x) => x.investigationId === investigationId), 'Draft')
      if (!body.trim()) throw new Error('The draft cannot be empty.')
      if (body !== d.body) {
        d.body = body
        d.status = 'draft'
        d.reviewedAt = d.reviewedBy = d.approvedAt = d.approvedBy = undefined
      }
      d.savedAt = nowIso()
      const inv = findInv(s, investigationId)
      logActivity(s, {
        kind: 'draft_saved',
        label: 'Draft saved',
        relatedType: 'investigation',
        relatedId: inv.id,
        relatedLabel: inv.title,
      })
      return clone(d)
    })
  },

  async regenerateDraft(investigationId: string): Promise<ResponseDraft> {
    await tick()
    return mutate((s) => {
      const d = must(s.drafts.find((x) => x.investigationId === investigationId), 'Draft')
      const inv = findInv(s, investigationId)
      const body = generateDraft(s, investigationId)
      Object.assign(d, {
        body,
        generatedBody: body,
        status: 'draft',
        basedOnVersion: inv.analysisVersion,
        savedAt: nowIso(),
        reviewedAt: undefined,
        reviewedBy: undefined,
        approvedAt: undefined,
        approvedBy: undefined,
      })
      return clone(d)
    })
  },

  async setDraftStatus(investigationId: string, status: 'reviewed' | 'approved'): Promise<ResponseDraft> {
    await tick()
    return mutate((s) => {
      const d = must(s.drafts.find((x) => x.investigationId === investigationId), 'Draft')
      const inv = findInv(s, investigationId)
      if (status === 'reviewed') {
        d.status = 'reviewed'
        d.reviewedBy = CURRENT_USER
        d.reviewedAt = nowIso()
        d.basedOnVersion = inv.analysisVersion
      } else {
        if (d.status !== 'reviewed') throw new Error('Mark the draft as reviewed before approving it.')
        d.status = 'approved'
        d.approvedBy = CURRENT_USER
        d.approvedAt = nowIso()
        d.basedOnVersion = inv.analysisVersion
        logActivity(s, {
          kind: 'draft_approved',
          label: 'Draft approved',
          relatedType: 'investigation',
          relatedId: inv.id,
          relatedLabel: inv.title,
          detail: 'Approved for manual sending. Nothing was sent.',
        })
      }
      return clone(d)
    })
  },

  // ── evidence ──
  async listEvidence(filters: EvidenceFilters = {}): Promise<EvidenceRecord[]> {
    await tick()
    guard()
    const q = filters.search?.trim().toLowerCase()
    return clone(
      mockEvidence
        .filter((e) => {
          if (filters.provider && filters.provider !== 'all' && e.provider !== filters.provider) return false
          if (filters.recordType && filters.recordType !== 'all' && e.recordType !== filters.recordType) return false
          if (filters.customer && filters.customer !== 'all' && e.customerName !== filters.customer) return false
          if (filters.indexStatus && filters.indexStatus !== 'all' && e.indexStatus !== filters.indexStatus) return false
          if (filters.dateFrom && e.timestamp < filters.dateFrom) return false
          if (filters.dateTo && e.timestamp > `${filters.dateTo}T23:59:59Z`) return false
          if (q) {
            const hay = `${e.title} ${e.author ?? ''} ${e.excerpt} ${e.externalRecordId} ${e.customerName} ${e.projectName}`.toLowerCase()
            if (!hay.includes(q)) return false
          }
          return true
        })
        .sort((a, b) => b.timestamp.localeCompare(a.timestamp)),
    )
  },

  async getEvidence(id: string): Promise<EvidenceRecord | null> {
    await tick()
    guard()
    return clone(evidenceById.get(id) ?? null)
  },

  async getEvidenceRelations(id: string): Promise<EvidenceRelations> {
    await tick()
    guard()
    const s = getState()
    const findings = s.findings.filter(
      (f) => f.supportingEvidenceIds.includes(id) || f.contradictingEvidenceIds.includes(id),
    )
    const events = s.timeline.filter((t) => t.evidenceIds.includes(id))
    const ids = new Set([...findings.map((f) => f.investigationId), ...events.map((t) => t.investigationId)])
    return clone({
      findings,
      events,
      investigations: s.investigations.filter((i) => ids.has(i.id)).map((i) => ({ id: i.id, title: i.title })),
    })
  },

  // ── connectors ──
  async listConnectors(): Promise<Connector[]> {
    await tick()
    guard()
    return clone(getState().connectors)
  },

  async getConnector(id: string): Promise<Connector | null> {
    await tick()
    guard()
    return clone(getState().connectors.find((c) => c.id === id) ?? null)
  },

  async listSyncJobs(connectorId?: SourceProvider): Promise<SyncJob[]> {
    await tick()
    guard()
    return clone(
      getState()
        .syncJobs.filter((j) => !connectorId || j.connectorId === connectorId)
        .sort((a, b) => b.startedAt.localeCompare(a.startedAt) || b.id.localeCompare(a.id)),
    )
  },

  /** Setup step 1. Marks the connector as connecting; no credentials are involved. */
  async simulateConnection(provider: SourceProvider): Promise<Connector> {
    await tick()
    requireSupported(provider)
    return mutate((s) => {
      const c = findConn(s, provider)
      if (isConnected(c)) throw new Error(`${connectorName(provider)} is already connected.`)
      const meta = providerMeta[provider]
      c.status = 'connecting'
      c.accountLabel = meta.demoAccount
      c.workspaceLabel = meta.demoWorkspace
      c.scope = defaultScopeFor(provider)
      c.grantedPermissions = []
      c.errorMessage = undefined
      return clone(c)
    })
  },

  async cancelSetup(provider: SourceProvider): Promise<void> {
    await tick()
    mutate((s) => {
      const c = findConn(s, provider)
      if (c.status === 'connecting') {
        c.status = 'not_connected'
        c.accountLabel = c.workspaceLabel = undefined
        c.scope = { resources: [], dateRange: '90d', contentTypes: [], includeArchived: false }
      }
    })
  },

  async updateConnectorScope(provider: SourceProvider, scope: ConnectorScope, options: { log?: boolean } = {}): Promise<Connector> {
    await tick()
    if (scope.resources.length === 0) throw new Error('Select at least one item to include.')
    if (scope.contentTypes.length === 0) throw new Error('Select at least one content type.')
    return mutate((s) => {
      const c = findConn(s, provider)
      c.scope = clone(scope)
      if (options.log !== false && isConnected(c)) {
        logActivity(s, {
          kind: 'scope_changed',
          label: 'Scope changed',
          relatedType: 'connector',
          relatedId: provider,
          relatedLabel: connectorName(provider),
          detail: `${scope.resources.length} selected, ${scope.dateRange} range.`,
        })
      }
      return clone(c)
    })
  },

  /** Setup step 3. Deterministic: succeeds unless the scope is empty or a failure is requested. */
  async testConnection(provider: SourceProvider, options: { simulatePermissionError?: boolean } = {}): Promise<TestConnectionResult> {
    await tick()
    return mutate((s) => {
      const c = findConn(s, provider)
      const meta = providerMeta[provider]
      if (c.status !== 'connecting' && !isConnected(c)) {
        throw new Error('Start the connection before testing access.')
      }
      if (options.simulatePermissionError) {
        return { ok: false, permissions: [], recordEstimate: 0, errorCode: 'INSUFFICIENT_PERMISSIONS', errorMessage: `The demo account does not have permission to read the selected ${meta.resourceLabel.toLowerCase()}. Adjust the scope or retry.` }
      }
      if (c.scope.resources.length === 0) {
        return { ok: false, permissions: [], recordEstimate: 0, errorCode: 'UNSUPPORTED_SCOPE', errorMessage: 'No data scope is selected. Go back and choose at least one item.' }
      }
      c.grantedPermissions = [...meta.permissions]
      c.lastPermissionCheckAt = nowIso()
      return {
        ok: true,
        permissions: meta.permissions,
        recordEstimate: baseRecordCount(provider) * c.scope.resources.length,
      }
    })
  },

  async simulateSync(provider: SourceProvider, trigger: SyncJob['trigger'] = 'manual'): Promise<SyncJob> {
    await tick()
    requireSupported(provider)
    return mutate((s) => {
      const c = findConn(s, provider)
      const name = connectorName(provider)
      if (c.status === 'not_connected' || (c.status === 'connecting' && trigger !== 'setup')) {
        throw new Error(`${name} is not connected.`)
      }
      if (c.status === 'permission_revoked') throw new Error(`${name} access was revoked. Reconnect it before syncing.`)
      if (c.status === 'syncing') throw new Error(`A sync is already running for ${name}.`)
      const job = startSyncJob(s, c, trigger)
      if (trigger === 'setup') {
        c.status = 'syncing'
        logActivity(s, {
          kind: 'connector_connected',
          label: 'Connector connected (simulated)',
          relatedType: 'connector',
          relatedId: provider,
          relatedLabel: name,
          detail: 'Demo mode. No real account was linked.',
        })
      }
      return clone(job)
    })
  },

  async retrySync(jobId: string): Promise<SyncJob> {
    await tick()
    const s = getState()
    const old = must(s.syncJobs.find((j) => j.id === jobId), 'Sync job')
    if (old.status !== 'failed' && old.status !== 'partial') throw new Error('Only failed or partial syncs can be retried.')
    return mockApi.simulateSync(old.connectorId, 'retry')
  },

  /** Reauthorization is simulated: nothing is sent to a provider. */
  async reconnect(provider: SourceProvider): Promise<Connector> {
    await tick()
    requireSupported(provider)
    return mutate((s) => {
      const c = findConn(s, provider)
      if (c.status !== 'permission_revoked' && c.status !== 'sync_failed' && c.status !== 'needs_attention') {
        throw new Error(`${connectorName(provider)} does not need to be reconnected.`)
      }
      c.status = 'connected'
      c.errorMessage = undefined
      c.grantedPermissions = [...providerMeta[provider].permissions]
      c.lastPermissionCheckAt = nowIso()
      logActivity(s, {
        kind: 'connector_connected',
        label: 'Connector reauthorized (simulated)',
        relatedType: 'connector',
        relatedId: provider,
        relatedLabel: connectorName(provider),
        detail: 'Demo mode. Run a sync to refresh records.',
      })
      return clone(c)
    })
  },

  /** Disconnecting keeps existing demo evidence; retention is not modeled. */
  async disconnect(provider: SourceProvider): Promise<Connector> {
    await tick()
    return mutate((s) => {
      const c = findConn(s, provider)
      if (c.status === 'not_connected') throw new Error(`${connectorName(provider)} is already disconnected.`)
      for (const j of s.syncJobs) {
        if (j.connectorId === provider && (j.status === 'running' || j.status === 'queued')) {
          j.status = 'failed'
          j.completedAt = nowIso()
          j.errorCode = 'CANCELLED'
          j.errorMessage = 'The connector was disconnected while this sync was running.'
        }
      }
      c.status = 'not_connected'
      c.accountLabel = c.workspaceLabel = c.errorMessage = undefined
      c.grantedPermissions = []
      logActivity(s, {
        kind: 'connector_disconnected',
        label: 'Connector disconnected',
        relatedType: 'connector',
        relatedId: provider,
        relatedLabel: connectorName(provider),
        detail: 'Existing demo records were not deleted.',
        outcome: 'warning',
      })
      return clone(c)
    })
  },

  /** "Use demo data": restores the five seeded demo connectors that investigations rely on. */
  async enableDemoConnectors(): Promise<number> {
    await tick()
    return mutate((s) => {
      const seed = createSeedState()
      const wanted: SourceProvider[] = ['gmail', 'slack', 'jira', 'confluence', 'notion']
      let changed = 0
      for (const p of wanted) {
        const cur = findConn(s, p)
        if (cur.status === 'not_connected' || cur.status === 'connecting') {
          Object.assign(cur, seed.connectors.find((c) => c.id === p))
          changed += 1
        }
      }
      if (changed > 0) {
        logActivity(s, {
          kind: 'connector_connected',
          label: 'Demo connectors enabled',
          relatedType: 'workspace',
          relatedLabel: 'Demo data',
          detail: `${changed} simulated connector(s) enabled.`,
        })
      }
      return changed
    })
  },

  // ── activity & settings ──
  async listActivity(): Promise<ActivityEvent[]> {
    await tick()
    guard()
    return clone([...getState().activity].sort((a, b) => b.at.localeCompare(a.at)))
  },

  async getSettings(): Promise<WorkspaceSettings> {
    await tick()
    return clone(getState().settings)
  },

  getSettingsSnapshot(): WorkspaceSettings {
    return getState().settings
  },

  async updateSettings(patch: Partial<WorkspaceSettings>): Promise<WorkspaceSettings> {
    await tick()
    return mutate((s) => {
      if (patch.workspaceName !== undefined && !patch.workspaceName.trim()) {
        throw new Error('Workspace name cannot be empty.')
      }
      Object.assign(s.settings, patch)
      return clone(s.settings)
    })
  },

  async resetDemo(): Promise<void> {
    await tick()
    removeKey('investigator.demo.state')
    clearAgentConversations()
    const fresh = createSeedState()
    fresh.settings.timezone = getState().settings.timezone
    replaceState(fresh)
    mutate((s) => {
      logActivity(s, {
        kind: 'demo_reset',
        label: 'Demo data reset',
        relatedType: 'workspace',
        relatedLabel: 'Demo data',
      })
    })
  },
}

resumeJobs()

export type MockApi = typeof mockApi
