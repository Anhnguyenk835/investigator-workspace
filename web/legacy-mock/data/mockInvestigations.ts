import type {
  Commitment,
  Contradiction,
  Finding,
  Gap,
  Investigation,
  InvestigationSummary,
  RecommendedAction,
  SourceCoverage,
  TimelineEvent,
  TimelineEventType,
} from '@/types/investigator'
import { evidenceById } from '@/data/mockEvidence'

/**
 * DEMO DATA — deterministic analyses for three fictional escalations.
 * Every evidence id referenced below must exist in mockEvidence.ts
 * (checked at module load in development).
 */

export interface Analysis {
  customerKey: string
  summary: InvestigationSummary
  findings: Finding[]
  timeline: TimelineEvent[]
  commitments: Commitment[]
  gaps: Gap[]
  contradictions: Contradiction[]
  actions: RecommendedAction[]
}

const SEED_AT = '2026-10-15T07:05:00Z'

// ═════════════════════════════ Northstar Capital ═════════════════════════════

const NS = 'inv-northstar-onboarding'

const nsFindings: Finding[] = [
  {
    id: `${NS}:f1`,
    investigationId: NS,
    title: 'Delivery date was communicated to the customer',
    claim: 'Northstar was told the workflow would be ready by Friday, October 9.',
    explanation:
      "Sam Lindqvist's October 1 email states the date and ties it to KYC sandbox credentials arriving by October 5. The internal ticket, plan and chat carry the same date.",
    status: 'verified',
    basis: 'direct',
    supportingEvidenceIds: ['ev-gmail-002', 'ev-jira-001', 'ev-confluence-001', 'ev-slack-001'],
    contradictingEvidenceIds: [],
    customerStatement:
      'On October 1 we told you we expected the investor onboarding workflow to be ready by Friday, October 9. That date has passed and the workflow is not yet live.',
  },
  {
    id: `${NS}:f2`,
    investigationId: NS,
    title: 'The date depended on customer-side credentials',
    claim:
      "Readiness on October 9 was conditional on Northstar's KYC sandbox credentials arriving by October 5.",
    explanation:
      'The condition appears in the original email and in the internal kickoff note. Records show the credentials had not arrived on October 5, and the customer expected to send them on October 7.',
    status: 'verified',
    basis: 'direct',
    supportingEvidenceIds: ['ev-gmail-002', 'ev-slack-001', 'ev-slack-002', 'ev-gmail-003'],
    contradictingEvidenceIds: [],
    customerStatement:
      "Part of our plan involved testing identity verification against your KYC provider's sandbox, which depended on credentials that were still being provisioned.",
  },
  {
    id: `${NS}:f3`,
    investigationId: NS,
    title: 'Engineering found a defect during UAT',
    claim: 'Trust-type investors fail entity-type validation; the defect is tracked as ENG-2291.',
    explanation:
      'Engineering reproduced the defect in staging on October 8. A fix is merged to staging, but a regression pass was still pending on October 14.',
    status: 'verified',
    basis: 'direct',
    supportingEvidenceIds: ['ev-slack-004', 'ev-jira-003', 'ev-slack-008'],
    contradictingEvidenceIds: [],
    customerStatement:
      'During testing on October 8 we found a defect that affects trust-type investors. Our engineering team has a fix in testing.',
  },
  {
    id: `${NS}:f4`,
    investigationId: NS,
    title: 'Current blocker: credential receipt is unconfirmed',
    claim: 'The workflow may still be waiting on KYC credentials, but receipt is not confirmed.',
    explanation:
      'Northstar says it sent the credentials to the support mailbox on October 12. An implementer reports not seeing them in the implementation queue. No searched record shows receipt or a reply.',
    status: 'needs_verification',
    basis: 'direct',
    supportingEvidenceIds: ['ev-gmail-006', 'ev-slack-007', 'ev-jira-002'],
    contradictingEvidenceIds: [],
  },
  {
    id: `${NS}:f5`,
    investigationId: NS,
    title: 'Customer was told "on track" while internal records showed a blocker',
    claim:
      'On October 8 the customer was told delivery was on track, one day after the ticket was marked Blocked.',
    explanation:
      'The October 8 email and the October 7–8 internal records cannot both describe the same status. Why the email omitted the blocker is not established in any record.',
    status: 'conflicting',
    basis: 'direct',
    supportingEvidenceIds: ['ev-gmail-004'],
    contradictingEvidenceIds: ['ev-jira-002', 'ev-slack-003', 'ev-slack-004'],
  },
  {
    id: `${NS}:f6`,
    investigationId: NS,
    title: 'The revised target has not been confirmed with the customer',
    claim: 'An internal target of October 20 exists; no record shows it was shared with Northstar.',
    explanation:
      'The project update says the customer had not been informed as of October 9. This is an inference from absence: Teams and CRM were not searched, so a later conversation could exist.',
    status: 'needs_verification',
    basis: 'inference',
    supportingEvidenceIds: ['ev-notion-002', 'ev-slack-006'],
    contradictingEvidenceIds: [],
  },
]

function nsEvent(
  n: number,
  evidenceId: string,
  title: string,
  eventType: TimelineEventType,
  description: string,
  findings: number[],
  commitments: number[] = [],
): TimelineEvent {
  const e = evidenceById.get(evidenceId)
  if (!e) throw new Error(`Unknown evidence ${evidenceId}`)
  return {
    id: `${NS}:t${n}`,
    investigationId: NS,
    title,
    description,
    eventType,
    occurredAt: e.timestamp,
    precision: e.timestampPrecision,
    actor: e.author,
    provider: e.provider,
    evidenceIds: [evidenceId],
    relatedFindingIds: findings.map((f) => `${NS}:f${f}`),
    relatedCommitmentIds: commitments.map((c) => `${NS}:c${c}`),
  }
}

const nsTimeline: TimelineEvent[] = [
  nsEvent(1, 'ev-gmail-001', 'Customer asks for the workflow by October 9', 'customer_request', 'Northstar requests the investor onboarding workflow ahead of its Fund II close.', []),
  nsEvent(2, 'ev-gmail-002', 'October 9 delivery date communicated', 'commitment', 'Date given, conditional on KYC sandbox credentials by October 5.', [1, 2], [1]),
  nsEvent(3, 'ev-jira-001', 'IMPL-482 created with an October 9 due date', 'ticket_change', 'Internal ticket lists customer credentials and the questionnaire as dependencies.', [1], [1]),
  nsEvent(4, 'ev-slack-001', 'Internal note records the promised date', 'internal_discussion', 'Implementation lead restates the date and its two customer-side dependencies.', [1, 2]),
  nsEvent(5, 'ev-confluence-001', 'Implementation plan sets go-live to October 9', 'document_update', 'Plan v3 lists go-live and milestones. No later version exists.', [1]),
  nsEvent(6, 'ev-notion-001', 'Requirements page lists trusts as in scope', 'document_update', 'Investor types in scope include trusts. Only the date of the edit is available.', [3]),
  nsEvent(7, 'ev-slack-002', 'Credentials not received at the October 5 check-in', 'internal_discussion', 'Workflow steps can be built, but identity verification cannot be tested.', [2]),
  nsEvent(8, 'ev-gmail-003', 'Customer sends questionnaire, expects credentials October 7', 'customer_message', "Northstar's KYC vendor is still provisioning the sandbox account.", [2], [2]),
  nsEvent(9, 'ev-jira-002', 'IMPL-482 moved to Blocked', 'blocker', 'Identity-verification step cannot be validated without the credentials.', [4, 5]),
  nsEvent(10, 'ev-slack-003', 'Team decides to wait before telling the customer', 'internal_discussion', 'The implementation lead notes Friday is tight and defers raising it with the customer.', [5]),
  nsEvent(11, 'ev-slack-004', 'UAT finds a defect for trust investors', 'blocker', 'Entity-type mapping fails for trusts; filed as ENG-2291.', [3, 5]),
  nsEvent(12, 'ev-jira-003', 'ENG-2291 filed with no release date', 'ticket_change', 'Defect reproduced in staging. Comment history is only partially indexed.', [3]),
  nsEvent(13, 'ev-slack-005', 'CS manager asks whether the customer was told', 'internal_discussion', "Last customer-visible message still says Friday.", [5]),
  nsEvent(14, 'ev-gmail-004', 'Customer told delivery is on track for Friday', 'commitment', 'Email promises a testing confirmation. It does not mention the blocker.', [5], [3]),
  nsEvent(15, 'ev-slack-006', 'October 9 date missed', 'internal_discussion', 'The implementation lead notes the date was missed and the customer still needs a call.', [6], [1]),
  nsEvent(16, 'ev-notion-002', 'Revised target set to October 20', 'deadline_change', 'Status Blocked; the update says the customer has not been informed.', [6], [4]),
  nsEvent(17, 'ev-gmail-005', 'Customer escalates the delay', 'customer_message', 'Northstar asks for an explanation and a firm date.', [1]),
  nsEvent(18, 'ev-gmail-006', 'Customer says credentials were sent to support', 'customer_message', 'Sent to the shared support mailbox on the evening of October 12.', [4], [2]),
  nsEvent(19, 'ev-slack-007', 'Credentials not found in the implementation queue', 'internal_discussion', 'An implementer asks for the support inbox to be checked.', [4]),
  nsEvent(20, 'ev-slack-008', 'ENG-2291 fix merged to staging', 'ticket_change', 'Regression pass still pending; Engineering does not call it done.', [3], [4]),
]

const nsCommitments: Commitment[] = [
  {
    id: `${NS}:c1`,
    investigationId: NS,
    statement: 'Investor onboarding workflow ready for Northstar by Friday, October 9.',
    committedBy: 'Sam Lindqvist',
    owner: 'Sam Lindqvist',
    promisedAt: '2026-10-01T16:40:00Z',
    dueAt: '2026-10-09T00:00:00Z',
    status: 'overdue',
    evidenceIds: ['ev-gmail-002', 'ev-jira-001', 'ev-confluence-001', 'ev-slack-006'],
  },
  {
    id: `${NS}:c2`,
    investigationId: NS,
    statement:
      'Northstar to send KYC sandbox credentials (requested by October 5; customer expected October 7).',
    committedBy: 'Daniel Whitfield',
    owner: 'Daniel Whitfield',
    promisedAt: '2026-10-06T10:22:00Z',
    dueAt: '2026-10-07T00:00:00Z',
    status: 'unverified',
    evidenceIds: ['ev-gmail-002', 'ev-gmail-003', 'ev-gmail-006'],
  },
  {
    id: `${NS}:c3`,
    investigationId: NS,
    statement: 'Final testing completed October 8, with a confirmation to follow.',
    committedBy: 'Sam Lindqvist',
    promisedAt: '2026-10-08T16:15:00Z',
    dueAt: '2026-10-08T00:00:00Z',
    status: 'unverified',
    evidenceIds: ['ev-gmail-004'],
  },
  {
    id: `${NS}:c4`,
    investigationId: NS,
    statement: 'Revised internal target: workflow ready by October 20.',
    promisedAt: '2026-10-09T17:30:00Z',
    dueAt: '2026-10-20T00:00:00Z',
    status: 'at_risk',
    evidenceIds: ['ev-notion-002', 'ev-slack-008'],
  },
]

const nsGaps: Gap[] = [
  {
    id: `${NS}:g1`,
    investigationId: NS,
    missing: "No record confirms Northstar's KYC credentials were received.",
    whyItMatters:
      "It decides whether the customer's dependency is cleared and whether the October 20 target is realistic.",
    resolvingEvidence:
      'A support-mailbox search for the October 12 message, or a reply to Daniel Whitfield.',
    followUp:
      'Ask Support to search the shared mailbox and confirm receipt with Daniel Whitfield.',
    relatedEvidenceIds: ['ev-gmail-006', 'ev-slack-007'],
    customerQuestion:
      'Confirming that the KYC sandbox credentials you sent on October 12 have reached our team.',
    review: 'unresolved',
  },
  {
    id: `${NS}:g2`,
    investigationId: NS,
    missing: 'No record shows the October 20 target was shared with Northstar.',
    whyItMatters:
      'The customer is escalating from the original date. An unconfirmed date must not be repeated to them.',
    resolvingEvidence:
      'Outbound email or call notes after October 9; Teams or CRM activity, which were not searched.',
    followUp: 'Check Teams and CRM activity, then confirm with the implementation lead.',
    relatedEvidenceIds: ['ev-notion-002', 'ev-slack-006'],
    customerQuestion:
      'Agreeing a realistic go-live date with our engineering team. We will share it once it is confirmed.',
    review: 'unresolved',
  },
  {
    id: `${NS}:g3`,
    investigationId: NS,
    missing: 'No committed release date for the ENG-2291 fix.',
    whyItMatters: 'The fix gates onboarding for trust-type investors.',
    resolvingEvidence:
      'Engineering confirmation after regression testing, or later ENG-2291 comments (partially indexed).',
    followUp: 'Ask Reza Ahmadi for a committed date once regression testing completes.',
    relatedEvidenceIds: ['ev-jira-003', 'ev-slack-008'],
    review: 'unresolved',
  },
]

const nsContradictions: Contradiction[] = [
  {
    id: `${NS}:x1`,
    investigationId: NS,
    title: 'Status told to the customer vs. status recorded internally',
    claimA: {
      text: "“We're on track for Friday.” (email to the customer)",
      at: '2026-10-08T16:15:00Z',
      evidenceIds: ['ev-gmail-004'],
    },
    claimB: {
      text: 'IMPL-482 is Blocked on credentials, and UAT found a trust-investor defect.',
      at: '2026-10-08T09:14:00Z',
      evidenceIds: ['ev-jira-002', 'ev-slack-004'],
    },
    explanation:
      'The customer-facing message was sent after the internal records show a blocker. The records do not say whether the sender knew of the defect.',
    review: 'unresolved',
  },
  {
    id: `${NS}:x2`,
    investigationId: NS,
    title: 'Go-live date in the plan vs. the project update',
    claimA: {
      text: 'Go-live: October 9, 2026 (Confluence plan v3).',
      at: '2026-10-02T11:20:00Z',
      evidenceIds: ['ev-confluence-001'],
    },
    claimB: {
      text: 'Revised target: October 20, status Blocked (Notion project update).',
      at: '2026-10-09T17:30:00Z',
      evidenceIds: ['ev-notion-002'],
    },
    explanation:
      'The plan page has not been edited since October 2, so it may be stale. That is an inference and is not stated in either record.',
    review: 'unresolved',
  },
]

const nsActions: RecommendedAction[] = [
  {
    id: `${NS}:a1`,
    investigationId: NS,
    title: 'Confirm receipt of the KYC sandbox credentials',
    rationale: 'Credential receipt is the only open item that can be settled with a single check.',
    suggestedOwner: 'Chloe Tan',
    priority: 'high',
    relatedFindingIds: [`${NS}:f4`],
    relatedEvidenceIds: ['ev-gmail-006', 'ev-slack-007'],
    customerStep: 'We are confirming that the KYC sandbox credentials you sent have reached our team.',
    status: 'suggested',
    notes: [],
    createdAt: SEED_AT,
    updatedAt: SEED_AT,
  },
  {
    id: `${NS}:a2`,
    investigationId: NS,
    title: 'Send a reviewed update that acknowledges the missed date',
    rationale:
      'The customer escalated on October 12 and no reply is present in the searched sources.',
    suggestedOwner: 'Alex Morgan',
    priority: 'high',
    relatedFindingIds: [`${NS}:f1`, `${NS}:f6`],
    relatedEvidenceIds: ['ev-gmail-005', 'ev-slack-006'],
    status: 'suggested',
    notes: [],
    createdAt: SEED_AT,
    updatedAt: SEED_AT,
  },
  {
    id: `${NS}:a3`,
    investigationId: NS,
    title: 'Get a committed ENG-2291 release date from Engineering',
    rationale: 'Without it, any new customer date would be a guess.',
    suggestedOwner: 'Reza Ahmadi',
    priority: 'high',
    relatedFindingIds: [`${NS}:f3`],
    relatedEvidenceIds: ['ev-jira-003', 'ev-slack-008'],
    customerStep:
      'Our engineering team is finishing regression testing on the fix and we will share a confirmed date once it is available.',
    status: 'suggested',
    notes: [],
    createdAt: SEED_AT,
    updatedAt: SEED_AT,
  },
  {
    id: `${NS}:a4`,
    investigationId: NS,
    title: 'Reconcile the implementation plan with the project update',
    rationale: 'Two internal documents give different go-live dates.',
    suggestedOwner: 'Sam Lindqvist',
    priority: 'medium',
    relatedFindingIds: [`${NS}:f6`],
    relatedEvidenceIds: ['ev-confluence-001', 'ev-notion-002'],
    status: 'suggested',
    notes: [],
    createdAt: SEED_AT,
    updatedAt: SEED_AT,
  },
  {
    id: `${NS}:a5`,
    investigationId: NS,
    title: 'Agree who sends customer status updates during delays',
    rationale:
      'Internal discussion shows uncertainty about who would tell the customer. No record names an owner.',
    priority: 'low',
    relatedFindingIds: [`${NS}:f5`],
    relatedEvidenceIds: ['ev-slack-003', 'ev-slack-005'],
    status: 'suggested',
    notes: [],
    createdAt: SEED_AT,
    updatedAt: SEED_AT,
  },
]

const nsSummary: InvestigationSummary = {
  overview: [
    { text: 'Northstar was told on October 1 that the workflow would be ready by Friday, October 9, ', evidenceIds: ['ev-gmail-002'] },
    { text: 'conditional on KYC sandbox credentials arriving by October 5. ', evidenceIds: ['ev-gmail-002'] },
    { text: 'The date was missed: the credentials had not arrived ', evidenceIds: ['ev-jira-002', 'ev-slack-003'] },
    { text: 'and UAT found a defect affecting trust investors. ', evidenceIds: ['ev-slack-004', 'ev-jira-003'] },
    { text: 'An internal target of October 20 exists, ', evidenceIds: ['ev-notion-002'] },
    { text: 'but no record shows it was shared with the customer.', evidenceIds: ['ev-notion-002'] },
  ],
  status: [
    { text: 'Blocked. The October 9 date passed and the customer has escalated.', evidenceIds: ['ev-notion-002', 'ev-gmail-005'] },
  ],
  blocker: [
    { text: 'Two open dependencies: customer credentials, whose receipt is unconfirmed, ', evidenceIds: ['ev-gmail-006', 'ev-slack-007'] },
    { text: 'and the ENG-2291 fix, which awaits regression testing.', evidenceIds: ['ev-slack-008', 'ev-jira-003'] },
  ],
  nextStep: [
    { text: 'Confirm credential receipt, get a committed ENG-2291 date, then send the customer a reviewed update.', evidenceIds: ['ev-slack-007', 'ev-slack-008'] },
  ],
}

// ═════════════════════════════ Cobalt Ventures ═════════════════════════════

const CV = 'inv-cobalt-notices'

const cobalt: Analysis = {
  customerKey: 'cobalt',
  summary: {
    overview: [
      { text: 'Capital call notices were throttled by the outbound mail provider; about 40 were deferred, not lost. ', evidenceIds: ['ev-cv-slack-001'] },
      { text: 'ENG-2144 paced delivery under the limit and the deferred notices were re-sent.', evidenceIds: ['ev-cv-jira-001'] },
    ],
    status: [{ text: 'Resolved. Deferred notices were re-sent.', evidenceIds: ['ev-cv-jira-001'] }],
    blocker: [{ text: 'None recorded in the searched sources.' }],
    nextStep: [{ text: 'No further action recorded.' }],
  },
  findings: [
    {
      id: `${CV}:f1`,
      investigationId: CV,
      title: 'Notices were throttled, not lost',
      claim: 'Delivery logs show the batch was throttled and about 40 notices were deferred.',
      explanation: 'Stated in the internal delivery-log review on September 15.',
      status: 'verified',
      basis: 'direct',
      supportingEvidenceIds: ['ev-cv-slack-001', 'ev-cv-gmail-001'],
      contradictingEvidenceIds: [],
    },
    {
      id: `${CV}:f2`,
      investigationId: CV,
      title: 'Fix shipped and notices re-sent',
      claim: 'ENG-2144 was resolved and deferred notices were re-sent.',
      explanation: 'Recorded in the resolved ticket.',
      status: 'verified',
      basis: 'direct',
      supportingEvidenceIds: ['ev-cv-jira-001'],
      contradictingEvidenceIds: [],
    },
  ],
  timeline: [
    { id: `${CV}:t1`, investigationId: CV, title: 'LPs report missing notices', description: 'Customer asks whether the notices were delivered.', eventType: 'customer_request', occurredAt: '2026-09-14T13:20:00Z', precision: 'exact', actor: 'Marta Kowal', provider: 'gmail', evidenceIds: ['ev-cv-gmail-001'], relatedFindingIds: [`${CV}:f1`], relatedCommitmentIds: [] },
    { id: `${CV}:t2`, investigationId: CV, title: 'Delivery logs show throttling', description: 'About 40 notices were deferred by the mail provider.', eventType: 'internal_discussion', occurredAt: '2026-09-15T10:05:00Z', precision: 'exact', actor: 'Chloe Tan', provider: 'slack', evidenceIds: ['ev-cv-slack-001'], relatedFindingIds: [`${CV}:f1`], relatedCommitmentIds: [] },
    { id: `${CV}:t3`, investigationId: CV, title: 'ENG-2144 resolved', description: 'Sender paces delivery; deferred notices re-sent.', eventType: 'ticket_change', occurredAt: '2026-09-18T15:00:00Z', precision: 'exact', actor: 'Reza Ahmadi', provider: 'jira', evidenceIds: ['ev-cv-jira-001'], relatedFindingIds: [`${CV}:f2`], relatedCommitmentIds: [`${CV}:c1`] },
  ],
  commitments: [
    {
      id: `${CV}:c1`,
      investigationId: CV,
      statement: 'Re-send deferred capital call notices.',
      owner: 'Reza Ahmadi',
      dueAt: '2026-09-18T00:00:00Z',
      status: 'fulfilled',
      evidenceIds: ['ev-cv-jira-001'],
    },
  ],
  gaps: [],
  contradictions: [],
  actions: [
    {
      id: `${CV}:a1`,
      investigationId: CV,
      title: 'Tell Cobalt the deferred notices were re-sent',
      rationale: 'The customer asked for confirmation of delivery.',
      suggestedOwner: 'Jordan Ellis',
      priority: 'medium',
      relatedFindingIds: [`${CV}:f2`],
      relatedEvidenceIds: ['ev-cv-jira-001'],
      status: 'completed',
      notes: [],
      createdAt: '2026-09-18T15:30:00Z',
      updatedAt: '2026-09-19T09:00:00Z',
    },
  ],
}

// ═════════════════════════════ Meridian Trust ═════════════════════════════

const MT = 'inv-meridian-sso'

const meridian: Analysis = {
  customerKey: 'meridian',
  summary: {
    overview: [
      { text: 'LP sign-in loops through the identity provider began after a certificate rotation on the customer side. ', evidenceIds: ['ev-mt-slack-001'] },
      { text: 'Engineering is waiting for the new signing-certificate metadata from Meridian.', evidenceIds: ['ev-mt-jira-001'] },
    ],
    status: [{ text: 'Blocked on customer-provided metadata.', evidenceIds: ['ev-mt-jira-001'] }],
    blocker: [{ text: 'Signing-certificate metadata from Meridian has not been received.', evidenceIds: ['ev-mt-jira-001'] }],
    nextStep: [{ text: 'Request the metadata from Meridian.', evidenceIds: ['ev-mt-jira-001'] }],
  },
  findings: [
    {
      id: `${MT}:f1`,
      investigationId: MT,
      title: 'Loop started after the customer rotated a certificate',
      claim: 'The redirect loop began after the certificate rotation on the customer side.',
      explanation: 'Stated by one implementer; no log or timestamp confirms the order of events.',
      status: 'needs_verification',
      basis: 'direct',
      supportingEvidenceIds: ['ev-mt-slack-001'],
      contradictingEvidenceIds: [],
    },
    {
      id: `${MT}:f2`,
      investigationId: MT,
      title: 'Engineering is waiting on the customer',
      claim: 'The SSO configuration cannot be updated until Meridian sends new certificate metadata.',
      explanation: 'Recorded in the ENG-2260 comment of October 8.',
      status: 'verified',
      basis: 'direct',
      supportingEvidenceIds: ['ev-mt-jira-001', 'ev-mt-confluence-001'],
      contradictingEvidenceIds: [],
    },
  ],
  timeline: [
    { id: `${MT}:t1`, investigationId: MT, title: 'Sign-in redirect loop reported', description: 'LPs loop when signing in through their identity provider.', eventType: 'internal_discussion', occurredAt: '2026-10-06T14:10:00Z', precision: 'exact', actor: 'Chloe Tan', provider: 'slack', evidenceIds: ['ev-mt-slack-001'], relatedFindingIds: [`${MT}:f1`], relatedCommitmentIds: [] },
    { id: `${MT}:t2`, investigationId: MT, title: 'Runbook describes the metadata update', description: 'Update identity provider metadata, then test with a pilot LP.', eventType: 'document_update', occurredAt: '2026-10-07T08:15:00Z', precision: 'exact', actor: 'Reza Ahmadi', provider: 'confluence', evidenceIds: ['ev-mt-confluence-001'], relatedFindingIds: [`${MT}:f2`], relatedCommitmentIds: [] },
    { id: `${MT}:t3`, investigationId: MT, title: 'Engineering waits on certificate metadata', description: 'The SSO configuration cannot be updated without it.', eventType: 'blocker', occurredAt: '2026-10-08T12:30:00Z', precision: 'exact', actor: 'Reza Ahmadi', provider: 'jira', evidenceIds: ['ev-mt-jira-001'], relatedFindingIds: [`${MT}:f2`], relatedCommitmentIds: [] },
  ],
  commitments: [],
  gaps: [
    {
      id: `${MT}:g1`,
      investigationId: MT,
      missing: 'Teams conversations with Meridian IT could not be read.',
      whyItMatters: 'The customer may have sent the metadata or discussed the rotation there.',
      resolvingEvidence: 'Restored Teams access, or a manual export from the Meridian IT channel.',
      followUp: 'Reconnect the Teams connector, then re-run the investigation.',
      relatedEvidenceIds: ['ev-mt-teams-001'],
      review: 'unresolved',
    },
  ],
  contradictions: [],
  actions: [
    {
      id: `${MT}:a1`,
      investigationId: MT,
      title: 'Request signing-certificate metadata from Meridian',
      rationale: 'It is the one input Engineering says is missing.',
      suggestedOwner: 'Taylor Brooks',
      priority: 'high',
      relatedFindingIds: [`${MT}:f2`],
      relatedEvidenceIds: ['ev-mt-jira-001'],
      status: 'accepted',
      notes: [],
      createdAt: SEED_AT,
      updatedAt: SEED_AT,
    },
  ],
}

const northstar: Analysis = {
  customerKey: 'northstar',
  summary: nsSummary,
  findings: nsFindings,
  timeline: nsTimeline,
  commitments: nsCommitments,
  gaps: nsGaps,
  contradictions: nsContradictions,
  actions: nsActions,
}

export const seedAnalyses: Record<string, Analysis> = {
  [NS]: northstar,
  [CV]: cobalt,
  [MT]: meridian,
}

/** Template used when a new investigation matches a customer. Keyed by customerKey. */
export const analysisTemplates: Record<string, { sourceId: string; analysis: Analysis }> = {
  northstar: { sourceId: NS, analysis: northstar },
  cobalt: { sourceId: CV, analysis: cobalt },
  meridian: { sourceId: MT, analysis: meridian },
}

// ═════════════════════════════ Investigations ═════════════════════════════

const nsCoverage: SourceCoverage[] = [
  { provider: 'gmail', status: 'searched', recordsFound: 6, searchedAt: '2026-10-15T07:00:00Z' },
  { provider: 'slack', status: 'searched', recordsFound: 8, searchedAt: '2026-10-15T07:00:00Z' },
  { provider: 'jira', status: 'partial', recordsFound: 3, searchedAt: '2026-10-15T07:00:00Z', warning: 'Comment history for project ENG is only partially indexed.' },
  { provider: 'confluence', status: 'searched', recordsFound: 1, searchedAt: '2026-10-15T07:00:00Z' },
  { provider: 'notion', status: 'searched', recordsFound: 2, searchedAt: '2026-10-15T07:00:00Z' },
  { provider: 'teams', status: 'permission_denied', warning: 'Access was revoked. Teams conversations were not searched.' },
  { provider: 'salesforce', status: 'search_failed', warning: 'The last CRM sync failed, so account activity was not searched.' },
]

export const seedInvestigations: Investigation[] = [
  {
    id: NS,
    title: 'Investor onboarding delay',
    problemStatement:
      'The customer says the investor onboarding workflow was expected to be ready last Friday, but the process is still blocked. Investigate what was promised, what changed, and what is preventing completion.',
    customerName: 'Northstar Capital',
    projectName: 'Investor onboarding workflow',
    ticketId: 'IMPL-482',
    owner: 'Alex Morgan',
    status: 'needs_review',
    selectedProviders: ['gmail', 'slack', 'jira', 'confluence', 'notion', 'teams', 'salesforce'],
    coverage: nsCoverage,
    summary: nsSummary,
    createdAt: '2026-10-12T09:30:00Z',
    updatedAt: '2026-10-15T07:05:00Z',
    lastRunAt: '2026-10-15T07:00:00Z',
    runCount: 1,
    analysisVersion: 1,
  },
  {
    id: MT,
    title: 'LP portal sign-in redirect loop',
    problemStatement:
      'LPs at Meridian Trust loop back to the sign-in page when authenticating through their identity provider. Establish when it started and what is needed to fix it.',
    customerName: 'Meridian Trust',
    projectName: 'LP portal SSO',
    ticketId: 'ENG-2260',
    owner: 'Taylor Brooks',
    status: 'blocked',
    selectedProviders: ['gmail', 'slack', 'jira', 'confluence', 'teams'],
    coverage: [
      { provider: 'gmail', status: 'no_matches', recordsFound: 0, searchedAt: '2026-10-14T10:00:00Z' },
      { provider: 'slack', status: 'searched', recordsFound: 1, searchedAt: '2026-10-14T10:00:00Z' },
      { provider: 'jira', status: 'partial', recordsFound: 1, searchedAt: '2026-10-14T10:00:00Z', warning: 'Comment history for project ENG is only partially indexed.' },
      { provider: 'confluence', status: 'partial', recordsFound: 1, searchedAt: '2026-10-14T10:00:00Z', warning: 'One page was only partly extracted.' },
      { provider: 'teams', status: 'permission_denied', warning: 'Access was revoked. Teams conversations were not searched.' },
    ],
    summary: meridian.summary,
    createdAt: '2026-10-09T08:00:00Z',
    updatedAt: '2026-10-14T10:05:00Z',
    lastRunAt: '2026-10-14T10:00:00Z',
    runCount: 1,
    analysisVersion: 1,
  },
  {
    id: CV,
    title: 'Capital call notices not delivered',
    problemStatement:
      'Several LPs say they did not receive a capital call notice. Confirm whether notices were delivered and why not.',
    customerName: 'Cobalt Ventures',
    projectName: 'Capital call notices',
    ticketId: 'ENG-2144',
    owner: 'Jordan Ellis',
    status: 'resolved',
    selectedProviders: ['gmail', 'slack', 'jira', 'notion'],
    coverage: [
      { provider: 'gmail', status: 'searched', recordsFound: 1, searchedAt: '2026-09-19T08:00:00Z' },
      { provider: 'slack', status: 'searched', recordsFound: 1, searchedAt: '2026-09-19T08:00:00Z' },
      { provider: 'jira', status: 'searched', recordsFound: 1, searchedAt: '2026-09-19T08:00:00Z' },
      { provider: 'notion', status: 'partial', recordsFound: 1, searchedAt: '2026-09-19T08:00:00Z', warning: 'One page contains content that could not be extracted.' },
    ],
    summary: cobalt.summary,
    summaryReviewedBy: 'Jordan Ellis',
    summaryReviewedAt: '2026-09-19T09:00:00Z',
    createdAt: '2026-09-14T14:00:00Z',
    updatedAt: '2026-09-19T09:10:00Z',
    lastRunAt: '2026-09-19T08:00:00Z',
    runCount: 1,
    analysisVersion: 1,
    resolvedAt: '2026-09-19T09:10:00Z',
    resolvedBy: 'Jordan Ellis',
  },
  {
    id: 'inv-harbor-export',
    title: 'Quarterly report export mismatch',
    problemStatement:
      'Harbor Peak Partners reports that totals in the exported quarterly report differ from the portal view. Determine which figures differ and when the discrepancy started.',
    customerName: 'Harbor Peak Partners',
    projectName: 'Quarterly reporting',
    owner: 'Alex Morgan',
    status: 'draft',
    selectedProviders: ['gmail', 'slack'],
    coverage: [],
    summary: null,
    createdAt: '2026-10-15T11:20:00Z',
    updatedAt: '2026-10-15T11:20:00Z',
    runCount: 0,
    analysisVersion: 0,
  },
  {
    id: 'inv-lakeview-reminders',
    title: 'Signing reminders not sent',
    problemStatement:
      'Lakeview Advisors says automatic signing reminders stopped being sent last week. Find out when they stopped and why.',
    customerName: 'Lakeview Advisors',
    projectName: 'Document signing',
    owner: 'Jordan Ellis',
    status: 'failed',
    selectedProviders: ['gmail', 'slack', 'jira'],
    coverage: [],
    summary: null,
    createdAt: '2026-10-13T15:40:00Z',
    updatedAt: '2026-10-13T15:52:00Z',
    runCount: 0,
    analysisVersion: 0,
    failureReason:
      'The run stopped before any source was searched because the connector index was being rebuilt. Nothing was saved. Retrying is safe.',
  },
]

export const seedFindings = Object.values(seedAnalyses).flatMap((a) => a.findings)
export const seedTimeline = Object.values(seedAnalyses).flatMap((a) => a.timeline)
export const seedCommitments = Object.values(seedAnalyses).flatMap((a) => a.commitments)
export const seedGaps = Object.values(seedAnalyses).flatMap((a) => a.gaps)
export const seedContradictions = Object.values(seedAnalyses).flatMap((a) => a.contradictions)
export const seedActions = Object.values(seedAnalyses).flatMap((a) => a.actions)
