import { evidenceById } from '@/data/mockEvidence'
import { providerMeta } from '@/data/mockConnectors'
import { formatDate, shortDate } from '@/lib/format'
import { generateDraft } from '@/lib/mock/draft'
import { getState, newId, nowIso } from '@/lib/mock/store'
import type {
  AgentAction,
  AgentBullet,
  AgentIntent,
  AgentMessage,
  AgentResponse,
  AgentSection,
  AgentToolActivity,
  MockAgentService,
  NewActionInput,
  SendMessageInput,
} from '@/types/agent'
import type {
  Commitment,
  CommitmentStatus,
  Investigation,
  MockState,
  SourceProvider,
} from '@/types/investigator'

/**
 * Deterministic mock agent. It never calls a model or the network: every answer is
 * assembled from the shared mock state, and every "tool" is a pure read of that state.
 */

const TOOL_DELAY_MS = 320
const UNVERIFIED = "I couldn't verify this from the available records."

// ───────────────────────── intent matching ─────────────────────────

const INTENT_RULES: [AgentIntent, RegExp][] = [
  ['draft', /\b(draft|customer update|reply|respond|response|email the customer|write to)\b/i],
  ['conflicts', /\b(conflict\w*|contradict\w*|disagree\w*|inconsisten\w*|mismatch\w*)\b/i],
  ['commitments', /\b(commit\w*|promis\w*|missed|overdue|deadline\w*|due date\w*)\b/i],
  ['next_steps', /\b(next|recommend\w*|should we|what should|action\w*|follow[- ]?up|do now)\b/i],
  ['summary', /\b(summar\w*|what happened|overview|recap|tldr|brief me)\b/i],
  ['timeline', /\b(timeline|chronolog\w*|sequence|trace|history|when did)\b/i],
  ['blocker', /\b(cause\w*|blocker\w*|blocked|why|delay\w*|root|stuck|reason)\b/i],
]

export function detectIntent(message: string): AgentIntent {
  for (const [intent, re] of INTENT_RULES) if (re.test(message)) return intent
  return 'unsupported'
}

// ───────────────────────── read helpers ─────────────────────────

interface Ctx {
  s: MockState
  inv: Investigation
  tz: string
  evidence: string[]
}

const uniq = <T,>(xs: T[]): T[] => [...new Set(xs)]

function evidenceFor(s: MockState, invId: string): string[] {
  const inv = s.investigations.find((i) => i.id === invId)
  const ids: string[] = []
  const sum = inv?.summary
  if (sum) for (const part of [sum.overview, sum.status, sum.blocker, sum.nextStep]) for (const c of part) ids.push(...(c.evidenceIds ?? []))
  for (const f of s.findings) if (f.investigationId === invId) ids.push(...f.supportingEvidenceIds, ...f.contradictingEvidenceIds)
  for (const t of s.timeline) if (t.investigationId === invId) ids.push(...t.evidenceIds)
  for (const c of s.commitments) if (c.investigationId === invId) ids.push(...c.evidenceIds)
  for (const g of s.gaps) if (g.investigationId === invId) ids.push(...g.relatedEvidenceIds)
  for (const c of s.contradictions) if (c.investigationId === invId) ids.push(...c.claimA.evidenceIds, ...c.claimB.evidenceIds)
  for (const a of s.actions) if (a.investigationId === invId) ids.push(...a.relatedEvidenceIds)
  return uniq(ids)
    .filter((id) => evidenceById.has(id))
    .sort((a, b) => (evidenceById.get(a)?.timestamp ?? '').localeCompare(evidenceById.get(b)?.timestamp ?? ''))
}

const own = <T extends { investigationId: string }>(xs: T[], id: string): T[] => xs.filter((x) => x.investigationId === id)
const dateOf = (c: Ctx, iso?: string) => (iso ? formatDate(iso, c.tz) : undefined)
const sentence = (t: string) => (/[.!?]$/.test(t.trim()) ? t.trim() : `${t.trim()}.`)

// ───────────────────────── simulated tools ─────────────────────────

type Tool = { run: (c: Ctx) => Omit<AgentToolActivity, 'id'> }

function searchTool(provider: SourceProvider): Tool {
  const name = providerMeta[provider].name
  return {
    run: (c) => {
      const ids = c.evidence.filter((id) => evidenceById.get(id)?.provider === provider)
      const connector = c.s.connectors.find((x) => x.id === provider)
      const partial = connector?.status === 'needs_attention' ? ` ${connector.errorMessage ?? 'The last sync was partial.'}` : ''
      return {
        label: provider === 'jira' ? 'Checking Jira status' : `Searching ${name}`,
        operation: `evidence.search({ provider: "${provider}", investigation: "${c.inv.id}" })`,
        provider,
        summary: `${ids.length} record${ids.length === 1 ? '' : 's'} used by this investigation.${partial}`,
        count: ids.length,
        evidenceIds: ids,
      }
    },
  }
}

const timelineTool: Tool = {
  run: (c) => {
    const ev = own(c.s.timeline, c.inv.id)
    return {
      label: 'Comparing timeline events',
      operation: `timeline.list({ investigation: "${c.inv.id}" })`,
      summary: `${ev.length} event${ev.length === 1 ? '' : 's'} ordered by time.`,
      count: ev.length,
      evidenceIds: uniq(ev.flatMap((e) => e.evidenceIds)),
    }
  },
}

const commitmentsTool: Tool = {
  run: (c) => {
    const cm = own(c.s.commitments, c.inv.id)
    return {
      label: 'Reviewing commitments',
      operation: `commitments.list({ investigation: "${c.inv.id}" })`,
      summary: `${cm.length} commitment${cm.length === 1 ? '' : 's'} read.`,
      count: cm.length,
      evidenceIds: uniq(cm.flatMap((x) => x.evidenceIds)),
    }
  },
}

const findingsTool = (label = 'Preparing evidence-backed findings'): Tool => ({
  run: (c) => {
    const f = own(c.s.findings, c.inv.id)
    return {
      label,
      operation: `findings.list({ investigation: "${c.inv.id}" })`,
      summary: `${f.length} finding${f.length === 1 ? '' : 's'}, ${f.filter((x) => x.status === 'verified').length} verified.`,
      count: f.length,
      evidenceIds: uniq(f.flatMap((x) => x.supportingEvidenceIds)),
    }
  },
})

const issuesTool: Tool = {
  run: (c) => {
    const g = own(c.s.gaps, c.inv.id)
    const k = own(c.s.contradictions, c.inv.id)
    return {
      label: 'Checking gaps and conflicts',
      operation: `issues.list({ investigation: "${c.inv.id}" })`,
      summary: `${k.length} contradiction${k.length === 1 ? '' : 's'}, ${g.length} evidence gap${g.length === 1 ? '' : 's'}.`,
      count: k.length + g.length,
      evidenceIds: uniq([...k.flatMap((x) => [...x.claimA.evidenceIds, ...x.claimB.evidenceIds]), ...g.flatMap((x) => x.relatedEvidenceIds)]),
    }
  },
}

const actionsTool: Tool = {
  run: (c) => {
    const a = own(c.s.actions, c.inv.id).filter((x) => x.status !== 'dismissed')
    return {
      label: 'Reading recommended actions',
      operation: `actions.list({ investigation: "${c.inv.id}" })`,
      summary: `${a.length} open or completed action${a.length === 1 ? '' : 's'}.`,
      count: a.length,
      evidenceIds: uniq(a.flatMap((x) => x.relatedEvidenceIds)),
    }
  },
}

const draftTool: Tool = {
  run: (c) => {
    const f = own(c.s.findings, c.inv.id).filter((x) => x.status === 'verified' && x.customerStatement)
    return {
      label: 'Checking verified findings',
      operation: `draft.generate({ investigation: "${c.inv.id}" })`,
      summary: `${f.length} verified, customer-safe finding${f.length === 1 ? '' : 's'} available.`,
      count: f.length,
      evidenceIds: uniq(f.flatMap((x) => x.supportingEvidenceIds)),
    }
  },
}

const PROVIDER_ORDER: SourceProvider[] = ['gmail', 'outlook', 'slack', 'teams', 'jira', 'linear', 'confluence', 'notion', 'google_drive', 'salesforce']

function providerTools(c: Ctx, only?: SourceProvider[]): Tool[] {
  const present = new Set(c.evidence.map((id) => evidenceById.get(id)?.provider))
  return PROVIDER_ORDER.filter((p) => present.has(p) && (!only || only.includes(p))).map(searchTool)
}

function planTools(intent: AgentIntent, c: Ctx): Tool[] {
  switch (intent) {
    case 'summary':
      return [findingsTool('Reading summary and findings')]
    case 'timeline':
      return [...providerTools(c, ['gmail', 'outlook', 'slack', 'teams']), timelineTool]
    case 'commitments':
      return [commitmentsTool]
    case 'blocker':
      return [...providerTools(c), findingsTool(), issuesTool]
    case 'conflicts':
      return [issuesTool, timelineTool]
    case 'next_steps':
      return [findingsTool('Reading findings'), issuesTool, actionsTool]
    case 'draft':
      return [draftTool]
    default:
      return []
  }
}

// ───────────────────────── response builders ─────────────────────────

interface Built {
  content: string
  sections: AgentSection[]
  actions?: AgentAction[]
  followUps?: string[]
  preview?: string
  needsInput?: boolean
}

const bullet = (text: string, evidenceIds: string[] = [], extra: Partial<AgentBullet> = {}): AgentBullet => ({
  text,
  evidenceIds: uniq(evidenceIds),
  ...extra,
})

function insufficient(c: Ctx, why: string): Built {
  return {
    content: `${UNVERIFIED} ${why}`,
    sections: [
      {
        heading: 'What to inspect next',
        kind: 'unknown',
        bullets: [
          bullet('Run or re-run the investigation so the agent has a timeline and findings to read.'),
          bullet('Check which sources were searched; unsearched sources can hold missing records.'),
          bullet(`Add the customer, project or ticket ID in Edit context so more records can match (${c.inv.title}).`),
        ],
      },
    ],
    followUps: [],
    needsInput: true,
  }
}

function hasAnalysis(c: Ctx): boolean {
  return c.inv.summary !== null && !c.inv.job
}

const noteAction = (id: string, text: string): AgentAction => ({ id: `note-agent-${id}`, kind: 'apply_note', label: 'Apply investigation note', noteText: text })

function buildSummary(c: Ctx, msgId: string): Built {
  const sum = c.inv.summary
  if (!sum || c.inv.job) return insufficient(c, 'This investigation has no completed analysis yet.')
  const findings = own(c.s.findings, c.inv.id)
  const gaps = own(c.s.gaps, c.inv.id).filter((g) => g.review === 'unresolved')
  const counts = (st: string) => findings.filter((f) => f.status === st).length
  const sections: AgentSection[] = [
    {
      heading: 'What the records show',
      kind: 'direct',
      bullets: [...sum.overview, ...sum.status, ...sum.blocker].map((p) => bullet(sentence(p.text), p.evidenceIds)),
    },
    {
      heading: 'Findings',
      kind: 'info',
      bullets: [
        bullet(`${counts('verified')} verified, ${counts('needs_verification')} need verification, ${counts('conflicting')} conflicting, ${counts('unknown')} unknown.`),
        ...findings.map((f) => bullet(`${f.title}.`, f.supportingEvidenceIds, { findingId: f.id, tone: f.status === 'verified' ? 'neutral' : 'warning' })),
      ],
    },
  ]
  if (gaps.length > 0) {
    sections.push({ heading: 'Still unknown', kind: 'unknown', bullets: gaps.map((g) => bullet(sentence(g.missing), g.relatedEvidenceIds)) })
  }
  const first = findings[0]
  const note = `Agent summary: ${[...sum.overview, ...sum.status].map((p) => sentence(p.text)).join(' ')}`
  return {
    content: [...sum.overview].map((p) => sentence(p.text)).join(' '),
    sections: [
      ...sections,
      ...(c.inv.summaryReviewedAt ? [] : [{ heading: 'Review state', kind: 'info' as const, bullets: [bullet('The investigation summary has not been human-reviewed yet.', [], { tone: 'warning' })] }]),
    ],
    actions: [
      ...(first ? [{ id: `view-${first.id}`, kind: 'view_finding' as const, label: 'View first finding', findingId: first.id }] : []),
      noteAction(msgId, note),
    ],
    followUps: ['What caused the delay?', 'Find missed commitments', 'Show conflicting evidence'],
  }
}

function buildTimeline(c: Ctx): Built {
  const events = own(c.s.timeline, c.inv.id).sort((a, b) => a.occurredAt.localeCompare(b.occurredAt))
  if (!hasAnalysis(c) || events.length === 0) return insufficient(c, 'No timeline events exist for this investigation.')
  const stamp = (e: (typeof events)[number]) => (e.precision === 'unknown' ? 'Date unknown' : e.precision === 'date_only' ? shortDate(e.occurredAt, c.tz) : `${shortDate(e.occurredAt, c.tz)}`)
  const key = events.filter((e) => e.eventType !== 'internal_discussion' || e.relatedFindingIds.length > 0).slice(0, 10)
  const first = events[0]
  const last = events[events.length - 1]
  const dateOnly = events.filter((e) => e.precision !== 'exact').length
  return {
    content: `${events.length} events between ${dateOf(c, first.occurredAt)} and ${dateOf(c, last.occurredAt)}. The ${key.length} below carry the most weight; open any citation to read the source.`,
    sections: [
      {
        heading: 'Chronology',
        kind: 'direct',
        bullets: key.map((e) => bullet(`${stamp(e)} · ${e.title}${e.actor ? ` (${e.actor})` : ''}`, e.evidenceIds, { timelineEventId: e.id })),
      },
      ...(dateOnly > 0
        ? [{ heading: 'Still unknown', kind: 'unknown' as const, bullets: [bullet(`${dateOnly} event${dateOnly === 1 ? ' has' : 's have'} a date only; no time of day is assumed.`, [], { tone: 'warning' })] }]
        : []),
    ],
    actions: [{ id: `tl-${last.id}`, kind: 'show_timeline', label: 'Show latest on timeline', timelineEventId: last.id }],
    followUps: ['Find missed commitments', 'What caused the delay?'],
  }
}

const COMMIT_LABEL: Record<CommitmentStatus, string> = {
  confirmed: 'Confirmed',
  fulfilled: 'Fulfilled',
  at_risk: 'At risk',
  overdue: 'Overdue',
  unverified: 'Unverified',
}

function buildCommitments(c: Ctx): Built {
  const list = own(c.s.commitments, c.inv.id)
  if (!hasAnalysis(c) || list.length === 0) return insufficient(c, 'No commitments were extracted for this investigation.')
  const order: CommitmentStatus[] = ['overdue', 'at_risk', 'unverified', 'confirmed', 'fulfilled']
  const count = (st: CommitmentStatus) => list.filter((x) => x.status === st).length
  const line = (x: Commitment) => {
    const who = x.owner ?? x.committedBy
    const due = x.dueAt ? `due ${dateOf(c, x.dueAt)}` : 'no due date stated'
    return `${COMMIT_LABEL[x.status]}: ${sentence(x.statement)} ${who ? `Owner: ${who}.` : 'Owner unknown.'} ${due[0].toUpperCase()}${due.slice(1)}.`
  }
  const missingOwner = list.filter((x) => !x.owner && !x.committedBy).length
  const missingDue = list.filter((x) => !x.dueAt).length
  const problems = list.filter((x) => x.status === 'overdue' || x.status === 'at_risk')
  return {
    content: `${list.length} commitments: ${order.filter(count).map((st) => `${count(st)} ${COMMIT_LABEL[st].toLowerCase()}`).join(', ')}.${problems.length ? ` ${problems.length} need attention.` : ''}`,
    sections: [
      ...order
        .filter(count)
        .map((st) => ({
          heading: `${COMMIT_LABEL[st]} (${count(st)})`,
          kind: st === 'overdue' || st === 'at_risk' ? ('conflict' as const) : st === 'unverified' ? ('unknown' as const) : ('direct' as const),
          bullets: list.filter((x) => x.status === st).map((x) => bullet(line(x), x.evidenceIds, { commitmentId: x.id })),
        })),
      ...(missingOwner + missingDue > 0
        ? [{ heading: 'Still unknown', kind: 'unknown' as const, bullets: [bullet(`${missingOwner} without a named owner, ${missingDue} without a due date. The agent does not fill these in.`, [], { tone: 'warning' as const })] }]
        : []),
    ],
    actions: problems[0] ? [{ id: `cm-${problems[0].id}`, kind: 'open_evidence', label: 'Open evidence', evidenceId: problems[0].evidenceIds[0] ?? '' }].filter((a) => a.evidenceId) as AgentAction[] : [],
    followUps: ['What caused the delay?', 'What should we do next?'],
  }
}

function buildBlocker(c: Ctx): Built {
  if (!hasAnalysis(c)) return insufficient(c, 'This investigation has no completed analysis yet.')
  const sum = c.inv.summary
  const findings = own(c.s.findings, c.inv.id)
  const direct = findings.filter((f) => f.basis === 'direct' && f.supportingEvidenceIds.length > 0)
  const inferred = findings.filter((f) => f.basis === 'inference')
  const gaps = own(c.s.gaps, c.inv.id).filter((g) => g.review === 'unresolved')
  const conflicts = own(c.s.contradictions, c.inv.id)
  const jira = c.s.connectors.find((x) => x.id === 'jira')
  const byProvider = uniq(c.evidence.map((id) => evidenceById.get(id)?.provider).filter((p): p is SourceProvider => Boolean(p))).map((p) => providerMeta[p].name)
  const blockerText = sum?.blocker.map((p) => sentence(p.text)).join(' ') ?? ''
  const unknowns: AgentBullet[] = gaps.map((g) => bullet(sentence(g.missing), g.relatedEvidenceIds))
  if (jira?.status === 'needs_attention') unknowns.push(bullet('Jira comment history is only partly indexed, so ticket discussion may be missing.', [], { tone: 'warning' }))
  return {
    content: blockerText || 'The records do not state a single blocker.',
    sections: ([
      {
        heading: 'Direct evidence',
        kind: 'direct',
        bullets: direct.map((f) => bullet(sentence(f.claim), f.supportingEvidenceIds, { findingId: f.id })),
      },
      ...(inferred.length > 0
        ? [{ heading: 'Interpretation (not stated in a record)', kind: 'interpretation' as const, bullets: inferred.map((f) => bullet(sentence(f.claim), f.supportingEvidenceIds, { findingId: f.id, tone: 'warning' as const })) }]
        : []),
      ...(conflicts.length > 0
        ? [{ heading: 'Conflicting information', kind: 'conflict' as const, bullets: conflicts.map((k) => bullet(`${k.title}. ${sentence(k.explanation)}`, [...k.claimA.evidenceIds, ...k.claimB.evidenceIds])) }]
        : []),
      ...(unknowns.length > 0 ? [{ heading: 'Still unknown', kind: 'unknown' as const, bullets: unknowns }] : []),
      { heading: 'Sources compared', kind: 'info', bullets: [bullet(byProvider.join(', ') || 'None')] },
    ] as AgentSection[]).filter((sec) => sec.bullets.length > 0),
    actions: [
      ...(direct[0] ? [{ id: `view-${direct[0].id}`, kind: 'view_finding' as const, label: 'View finding', findingId: direct[0].id }] : []),
      noteAction(`blocker-${c.inv.analysisVersion}`, `Agent blocker analysis: ${blockerText}`),
    ],
    followUps: ['Show conflicting evidence', 'What should we do next?'],
  }
}

function buildConflicts(c: Ctx): Built {
  const conflicts = own(c.s.contradictions, c.inv.id)
  const conflictingFindings = own(c.s.findings, c.inv.id).filter((f) => f.status === 'conflicting')
  if (!hasAnalysis(c)) return insufficient(c, 'This investigation has no completed analysis yet.')
  if (conflicts.length === 0 && conflictingFindings.length === 0) {
    return {
      content: 'No conflicting records were found in the available demo records.',
      sections: [{ heading: 'Note', kind: 'info', bullets: [bullet('That is not proof nothing conflicts. Sources that were not searched could hold contradicting records.')] }],
      followUps: ['What caused the delay?', 'What should we do next?'],
    }
  }
  return {
    content: `${conflicts.length} contradiction${conflicts.length === 1 ? '' : 's'} between records. Both claims are shown with their sources.`,
    sections: conflicts.map((k) => ({
      heading: k.title,
      kind: 'conflict' as const,
      bullets: [
        bullet(`Claim A (${shortDate(k.claimA.at, c.tz)}): ${sentence(k.claimA.text)}`, k.claimA.evidenceIds),
        bullet(`Claim B (${shortDate(k.claimB.at, c.tz)}): ${sentence(k.claimB.text)}`, k.claimB.evidenceIds),
        bullet(sentence(k.explanation), [], { tone: 'warning' }),
      ],
    })),
    actions: [
      ...(conflicts[0] ? [{ id: `ev-${conflicts[0].id}`, kind: 'open_evidence' as const, label: 'Open first record', evidenceId: conflicts[0].claimA.evidenceIds[0] }] : []),
      ...(conflictingFindings[0] ? [{ id: `view-${conflictingFindings[0].id}`, kind: 'view_finding' as const, label: 'View conflicting finding', findingId: conflictingFindings[0].id }] : []),
    ].filter((a) => a.kind !== 'open_evidence' || a.evidenceId),
    followUps: ['What should we do next?', 'Draft a customer update'],
  }
}

function buildNextSteps(c: Ctx): Built {
  if (!hasAnalysis(c)) return insufficient(c, 'This investigation has no completed analysis yet.')
  const actions = own(c.s.actions, c.inv.id).filter((a) => a.status !== 'dismissed' && a.status !== 'completed')
  const gaps = own(c.s.gaps, c.inv.id).filter((g) => g.review === 'unresolved')
  const findings = own(c.s.findings, c.inv.id)
  const existing = new Set(actions.map((a) => a.title.toLowerCase()))
  const proposals: NewActionInput[] = gaps
    .filter((g) => !existing.has(g.followUp.toLowerCase()))
    .slice(0, 2)
    .map((g) => ({
      id: `act-agent-${g.id}`,
      title: g.followUp,
      rationale: `${sentence(g.missing)} ${sentence(g.whyItMatters)}`,
      priority: 'medium' as const,
      relatedFindingIds: findings.filter((f) => f.supportingEvidenceIds.some((e) => g.relatedEvidenceIds.includes(e))).map((f) => f.id),
      relatedEvidenceIds: g.relatedEvidenceIds,
    }))
  const sections: AgentSection[] = []
  if (actions.length > 0) {
    sections.push({
      heading: 'Already recommended',
      kind: 'direct',
      bullets: actions.map((a) => bullet(`${a.title} (${a.priority} priority, ${a.status.replace('_', ' ')}). ${sentence(a.rationale)}`, a.relatedEvidenceIds)),
    })
  }
  if (proposals.length > 0) {
    sections.push({
      heading: 'Suggested from open gaps',
      kind: 'interpretation',
      bullets: proposals.map((p) => bullet(`${sentence(p.title)} ${p.rationale}`, p.relatedEvidenceIds)),
    })
  }
  if (gaps.length > 0) {
    sections.push({ heading: 'Still unknown', kind: 'unknown', bullets: gaps.map((g) => bullet(sentence(g.missing), g.relatedEvidenceIds)) })
  }
  if (sections.length === 0) return insufficient(c, 'There are no open actions or gaps to recommend from.')
  return {
    content: `${actions.length} action${actions.length === 1 ? ' is' : 's are'} already recommended${proposals.length ? ` and ${proposals.length} more could close open gaps` : ''}. Nothing is added until you choose to.`,
    sections,
    actions: proposals.map((p) => ({ id: p.id, kind: 'add_action' as const, label: 'Add to recommended actions', action: p })),
    followUps: ['Draft a customer update', 'Find missed commitments'],
  }
}

function buildDraft(c: Ctx): Built {
  const verified = own(c.s.findings, c.inv.id).filter((f) => f.status === 'verified' && f.customerStatement)
  const held = own(c.s.findings, c.inv.id).filter((f) => f.status !== 'verified')
  if (!hasAnalysis(c) || verified.length === 0) return insufficient(c, 'No verified, customer-safe findings exist yet, so there is nothing to base a draft on.')
  return {
    content: `Drafted from ${verified.length} verified finding${verified.length === 1 ? '' : 's'}. Nothing is sent; review and edit it in the response editor first.`,
    sections: [
      { heading: 'Included (verified)', kind: 'direct', bullets: verified.map((f) => bullet(sentence(f.title), f.supportingEvidenceIds, { findingId: f.id })) },
      ...(held.length > 0
        ? [{ heading: 'Left out (not verified)', kind: 'unknown' as const, bullets: held.map((f) => bullet(`${sentence(f.title)} It is ${f.status.replace('_', ' ')}.`, f.supportingEvidenceIds, { tone: 'warning' as const })) }]
        : []),
    ],
    preview: generateDraft(c.s, c.inv.id),
    actions: [{ id: `resp-${c.inv.id}`, kind: 'open_response', label: 'Open response editor' }],
    followUps: ['Show conflicting evidence', 'What should we do next?'],
  }
}

function buildUnsupported(): Built {
  return {
    content: `${UNVERIFIED} I can only answer from this investigation's records, and that question does not match anything I can inspect.`,
    sections: [
      {
        heading: 'What I can inspect',
        kind: 'info',
        bullets: [
          bullet('Summary and findings'),
          bullet('Timeline of emails, chat, tickets and documents'),
          bullet('Commitments, owners and due dates'),
          bullet('Blockers, evidence gaps and conflicting records'),
          bullet('Recommended actions and a customer update draft'),
        ],
      },
    ],
    followUps: ['Summarize what happened', 'Find missed commitments', 'What caused the delay?'],
    needsInput: true,
  }
}

function build(intent: AgentIntent, c: Ctx, msgId: string): Built {
  switch (intent) {
    case 'summary': return buildSummary(c, msgId)
    case 'timeline': return buildTimeline(c)
    case 'commitments': return buildCommitments(c)
    case 'blocker': return buildBlocker(c)
    case 'conflicts': return buildConflicts(c)
    case 'next_steps': return buildNextSteps(c)
    case 'draft': return buildDraft(c)
    default: return buildUnsupported()
  }
}

// ───────────────────────── service ─────────────────────────

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))

export const mockAgent: MockAgentService = {
  async sendMessage(input: SendMessageInput, onTool): Promise<AgentResponse> {
    const s0 = getState()
    if (s0.settings.simulateApiFailure) {
      throw new Error('Simulated API failure. The agent could not complete this request. Turn this off in Settings.')
    }
    const text = input.message.trim()
    if (!text) throw new Error('Type a question first.')
    const inv = s0.investigations.find((i) => i.id === input.investigationId)
    if (!inv) throw new Error('Investigation was not found.')

    const intent = detectIntent(text)
    const ctx = (): Ctx => {
      const s = getState()
      const cur = s.investigations.find((i) => i.id === inv.id) ?? inv
      return { s, inv: cur, tz: s.settings.timezone, evidence: evidenceFor(s, inv.id) }
    }

    const tools: AgentToolActivity[] = []
    for (const tool of planTools(intent, ctx())) {
      await wait(TOOL_DELAY_MS)
      if (getState().settings.simulateApiFailure) throw new Error('Simulated API failure. The agent stopped partway through.')
      const activity = { id: newId('tool'), ...tool.run(ctx()) }
      tools.push(activity)
      onTool?.(activity)
    }
    await wait(TOOL_DELAY_MS)

    const c = ctx()
    const id = newId('msg')
    const built = build(intent, c, id)
    const evidenceIds = uniq(built.sections.flatMap((sec) => sec.bullets.flatMap((b) => b.evidenceIds)))
    const message: AgentMessage = {
      id,
      role: 'assistant',
      content: built.content,
      createdAt: nowIso(),
      evidenceIds,
      intent,
      tools,
      sections: built.sections,
      preview: built.preview,
      actions: built.actions,
      followUps: built.followUps,
      needsInput: built.needsInput,
    }
    return { message }
  },
}
