import type { SourceProvider } from '@/types/investigator'

export interface ProviderMeta {
  name: string
  description: string
  recordTypes: string
}

export const providerMeta: Record<SourceProvider, ProviderMeta> = {
  gmail: { name: 'Gmail', description: 'Email threads, senders and timestamps from your mailbox.', recordTypes: 'Email, thread, sender, timestamps' },
  outlook: { name: 'Outlook', description: 'Email and conversations from Microsoft 365 mailboxes.', recordTypes: 'Email and conversations' },
  slack: { name: 'Slack', description: 'Channel messages and threads from channels you can read.', recordTypes: 'Messages, channels, threads' },
  teams: { name: 'Microsoft Teams', description: 'Chats and channel messages from your organization.', recordTypes: 'Chats and channel messages' },
  jira: { name: 'Jira', description: 'Issues, comments and status history from your projects.', recordTypes: 'Issues, comments, status history' },
  linear: { name: 'Linear', description: 'Issues, comments and project activity from selected teams.', recordTypes: 'Issues, comments, project activity' },
  confluence: { name: 'Confluence', description: 'Pages and comments from spaces you can read.', recordTypes: 'Pages and comments' },
  notion: { name: 'Notion', description: 'Pages shared with the connection. Search matches titles only.', recordTypes: 'Pages and comments' },
  google_drive: { name: 'Google Drive', description: 'Documents and file metadata from authorized folders.', recordTypes: 'Documents and file metadata' },
  salesforce: { name: 'Salesforce', description: 'Accounts, contacts and supported activity records.', recordTypes: 'Accounts, contacts, activity' },
}

/** Sources the backend can read today. Every other provider is shown as "coming soon". */
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

/** Backend source names are the same strings as these providers. */
export const PROVIDER_FOR_SOURCE: Record<string, SourceProvider | undefined> = Object.fromEntries(
  supportedProviders.map((p) => [p, p]),
)
