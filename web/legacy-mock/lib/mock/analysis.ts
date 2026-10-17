import { analysisTemplates, type Analysis } from '@/data/mockInvestigations'
import { evidenceById, mockEvidence } from '@/data/mockEvidence'
import { providerMeta } from '@/data/mockConnectors'
import type {
  CitedText,
  Connector,
  CoverageStatus,
  EvidenceRecord,
  Investigation,
  MockState,
  SourceCoverage,
  SourceProvider,
} from '@/types/investigator'
import { nowIso } from '@/lib/mock/store'

/**
 * Deterministic stand-in for the investigation engine. Given the same connector
 * state and the same inputs it always produces the same output.
 */

const CUSTOMER_KEYS = ['northstar', 'cobalt', 'meridian'] as const

export function customerKeyFor(inv: Investigation): string | undefined {
  const hay = [inv.customerName, inv.projectName, inv.ticketId, inv.problemStatement]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
  const direct = CUSTOMER_KEYS.find((k) => hay.includes(k))
  if (direct) return direct
  if (!inv.customerName && /investor onboarding/.test(hay)) return 'northstar'
  return undefined
}

export function evidenceForKey(key: string | undefined): EvidenceRecord[] {
  if (!key) return []
  return mockEvidence.filter((e) => e.customerName.toLowerCase().includes(key))
}

export const isHealthy = (c: Connector): boolean =>
  c.status === 'connected' || c.status === 'syncing' || c.status === 'sync_completed'

export const isConnected = (c: Connector): boolean =>
  isHealthy(c) || c.status === 'needs_attention'

export const needsAttention = (c: Connector): boolean =>
  c.status === 'needs_attention' ||
  c.status === 'permission_revoked' ||
  c.status === 'sync_failed'

function coverageFor(
  provider: SourceProvider,
  connector: Connector | undefined,
  found: number,
  at: string,
): SourceCoverage {
  const name = providerMeta[provider].name
  const status = connector?.status ?? 'not_connected'
  const base = { provider, searchedAt: at }
  if (status === 'not_connected' || status === 'connecting') {
    return { provider, status: 'not_connected', warning: `${name} is not connected, so it was not searched.` }
  }
  if (status === 'permission_revoked') {
    return { provider, status: 'permission_denied', warning: `Access to ${name} was revoked. It was not searched.` }
  }
  if (status === 'sync_failed') {
    return { provider, status: 'search_failed', warning: `The last ${name} sync failed, so it was not searched.` }
  }
  if (status === 'needs_attention') {
    return {
      ...base,
      status: 'partial',
      recordsFound: found,
      warning: connector?.errorMessage ?? `${name} was only partially searched.`,
    }
  }
  const covered: CoverageStatus = found > 0 ? 'searched' : 'no_matches'
  return { ...base, status: covered, recordsFound: found }
}

export function computeCoverage(
  s: MockState,
  providers: SourceProvider[],
  key: string | undefined,
): SourceCoverage[] {
  const at = nowIso()
  const pool = evidenceForKey(key)
  return providers.map((p) =>
    coverageFor(
      p,
      s.connectors.find((c) => c.id === p),
      pool.filter((e) => e.provider === p && e.indexStatus !== 'unavailable').length,
      at,
    ),
  )
}

export const isSearchable = (c: SourceCoverage): boolean =>
  c.status === 'searched' || c.status === 'partial' || c.status === 'no_matches'

export function coverageRatio(coverage: SourceCoverage[]): { searched: number; total: number } {
  return { searched: coverage.filter(isSearchable).length, total: coverage.length }
}

function pruneCited(parts: CitedText[], keep: (id: string) => boolean): CitedText[] {
  return parts
    .map((p) => (p.evidenceIds ? { ...p, evidenceIds: p.evidenceIds.filter(keep) } : p))
    .filter((p) => p.evidenceIds === undefined || p.evidenceIds.length > 0)
}

function buildFromTemplate(inv: Investigation, key: string, allowed: Set<SourceProvider>): Analysis {
  const tpl = analysisTemplates[key]
  const cloned: Analysis = JSON.parse(
    JSON.stringify(tpl.analysis).replaceAll(tpl.sourceId, inv.id),
  )
  const keep = (id: string) => {
    const e = evidenceById.get(id)
    return e !== undefined && allowed.has(e.provider) && e.indexStatus !== 'unavailable'
  }
  const filt = (ids: string[]) => ids.filter(keep)

  const findings = cloned.findings
    .map((f) => ({
      ...f,
      supportingEvidenceIds: filt(f.supportingEvidenceIds),
      contradictingEvidenceIds: filt(f.contradictingEvidenceIds),
    }))
    .filter((f) => f.supportingEvidenceIds.length > 0)
  const findingIds = new Set(findings.map((f) => f.id))

  const commitments = cloned.commitments
    .map((c) => ({ ...c, evidenceIds: filt(c.evidenceIds) }))
    .filter((c) => c.evidenceIds.length > 0)
  const commitmentIds = new Set(commitments.map((c) => c.id))

  const timeline = cloned.timeline
    .map((t) => ({
      ...t,
      evidenceIds: filt(t.evidenceIds),
      relatedFindingIds: t.relatedFindingIds.filter((id) => findingIds.has(id)),
      relatedCommitmentIds: t.relatedCommitmentIds.filter((id) => commitmentIds.has(id)),
    }))
    .filter((t) => t.evidenceIds.length > 0)

  const contradictions = cloned.contradictions
    .map((c) => ({
      ...c,
      claimA: { ...c.claimA, evidenceIds: filt(c.claimA.evidenceIds) },
      claimB: { ...c.claimB, evidenceIds: filt(c.claimB.evidenceIds) },
    }))
    .filter((c) => c.claimA.evidenceIds.length > 0 && c.claimB.evidenceIds.length > 0)

  const summary = {
    overview: pruneCited(cloned.summary.overview, keep),
    status: pruneCited(cloned.summary.status, keep),
    blocker: pruneCited(cloned.summary.blocker, keep),
    nextStep: pruneCited(cloned.summary.nextStep, keep),
  }
  const empty = (parts: CitedText[]) => parts.length === 0
  if (empty(summary.overview)) {
    summary.overview = [{ text: 'Limited evidence was available from the selected sources. Conclusions are unknown.' }]
  }
  if (empty(summary.status)) summary.status = [{ text: 'Unknown' }]
  if (empty(summary.blocker)) summary.blocker = [{ text: 'Unknown' }]
  if (empty(summary.nextStep)) {
    summary.nextStep = [{ text: 'Connect missing sources or broaden the date range, then re-run.' }]
  }

  return {
    customerKey: key,
    summary,
    findings,
    timeline,
    commitments,
    gaps: cloned.gaps.map((g) => ({ ...g, relatedEvidenceIds: filt(g.relatedEvidenceIds) })),
    contradictions,
    actions: cloned.actions.map((a) => ({
      ...a,
      relatedEvidenceIds: filt(a.relatedEvidenceIds),
      relatedFindingIds: a.relatedFindingIds.filter((id) => findingIds.has(id)),
    })),
  }
}

const NO_MATCH_SUMMARY = {
  overview: [
    {
      text: 'No records matching this escalation were found in the searched sources. This does not mean no evidence exists: unsearched sources and unindexed records could hold relevant history.',
    },
  ],
  status: [{ text: 'Unknown' }],
  blocker: [{ text: 'Unknown' }],
  nextStep: [{ text: 'Connect missing sources, broaden the context, then re-run the investigation.' }],
}

export const hasAnalysis = (s: MockState, inv: Investigation): boolean =>
  inv.summary !== null || s.findings.some((f) => f.investigationId === inv.id)

function describeCoverageChange(before: SourceCoverage[], after: SourceCoverage[]): string[] {
  const changes: string[] = []
  for (const a of after) {
    const b = before.find((x) => x.provider === a.provider)
    if (!b || b.status !== a.status) {
      changes.push(`${providerMeta[a.provider].name}: ${b ? b.status.replace('_', ' ') : 'new'} → ${a.status.replace('_', ' ')}`)
    }
  }
  return changes
}

/** Completes a simulated run. Called by the shared job scheduler. */
export function completeRun(s: MockState, inv: Investigation): void {
  const kind = inv.job?.kind ?? 'initial'
  const at = nowIso()
  const key = customerKeyFor(inv)
  const before = inv.coverage
  const coverage = computeCoverage(s, inv.selectedProviders, key)
  const allowed = new Set(coverage.filter(isSearchable).map((c) => c.provider))
  const existing = hasAnalysis(s, inv)

  if (existing && kind === 'rerun') {
    const changes = describeCoverageChange(before, coverage)
    inv.coverage = coverage
    inv.lastRunNote =
      changes.length > 0
        ? `Coverage updated (${changes.join('; ')}). Reviewed notes and actions were kept.`
        : 'No new records were found in the searched sources. Reviewed notes and actions were kept.'
    if (changes.length > 0) inv.analysisVersion += 1
    inv.summaryReviewedBy = changes.length > 0 ? undefined : inv.summaryReviewedBy
    inv.summaryReviewedAt = changes.length > 0 ? undefined : inv.summaryReviewedAt
    if (inv.status === 'investigating' || inv.status === 'queued') inv.status = 'needs_review'
  } else {
    // First analysis (or a retry of a draft or failed case): replace any partial output.
    removeFor(s.findings, inv.id)
    removeFor(s.timeline, inv.id)
    removeFor(s.commitments, inv.id)
    removeFor(s.gaps, inv.id)
    removeFor(s.contradictions, inv.id)
    removeFor(s.actions, inv.id)
    inv.coverage = coverage
    if (key && allowed.size > 0 && analysisTemplates[key]) {
      const built = buildFromTemplate(inv, key, allowed)
      s.findings.push(...built.findings)
      s.timeline.push(...built.timeline)
      s.commitments.push(...built.commitments)
      s.gaps.push(...built.gaps)
      s.contradictions.push(...built.contradictions)
      s.actions.push(...built.actions)
      inv.summary = built.summary
    } else {
      inv.summary = clone(NO_MATCH_SUMMARY)
    }
    inv.analysisVersion = Math.max(1, inv.analysisVersion + 1)
    inv.status = 'needs_review'
    inv.failureReason = undefined
    inv.lastRunNote = 'Initial run completed. All output is AI-generated and requires review.'
  }

  inv.lastRunAt = at
  inv.updatedAt = at
  inv.runCount += 1
  inv.job = undefined
}

const clone = <T>(v: T): T => structuredClone(v)

function removeFor<T extends { investigationId: string }>(items: T[], investigationId: string): void {
  for (let i = items.length - 1; i >= 0; i--) {
    if (items[i].investigationId === investigationId) items.splice(i, 1)
  }
}
