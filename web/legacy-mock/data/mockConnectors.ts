import type {
  ActivityEvent,
  Connector,
  ConnectorScope,
  SourceProvider,
  SyncJob,
} from '@/types/investigator'

/**
 * DEMO DATA — simulated connector configuration. No provider is contacted and
 * no credentials are collected anywhere in this prototype.
 */

export interface ProviderMeta {
  provider: SourceProvider
  name: string
  monogram: string
  description: string
  recordTypes: string
  resourceLabel: string
  resources: { id: string; label: string }[]
  defaultResources: string[]
  contentTypes: { id: string; label: string }[]
  permissions: string[]
  demoAccount: string
  demoWorkspace: string
}

const defaultContent = (labels: [string, string][]) =>
  labels.map(([id, label]) => ({ id, label }))

export const providerMeta: Record<SourceProvider, ProviderMeta> = {
  gmail: {
    provider: 'gmail',
    name: 'Gmail',
    monogram: 'Gm',
    description: 'Email threads, senders and timestamps from shared mailboxes.',
    recordTypes: 'Email, thread, sender, timestamps',
    resourceLabel: 'Mailbox labels',
    resources: [
      { id: 'northstar', label: 'Northstar / Implementation' },
      { id: 'escalations', label: 'Northstar / Escalations' },
      { id: 'support', label: 'Support' },
      { id: 'inbox', label: 'Inbox' },
    ],
    defaultResources: ['northstar', 'escalations', 'support'],
    contentTypes: defaultContent([['threads', 'Threads'], ['attachments', 'Attachment text']]),
    permissions: ['Read messages and labels', 'Read thread metadata'],
    demoAccount: 'cs-team@demo.example',
    demoWorkspace: 'Customer Success mailbox',
  },
  outlook: {
    provider: 'outlook',
    name: 'Outlook',
    monogram: 'Ol',
    description: 'Email and conversations from Microsoft 365 mailboxes.',
    recordTypes: 'Email and conversations',
    resourceLabel: 'Folders',
    resources: [
      { id: 'inbox', label: 'Inbox' },
      { id: 'sent', label: 'Sent items' },
      { id: 'shared', label: 'Shared mailbox' },
    ],
    defaultResources: ['shared'],
    contentTypes: defaultContent([['threads', 'Conversations'], ['attachments', 'Attachment text']]),
    permissions: ['Read mail', 'Read shared mailboxes'],
    demoAccount: 'cs-team@demo-365.example',
    demoWorkspace: 'Demo Microsoft 365 tenant',
  },
  slack: {
    provider: 'slack',
    name: 'Slack',
    monogram: 'Sl',
    description: 'Channel messages and threads from accessible channels.',
    recordTypes: 'Messages, channels, threads',
    resourceLabel: 'Channels',
    resources: [
      { id: 'impl-northstar', label: '#impl-northstar' },
      { id: 'eng-onboarding', label: '#eng-onboarding' },
      { id: 'support-escalations', label: '#support-escalations' },
      { id: 'general', label: '#general' },
    ],
    defaultResources: ['impl-northstar', 'eng-onboarding', 'support-escalations'],
    contentTypes: defaultContent([['messages', 'Messages'], ['threads', 'Thread replies'], ['files', 'File names']]),
    permissions: ['Read public channel history', 'Read channel metadata'],
    demoAccount: 'cs-bot@demo.example',
    demoWorkspace: 'Demo Workspace',
  },
  teams: {
    provider: 'teams',
    name: 'Microsoft Teams',
    monogram: 'Tm',
    description: 'Chats and channel messages from your organization.',
    recordTypes: 'Chats and channel messages',
    resourceLabel: 'Teams and channels',
    resources: [
      { id: 'meridian-it', label: 'Meridian IT channel' },
      { id: 'cs-ops', label: 'CS Operations' },
    ],
    defaultResources: ['cs-ops'],
    contentTypes: defaultContent([['messages', 'Channel messages'], ['chats', 'Group chats']]),
    permissions: ['Read channel messages', 'Read chat messages'],
    demoAccount: 'cs-team@demo-365.example',
    demoWorkspace: 'Demo Microsoft 365 tenant',
  },
  jira: {
    provider: 'jira',
    name: 'Jira',
    monogram: 'Ji',
    description: 'Issues, comments and status history from selected projects.',
    recordTypes: 'Issues, comments, status history',
    resourceLabel: 'Projects',
    resources: [
      { id: 'IMPL', label: 'IMPL · Implementation' },
      { id: 'ENG', label: 'ENG · Engineering' },
      { id: 'SUP', label: 'SUP · Support' },
    ],
    defaultResources: ['IMPL', 'ENG'],
    contentTypes: defaultContent([['issues', 'Issues'], ['comments', 'Comments'], ['history', 'Status history']]),
    permissions: ['Read issues', 'Read comments', 'Read project metadata'],
    demoAccount: 'cs-bot@demo.example',
    demoWorkspace: 'demo-site (Jira site)',
  },
  linear: {
    provider: 'linear',
    name: 'Linear',
    monogram: 'Li',
    description: 'Issues, comments and project activity from selected teams.',
    recordTypes: 'Issues, comments, project activity',
    resourceLabel: 'Teams',
    resources: [
      { id: 'platform', label: 'Platform' },
      { id: 'integrations', label: 'Integrations' },
    ],
    defaultResources: ['integrations'],
    contentTypes: defaultContent([['issues', 'Issues'], ['comments', 'Comments']]),
    permissions: ['Read issues', 'Read comments'],
    demoAccount: 'cs-bot@demo.example',
    demoWorkspace: 'Demo Linear workspace',
  },
  confluence: {
    provider: 'confluence',
    name: 'Confluence',
    monogram: 'Cf',
    description: 'Pages and supported metadata from permitted spaces.',
    recordTypes: 'Pages and metadata',
    resourceLabel: 'Spaces',
    resources: [
      { id: 'IMPL', label: 'IMPL · Implementation' },
      { id: 'KB', label: 'KB · Knowledge base' },
      { id: 'ENG', label: 'ENG · Engineering' },
    ],
    defaultResources: ['IMPL'],
    contentTypes: defaultContent([['pages', 'Pages'], ['comments', 'Page comments']]),
    permissions: ['Read pages', 'Read space metadata'],
    demoAccount: 'cs-bot@demo.example',
    demoWorkspace: 'demo-site (Confluence)',
  },
  notion: {
    provider: 'notion',
    name: 'Notion',
    monogram: 'No',
    description: 'Pages and databases shared with the integration.',
    recordTypes: 'Pages and databases',
    resourceLabel: 'Pages and databases',
    resources: [
      { id: 'customers', label: 'Customer workspace' },
      { id: 'projects', label: 'Projects database' },
      { id: 'meetings', label: 'Meeting notes' },
    ],
    defaultResources: ['customers', 'projects'],
    contentTypes: defaultContent([['pages', 'Pages'], ['databases', 'Database rows']]),
    permissions: ['Read content shared with the integration'],
    demoAccount: 'cs-bot@demo.example',
    demoWorkspace: 'Demo Notion workspace',
  },
  google_drive: {
    provider: 'google_drive',
    name: 'Google Drive',
    monogram: 'Gd',
    description: 'Documents and file metadata from authorized folders.',
    recordTypes: 'Documents and file metadata',
    resourceLabel: 'Folders',
    resources: [
      { id: 'customers', label: 'Customer files' },
      { id: 'contracts', label: 'Contracts' },
      { id: 'shared', label: 'Shared drives' },
    ],
    defaultResources: ['customers'],
    contentTypes: defaultContent([['docs', 'Documents'], ['sheets', 'Spreadsheets'], ['pdfs', 'PDF text']]),
    permissions: ['Read file metadata', 'Read file content'],
    demoAccount: 'cs-team@demo.example',
    demoWorkspace: 'Demo Drive',
  },
  salesforce: {
    provider: 'salesforce',
    name: 'Salesforce',
    monogram: 'Sf',
    description: 'Accounts, contacts and supported activity records.',
    recordTypes: 'Accounts, contacts, activity',
    resourceLabel: 'Objects',
    resources: [
      { id: 'accounts', label: 'Accounts' },
      { id: 'contacts', label: 'Contacts' },
      { id: 'activities', label: 'Activities' },
      { id: 'cases', label: 'Cases' },
    ],
    defaultResources: ['accounts', 'activities'],
    contentTypes: defaultContent([['records', 'Records'], ['notes', 'Notes']]),
    permissions: ['Read selected objects', 'Read activity history'],
    demoAccount: 'cs-bot@demo.example',
    demoWorkspace: 'Demo Salesforce org',
  },
}

/** Providers that can be connected today. Every other provider is shown as "coming soon". */
export const supportedProviders: SourceProvider[] = ['gmail', 'slack', 'jira', 'confluence', 'notion']

export const isSupported = (p: SourceProvider): boolean => supportedProviders.includes(p)

export const providerOrder: SourceProvider[] = [
  'gmail',
  'outlook',
  'slack',
  'teams',
  'jira',
  'linear',
  'confluence',
  'notion',
  'google_drive',
  'salesforce',
]

export const emptyScope: ConnectorScope = {
  resources: [],
  dateRange: '90d',
  contentTypes: [],
  includeArchived: false,
}

export const defaultScopeFor = (provider: SourceProvider): ConnectorScope => ({
  resources: [...providerMeta[provider].defaultResources],
  dateRange: '90d',
  contentTypes: providerMeta[provider].contentTypes.map((c) => c.id),
  includeArchived: false,
})

function seedConnector(
  provider: SourceProvider,
  patch: Partial<Connector> = {},
): Connector {
  const meta = providerMeta[provider]
  return {
    id: provider,
    provider,
    status: 'not_connected',
    scope: { ...emptyScope },
    grantedPermissions: [],
    indexedRecordCount: 0,
    isDemo: true,
    ...(patch.status && patch.status !== 'not_connected'
      ? {
          accountLabel: meta.demoAccount,
          workspaceLabel: meta.demoWorkspace,
          scope: defaultScopeFor(provider),
          grantedPermissions: meta.permissions,
        }
      : {}),
    ...patch,
  }
}

export const seedConnectors: Connector[] = [
  seedConnector('gmail', { status: 'sync_completed', lastSuccessfulSyncAt: '2026-10-15T06:12:00Z', lastPermissionCheckAt: '2026-10-15T06:00:00Z', indexedRecordCount: 1284 }),
  seedConnector('outlook'),
  seedConnector('slack', { status: 'sync_completed', lastSuccessfulSyncAt: '2026-10-15T06:20:00Z', lastPermissionCheckAt: '2026-10-15T06:00:00Z', indexedRecordCount: 5932 }),
  seedConnector('teams', {
    status: 'permission_revoked',
    lastSuccessfulSyncAt: '2026-10-08T06:10:00Z',
    lastPermissionCheckAt: '2026-10-14T06:00:00Z',
    indexedRecordCount: 411,
    errorMessage: 'The Teams administrator revoked consent for this connector. Reconnect to restore access.',
  }),
  seedConnector('jira', {
    status: 'needs_attention',
    lastSuccessfulSyncAt: '2026-10-15T06:30:00Z',
    lastPermissionCheckAt: '2026-10-15T06:00:00Z',
    indexedRecordCount: 842,
    errorMessage: 'The last sync was partial: comment history for project ENG could not be fully read.',
  }),
  seedConnector('linear'),
  seedConnector('confluence', { status: 'sync_completed', lastSuccessfulSyncAt: '2026-10-15T06:40:00Z', lastPermissionCheckAt: '2026-10-15T06:00:00Z', indexedRecordCount: 276 }),
  seedConnector('notion', { status: 'sync_completed', lastSuccessfulSyncAt: '2026-10-15T06:45:00Z', lastPermissionCheckAt: '2026-10-15T06:00:00Z', indexedRecordCount: 198 }),
  seedConnector('google_drive'),
  seedConnector('salesforce', {
    status: 'sync_failed',
    lastSuccessfulSyncAt: '2026-10-10T06:00:00Z',
    lastPermissionCheckAt: '2026-10-15T06:00:00Z',
    indexedRecordCount: 96,
    errorMessage: 'The provider rejected the session. Re-authorize or retry the sync.',
  }),
]

export const seedSyncJobs: SyncJob[] = [
  { id: 'sync-0001', connectorId: 'gmail', status: 'completed', trigger: 'manual', stage: 4, startedAt: '2026-10-15T06:00:00Z', completedAt: '2026-10-15T06:12:00Z', recordsFetched: 1284, recordsIndexed: 1284, recordsSkipped: 0 },
  { id: 'sync-0002', connectorId: 'slack', status: 'completed', trigger: 'manual', stage: 4, startedAt: '2026-10-15T06:05:00Z', completedAt: '2026-10-15T06:20:00Z', recordsFetched: 5940, recordsIndexed: 5932, recordsSkipped: 8 },
  { id: 'sync-0003', connectorId: 'jira', status: 'partial', trigger: 'manual', stage: 4, startedAt: '2026-10-15T06:15:00Z', completedAt: '2026-10-15T06:30:00Z', recordsFetched: 910, recordsIndexed: 842, recordsSkipped: 68, errorCode: 'PARTIAL_PERMISSION', errorMessage: 'Comment history for project ENG could not be read for 68 issues. The connected account lacks access to those comments.' },
  { id: 'sync-0004', connectorId: 'jira', status: 'completed', trigger: 'manual', stage: 4, startedAt: '2026-10-08T06:00:00Z', completedAt: '2026-10-08T06:14:00Z', recordsFetched: 780, recordsIndexed: 780, recordsSkipped: 0 },
  { id: 'sync-0005', connectorId: 'confluence', status: 'completed', trigger: 'manual', stage: 4, startedAt: '2026-10-15T06:25:00Z', completedAt: '2026-10-15T06:40:00Z', recordsFetched: 280, recordsIndexed: 276, recordsSkipped: 4 },
  { id: 'sync-0006', connectorId: 'notion', status: 'completed', trigger: 'manual', stage: 4, startedAt: '2026-10-15T06:30:00Z', completedAt: '2026-10-15T06:45:00Z', recordsFetched: 201, recordsIndexed: 198, recordsSkipped: 3 },
  { id: 'sync-0007', connectorId: 'teams', status: 'completed', trigger: 'manual', stage: 4, startedAt: '2026-10-08T06:00:00Z', completedAt: '2026-10-08T06:10:00Z', recordsFetched: 411, recordsIndexed: 411, recordsSkipped: 0 },
  { id: 'sync-0008', connectorId: 'teams', status: 'failed', trigger: 'manual', stage: 1, startedAt: '2026-10-14T06:00:00Z', completedAt: '2026-10-14T06:01:00Z', recordsFetched: 0, recordsIndexed: 0, recordsSkipped: 0, errorCode: 'CONSENT_REVOKED', errorMessage: 'Consent for this connector was revoked in the Microsoft 365 admin center. No records were read.' },
  { id: 'sync-0009', connectorId: 'salesforce', status: 'completed', trigger: 'manual', stage: 4, startedAt: '2026-10-10T06:00:00Z', completedAt: '2026-10-10T06:06:00Z', recordsFetched: 96, recordsIndexed: 96, recordsSkipped: 0 },
  { id: 'sync-0010', connectorId: 'salesforce', status: 'failed', trigger: 'manual', stage: 1, startedAt: '2026-10-15T06:50:00Z', completedAt: '2026-10-15T06:51:00Z', recordsFetched: 0, recordsIndexed: 0, recordsSkipped: 0, errorCode: 'AUTH_EXPIRED', errorMessage: 'The provider rejected the session token (authentication expired). No records were changed. Retrying is safe.' },
]

export const seedActivity: ActivityEvent[] = [
  { id: 'act-seed-01', kind: 'investigation_created', label: 'Investigation created', actor: 'Alex Morgan', relatedType: 'investigation', relatedId: 'inv-northstar-onboarding', relatedLabel: 'Investor onboarding delay', at: '2026-10-12T09:30:00Z', outcome: 'success' },
  { id: 'act-seed-02', kind: 'investigation_rerun', label: 'Investigation run completed', actor: 'The Investigator (simulated)', relatedType: 'investigation', relatedId: 'inv-northstar-onboarding', relatedLabel: 'Investor onboarding delay', at: '2026-10-15T07:00:00Z', outcome: 'warning', detail: '5 of 7 sources searched. Teams and Salesforce were not searched.' },
  { id: 'act-seed-03', kind: 'sync_completed', label: 'Sync completed', actor: 'System', relatedType: 'connector', relatedId: 'gmail', relatedLabel: 'Gmail', at: '2026-10-15T06:12:00Z', outcome: 'success', detail: '1,284 records indexed.' },
  { id: 'act-seed-04', kind: 'sync_completed', label: 'Sync partially completed', actor: 'System', relatedType: 'connector', relatedId: 'jira', relatedLabel: 'Jira', at: '2026-10-15T06:30:00Z', outcome: 'warning', detail: '68 records skipped.' },
  { id: 'act-seed-05', kind: 'sync_failed', label: 'Sync failed', actor: 'System', relatedType: 'connector', relatedId: 'salesforce', relatedLabel: 'Salesforce', at: '2026-10-15T06:51:00Z', outcome: 'failed', detail: 'Authentication expired.' },
  { id: 'act-seed-06', kind: 'sync_failed', label: 'Sync failed', actor: 'System', relatedType: 'connector', relatedId: 'teams', relatedLabel: 'Microsoft Teams', at: '2026-10-14T06:01:00Z', outcome: 'failed', detail: 'Consent revoked.' },
  { id: 'act-seed-07', kind: 'investigation_resolved', label: 'Investigation resolved', actor: 'Jordan Ellis', relatedType: 'investigation', relatedId: 'inv-cobalt-notices', relatedLabel: 'Capital call notices not delivered', at: '2026-09-19T09:10:00Z', outcome: 'success' },
]
