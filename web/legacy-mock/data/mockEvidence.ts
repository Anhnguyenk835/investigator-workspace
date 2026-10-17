import type { EvidenceRecord, SourceProvider } from '@/types/investigator'

/**
 * DEMO DATA — synthetic records for a fictional scenario. Nothing here refers to a
 * real customer, person or system. None of these records carries a real URL.
 */

const INGESTED_AT = '2026-10-15T06:00:00Z'
const INDEXED_AT = '2026-10-15T06:12:00Z'

type Seed = Omit<
  EvidenceRecord,
  'ingestedAt' | 'indexedAt' | 'isDemo' | 'indexStatus' | 'timestampPrecision'
> &
  Partial<
    Pick<EvidenceRecord, 'indexStatus' | 'timestampPrecision' | 'indexedAt'>
  >

function rec(seed: Seed): EvidenceRecord {
  const indexStatus = seed.indexStatus ?? 'indexed'
  return {
    timestampPrecision: 'exact',
    ...seed,
    indexStatus,
    ingestedAt: INGESTED_AT,
    indexedAt: indexStatus === 'unavailable' ? undefined : (seed.indexedAt ?? INDEXED_AT),
    isDemo: true,
  }
}

const NS = {
  customerName: 'Northstar Capital',
  projectName: 'Investor onboarding workflow',
} as const
const CV = {
  customerName: 'Cobalt Ventures',
  projectName: 'Capital call notices',
} as const
const MT = {
  customerName: 'Meridian Trust',
  projectName: 'LP portal SSO',
} as const

const ref = (provider: SourceProvider, path: string) => `demo://${provider}/${path}`

export const mockEvidence: EvidenceRecord[] = [
  // ── Northstar · Gmail ────────────────────────────────────────────────
  rec({
    id: 'ev-gmail-001',
    provider: 'gmail',
    recordType: 'email',
    externalRecordId: 'thr-ns-0001',
    title: 'Fund II close — investor onboarding workflow',
    author: 'Priya Raman',
    authorSide: 'customer',
    timestamp: '2026-10-01T14:12:00Z',
    excerpt:
      'We need the investor onboarding workflow live before our Fund II close. Our target is to start sending invitations to investors the week of October 12, so we would like everything ready by October 9 if possible.',
    context:
      'Priya Raman (Northstar Capital) to the implementation mailbox. Thread continues with a reply from Sam Lindqvist.',
    location: 'Label: Northstar / Implementation',
    sourceRef: ref('gmail', 'northstar/thr-ns-0001'),
    ...NS,
  }),
  rec({
    id: 'ev-gmail-002',
    provider: 'gmail',
    recordType: 'email',
    externalRecordId: 'thr-ns-0001-r1',
    title: 'Re: Fund II close — investor onboarding workflow',
    author: 'Sam Lindqvist',
    authorSide: 'internal',
    timestamp: '2026-10-01T16:40:00Z',
    excerpt:
      "We can have the workflow configured and ready for your investors by Friday, October 9. That assumes your KYC provider's sandbox credentials reach us by Monday, October 5, so we can test identity verification end to end.",
    context:
      'Reply in the same thread as ev-gmail-001. The date is stated together with a dependency on customer-side credentials.',
    location: 'Label: Northstar / Implementation',
    sourceRef: ref('gmail', 'northstar/thr-ns-0001-r1'),
    ...NS,
  }),
  rec({
    id: 'ev-gmail-003',
    provider: 'gmail',
    recordType: 'email',
    externalRecordId: 'thr-ns-0002',
    title: 'Accreditation questionnaire and KYC credentials',
    author: 'Daniel Whitfield',
    authorSide: 'customer',
    timestamp: '2026-10-06T10:22:00Z',
    excerpt:
      'Attached is the signed accreditation questionnaire. Our KYC vendor is still provisioning the sandbox account; we expect to send the credentials tomorrow, October 7.',
    context: 'Daniel Whitfield is the compliance lead at Northstar Capital.',
    location: 'Label: Northstar / Implementation',
    sourceRef: ref('gmail', 'northstar/thr-ns-0002'),
    ...NS,
  }),
  rec({
    id: 'ev-gmail-004',
    provider: 'gmail',
    recordType: 'email',
    externalRecordId: 'thr-ns-0003',
    title: 'Quick status on the onboarding workflow',
    author: 'Sam Lindqvist',
    authorSide: 'internal',
    timestamp: '2026-10-08T16:15:00Z',
    excerpt:
      "Quick update: we're on track for Friday. Final testing is today and I'll confirm as soon as it's complete.",
    context:
      'Sent to Priya Raman. The message does not mention the credentials or any open defect.',
    location: 'Label: Northstar / Implementation',
    sourceRef: ref('gmail', 'northstar/thr-ns-0003'),
    ...NS,
  }),
  rec({
    id: 'ev-gmail-005',
    provider: 'gmail',
    recordType: 'email',
    externalRecordId: 'thr-ns-0004',
    title: 'Onboarding still blocked — escalation',
    author: 'Priya Raman',
    authorSide: 'customer',
    timestamp: '2026-10-12T09:02:00Z',
    excerpt:
      'We were told the workflow would be ready last Friday and it is still blocked. Our investors are waiting on invitations. I need a clear explanation and a firm date, otherwise I will need to raise this with our CEO.',
    context: 'Sent to the implementation mailbox with the CS manager in copy.',
    location: 'Label: Northstar / Escalations',
    sourceRef: ref('gmail', 'northstar/thr-ns-0004'),
    ...NS,
  }),
  rec({
    id: 'ev-gmail-006',
    provider: 'gmail',
    recordType: 'email',
    externalRecordId: 'thr-ns-0005',
    title: 'KYC sandbox credentials sent',
    author: 'Daniel Whitfield',
    authorSide: 'customer',
    timestamp: '2026-10-12T18:44:00Z',
    excerpt:
      "I've sent the KYC sandbox credentials to the support address this evening. Please confirm once your team has them.",
    context:
      'Addressed to the shared support mailbox rather than the implementation mailbox. No reply is present in the searched mailbox.',
    location: 'Label: Northstar / Implementation',
    sourceRef: ref('gmail', 'northstar/thr-ns-0005'),
    ...NS,
  }),

  // ── Northstar · Slack ────────────────────────────────────────────────
  rec({
    id: 'ev-slack-001',
    provider: 'slack',
    recordType: 'chat_message',
    externalRecordId: 'msg-1759396260.0001',
    title: 'Message in #impl-northstar',
    author: 'Sam Lindqvist',
    authorSide: 'internal',
    timestamp: '2026-10-02T09:31:00Z',
    excerpt:
      "I told Priya we'd be ready Friday the 9th. That depends on their KYC vendor sandbox creds and the signed accreditation questionnaire. Opening IMPL-482 to track.",
    location: '#impl-northstar',
    sourceRef: ref('slack', 'impl-northstar/1759396260.0001'),
    ...NS,
  }),
  rec({
    id: 'ev-slack-002',
    provider: 'slack',
    recordType: 'chat_message',
    externalRecordId: 'msg-1759679280.0002',
    title: 'Message in #impl-northstar',
    author: 'Chloe Tan',
    authorSide: 'internal',
    timestamp: '2026-10-05T15:48:00Z',
    excerpt:
      "Monday check-in: Northstar hasn't sent the KYC credentials yet. I can build the workflow steps without them but can't test identity verification.",
    location: '#impl-northstar',
    sourceRef: ref('slack', 'impl-northstar/1759679280.0002'),
    ...NS,
  }),
  rec({
    id: 'ev-slack-003',
    provider: 'slack',
    recordType: 'chat_message',
    externalRecordId: 'msg-1759858200.0003',
    title: 'Message in #impl-northstar',
    author: 'Sam Lindqvist',
    authorSide: 'internal',
    timestamp: '2026-10-07T17:30:00Z',
    excerpt:
      "Still no creds from Northstar. Friday is looking tight. I'll hold off telling Priya until we know what Reza finds in UAT.",
    location: '#impl-northstar',
    sourceRef: ref('slack', 'impl-northstar/1759858200.0003'),
    ...NS,
  }),
  rec({
    id: 'ev-slack-004',
    provider: 'slack',
    recordType: 'chat_message',
    externalRecordId: 'msg-1759915440.0004',
    title: 'Message in #eng-onboarding',
    author: 'Reza Ahmadi',
    authorSide: 'internal',
    timestamp: '2026-10-08T09:14:00Z',
    excerpt:
      'UAT found a defect: investor entity-type mapping fails for trusts, so those investors cannot complete onboarding. Filed as ENG-2291. Not a config issue.',
    location: '#eng-onboarding',
    sourceRef: ref('slack', 'eng-onboarding/1759915440.0004'),
    ...NS,
  }),
  rec({
    id: 'ev-slack-005',
    provider: 'slack',
    recordType: 'chat_message',
    externalRecordId: 'msg-1759921320.0005',
    title: 'Message in #impl-northstar',
    author: 'Alex Morgan',
    authorSide: 'internal',
    timestamp: '2026-10-08T11:02:00Z',
    excerpt:
      "Has anyone told Northstar about the trust-mapping bug? Their last email I can see still says Friday.",
    location: '#impl-northstar',
    sourceRef: ref('slack', 'impl-northstar/1759921320.0005'),
    ...NS,
  }),
  rec({
    id: 'ev-slack-006',
    provider: 'slack',
    recordType: 'chat_message',
    externalRecordId: 'msg-1760029500.0006',
    title: 'Message in #impl-northstar',
    author: 'Sam Lindqvist',
    authorSide: 'internal',
    timestamp: '2026-10-09T17:05:00Z',
    excerpt:
      "We missed today's date. Updated the project page with a revised target. I still need to call Priya.",
    location: '#impl-northstar',
    sourceRef: ref('slack', 'impl-northstar/1760029500.0006'),
    ...NS,
  }),
  rec({
    id: 'ev-slack-007',
    provider: 'slack',
    recordType: 'chat_message',
    externalRecordId: 'msg-1760350320.0007',
    title: 'Message in #impl-northstar',
    author: 'Chloe Tan',
    authorSide: 'internal',
    timestamp: '2026-10-13T10:12:00Z',
    excerpt:
      "Daniel's email says the creds went to support@ last night. I haven't seen them in our queue. Can someone check the support inbox?",
    location: '#impl-northstar',
    sourceRef: ref('slack', 'impl-northstar/1760350320.0007'),
    ...NS,
  }),
  rec({
    id: 'ev-slack-008',
    provider: 'slack',
    recordType: 'chat_message',
    externalRecordId: 'msg-1760455500.0008',
    title: 'Message in #eng-onboarding',
    author: 'Reza Ahmadi',
    authorSide: 'internal',
    timestamp: '2026-10-14T15:25:00Z',
    excerpt:
      'ENG-2291 fix is merged to staging. Regression pass is still pending, so I would not call it done yet.',
    location: '#eng-onboarding',
    sourceRef: ref('slack', 'eng-onboarding/1760455500.0008'),
    ...NS,
  }),

  // ── Northstar · Jira ─────────────────────────────────────────────────
  rec({
    id: 'ev-jira-001',
    provider: 'jira',
    recordType: 'issue',
    externalRecordId: 'IMPL-482',
    title: 'IMPL-482 · Configure investor onboarding workflow (Northstar)',
    author: 'Sam Lindqvist',
    authorSide: 'internal',
    timestamp: '2026-10-02T09:05:00Z',
    excerpt:
      'Configure investor onboarding workflow for Northstar Fund II. Due: 2026-10-09. Dependencies: KYC sandbox credentials (customer), accreditation questionnaire (customer).',
    context: 'Created by Sam Lindqvist; assignee Sam Lindqvist; status at creation: To Do.',
    location: 'Project IMPL',
    sourceRef: ref('jira', 'IMPL/IMPL-482'),
    ...NS,
  }),
  rec({
    id: 'ev-jira-002',
    provider: 'jira',
    recordType: 'issue_comment',
    externalRecordId: 'IMPL-482#c-10231',
    title: 'Comment on IMPL-482',
    author: 'Reza Ahmadi',
    authorSide: 'internal',
    timestamp: '2026-10-07T13:05:00Z',
    excerpt:
      'Blocked on customer KYC sandbox credentials. Cannot validate identity-verification step. Moving to Blocked until received.',
    context: 'Status changed from In Progress to Blocked with this comment.',
    location: 'Project IMPL',
    sourceRef: ref('jira', 'IMPL/IMPL-482#c-10231'),
    ...NS,
  }),
  rec({
    id: 'ev-jira-003',
    provider: 'jira',
    recordType: 'issue',
    externalRecordId: 'ENG-2291',
    title: 'ENG-2291 · Entity-type mapping fails for trust investors',
    author: 'Reza Ahmadi',
    authorSide: 'internal',
    timestamp: '2026-10-08T09:40:00Z',
    excerpt:
      'Trust-type investors fail entity-type validation during onboarding. Reproduced in staging. No release date set.',
    context:
      'Comment history for project ENG is only partially indexed, so later updates may be missing.',
    location: 'Project ENG',
    sourceRef: ref('jira', 'ENG/ENG-2291'),
    indexStatus: 'partial',
    ...NS,
  }),

  // ── Northstar · Documentation and project update ─────────────────────
  rec({
    id: 'ev-confluence-001',
    provider: 'confluence',
    recordType: 'page',
    externalRecordId: 'page-88142',
    title: 'Northstar — Investor Onboarding Implementation Plan (v3)',
    author: 'Sam Lindqvist',
    authorSide: 'internal',
    timestamp: '2026-10-02T11:20:00Z',
    excerpt:
      'Go-live: October 9, 2026. Milestones: workflow configuration (Oct 5), KYC integration test (Oct 7), UAT (Oct 8), go-live (Oct 9).',
    context: 'Last edited October 2. The page has no later versions.',
    location: 'Space IMPL › Northstar',
    sourceRef: ref('confluence', 'IMPL/page-88142'),
    ...NS,
  }),
  rec({
    id: 'ev-notion-001',
    provider: 'notion',
    recordType: 'page',
    externalRecordId: 'pg-ns-requirements',
    title: 'Northstar onboarding requirements',
    author: 'Chloe Tan',
    authorSide: 'internal',
    timestamp: '2026-10-02T00:00:00Z',
    timestampPrecision: 'date_only',
    excerpt:
      'Investor types in scope: individuals, entities, trusts. Verification: KYC via customer-managed provider. Accreditation questionnaire required before invitation.',
    context: 'Notion exposes the edit date only; the time of day is not available.',
    location: 'Customer workspace › Northstar',
    sourceRef: ref('notion', 'customers/pg-ns-requirements'),
    ...NS,
  }),
  rec({
    id: 'ev-notion-002',
    provider: 'notion',
    recordType: 'project_update',
    externalRecordId: 'upd-ns-1009',
    title: 'Project update — Northstar onboarding',
    author: 'Sam Lindqvist',
    authorSide: 'internal',
    timestamp: '2026-10-09T17:30:00Z',
    excerpt:
      'Status: Blocked. Revised target: October 20, pending KYC sandbox credentials and the ENG-2291 fix. Customer not yet informed of the revised date.',
    context: 'Posted to the project updates database.',
    location: 'Projects › Northstar onboarding',
    sourceRef: ref('notion', 'projects/upd-ns-1009'),
    ...NS,
  }),

  // ── Cobalt Ventures (resolved case) ──────────────────────────────────
  rec({
    id: 'ev-cv-gmail-001',
    provider: 'gmail',
    recordType: 'email',
    externalRecordId: 'thr-cv-0001',
    title: 'Capital call notices not received by LPs',
    author: 'Marta Kowal',
    authorSide: 'customer',
    timestamp: '2026-09-14T13:20:00Z',
    excerpt:
      'Several of our LPs say they did not receive the capital call notice sent this morning. Can you confirm whether the notices were delivered?',
    location: 'Label: Cobalt / Support',
    sourceRef: ref('gmail', 'cobalt/thr-cv-0001'),
    ...CV,
  }),
  rec({
    id: 'ev-cv-slack-001',
    provider: 'slack',
    recordType: 'chat_message',
    externalRecordId: 'msg-cv-0001',
    title: 'Message in #support-escalations',
    author: 'Chloe Tan',
    authorSide: 'internal',
    timestamp: '2026-09-15T10:05:00Z',
    excerpt:
      'Delivery logs show the notice batch was throttled by the outbound mail provider. About 40 notices were deferred, not lost.',
    location: '#support-escalations',
    sourceRef: ref('slack', 'support-escalations/msg-cv-0001'),
    ...CV,
  }),
  rec({
    id: 'ev-cv-jira-001',
    provider: 'jira',
    recordType: 'issue',
    externalRecordId: 'ENG-2144',
    title: 'ENG-2144 · Batch notice sending exceeds provider rate limit',
    author: 'Reza Ahmadi',
    authorSide: 'internal',
    timestamp: '2026-09-18T15:00:00Z',
    excerpt:
      'Batch sender now paces delivery under the provider limit. Deferred notices were re-sent. Resolved.',
    location: 'Project ENG',
    sourceRef: ref('jira', 'ENG/ENG-2144'),
    ...CV,
  }),
  rec({
    id: 'ev-cv-notion-001',
    provider: 'notion',
    recordType: 'page',
    externalRecordId: 'pg-cv-template',
    title: 'Capital call notice template review',
    author: 'Chloe Tan',
    authorSide: 'internal',
    timestamp: '2026-09-16T00:00:00Z',
    timestampPrecision: 'date_only',
    excerpt: 'Embedded spreadsheet with delivery counts could not be extracted.',
    location: 'Customer workspace › Cobalt',
    sourceRef: ref('notion', 'customers/pg-cv-template'),
    indexStatus: 'unsupported',
    ...CV,
  }),

  // ── Meridian Trust (blocked case) ────────────────────────────────────
  rec({
    id: 'ev-mt-slack-001',
    provider: 'slack',
    recordType: 'chat_message',
    externalRecordId: 'msg-mt-0001',
    title: 'Message in #support-escalations',
    author: 'Chloe Tan',
    authorSide: 'internal',
    timestamp: '2026-10-06T14:10:00Z',
    excerpt:
      "Meridian LPs get a redirect loop when signing in through their identity provider. It started after the certificate rotation on their side.",
    location: '#support-escalations',
    sourceRef: ref('slack', 'support-escalations/msg-mt-0001'),
    ...MT,
  }),
  rec({
    id: 'ev-mt-jira-001',
    provider: 'jira',
    recordType: 'issue_comment',
    externalRecordId: 'ENG-2260#c-11002',
    title: 'Comment on ENG-2260',
    author: 'Reza Ahmadi',
    authorSide: 'internal',
    timestamp: '2026-10-08T12:30:00Z',
    excerpt:
      'Need the new signing certificate metadata from Meridian before we can update the SSO configuration. Waiting on customer.',
    location: 'Project ENG',
    sourceRef: ref('jira', 'ENG/ENG-2260#c-11002'),
    ...MT,
  }),
  rec({
    id: 'ev-mt-teams-001',
    provider: 'teams',
    recordType: 'chat_message',
    externalRecordId: 'msg-mt-teams-0001',
    title: 'Channel message — Meridian IT',
    author: 'Unknown',
    timestamp: '2026-10-09T09:00:00Z',
    excerpt: 'Content is not available. Access to this source was revoked.',
    location: 'Meridian IT channel',
    sourceRef: ref('teams', 'meridian-it/msg-mt-teams-0001'),
    indexStatus: 'unavailable',
    ...MT,
  }),
  rec({
    id: 'ev-mt-confluence-001',
    provider: 'confluence',
    recordType: 'page',
    externalRecordId: 'page-90210',
    title: 'SSO configuration runbook — Meridian',
    author: 'Reza Ahmadi',
    authorSide: 'internal',
    timestamp: '2026-10-07T08:15:00Z',
    excerpt:
      'Update the identity provider metadata and re-test sign-in for a pilot LP before enabling for all users.',
    context: 'An embedded sequence diagram was not extracted.',
    location: 'Space IMPL › Meridian',
    sourceRef: ref('confluence', 'IMPL/page-90210'),
    indexStatus: 'partial',
    ...MT,
  }),
]

export const evidenceById = new Map(mockEvidence.map((e) => [e.id, e]))
