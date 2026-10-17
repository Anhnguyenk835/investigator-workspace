/** The guides, as data: what to point at and what to say.
 *
 * `intro` is the first-run tour of the sidebar (Investigations, Connectors, Directory). Every page then has its own guide, shown the
 * first time that page is opened. */

export type PageId = 'investigations' | 'workspace' | 'settings'
export type TourId = 'intro' | PageId
export type Variant = 'demo' | 'user'

export type Placement = 'right' | 'bottom' | 'top' | 'left'

export interface TourStep {
  id: string
  /** CSS selector of what to point at. No target: a centred card. */
  target?: string
  title: string
  /** One text, or one per mode when the demo reads differently. */
  body: string | Record<Variant, string>
  placement?: Placement
  /** Skipped, in either direction, when its target does not appear (an empty list, no samples). */
  optional?: boolean
  /** The step points into the sidebar, which is a drawer on small screens. */
  nav?: boolean
}

export const TOURS: Record<TourId, TourStep[]> = {
  intro: [
    {
      id: 'investigations',
      target: '[data-tour="nav-investigations"]',
      placement: 'right',
      nav: true,
      title: 'Investigations',
      body: {
        demo: 'Every case lives here. Samples are finished investigations you can read; start your own any time.',
        user: 'Every case lives here. An investigation reconstructs what happened, who did what and what was promised.',
      },
    },
    {
      id: 'connectors',
      target: '[data-tour="nav-connectors"]',
      placement: 'right',
      nav: true,
      title: 'Connectors',
      body: {
        demo: 'Gmail, Slack, Jira and Confluence show here as connected. In this demo they read stored fictional data.',
        user: 'Connect Gmail, Slack, Jira, Confluence and Notion. Sources are read with your own permissions.',
      },
    },
    {
      id: 'directory',
      target: '[data-tour="nav-directory"]',
      placement: 'right',
      nav: true,
      title: 'Directory',
      body: {
        demo: 'Customers, projects and people, with where each one lives in your sources. The demo has its own, read-only.',
        user: 'Map each customer and project to its channels, Jira projects and labels, so investigations stay inside one customer.',
      },
    },
  ],

  investigations: [
    {
      id: 'new',
      target: '[data-tour="new-investigation"]',
      placement: 'bottom',
      title: 'Start a case',
      body: 'Describe what happened. Before anything is searched, you choose where to look.',
    },
    {
      id: 'filters',
      target: '[data-tour="list-filters"]',
      placement: 'bottom',
      optional: true,
      title: 'Find a case',
      body: 'Search by title, ticket or question, or filter by status and date.',
    },
    {
      id: 'open',
      target: '[data-tour="first-row"]',
      placement: 'bottom',
      optional: true,
      title: 'Open a case',
      body: {
        demo: 'This is a finished sample. Open it to see how a case reads, then ask the agent about it.',
        user: 'Open a case to read its summary, findings, timeline and evidence.',
      },
    },
  ],

  workspace: [
    {
      id: 'tabs',
      target: '[data-tour="workspace-tabs"]',
      placement: 'bottom',
      optional: true,
      title: 'Read it by section',
      body: 'Summary, findings, timeline, commitments, gaps, actions and sources. Every claim points at evidence.',
    },
    {
      id: 'findings',
      target: '#tab-findings',
      placement: 'bottom',
      optional: true,
      title: 'Check the evidence',
      body: 'Each finding lists the records that support it. Open a citation to see the original email, message or ticket.',
    },
    {
      id: 'agent',
      target: '[data-tour="agent"], #investigator-agent',
      placement: 'left',
      optional: true,
      title: 'Ask follow-up questions',
      body: 'The agent answers from this investigation and cites records. "Unknown" is a valid answer.',
    },
    {
      id: 'actions',
      target: '[data-tour="workspace-actions"]',
      placement: 'bottom',
      optional: true,
      title: 'Export or run again',
      body: {
        demo: 'Export the report. Samples cannot be run again; your own investigations can.',
        user: 'Export the report, or run the investigation again with the same question. Notes and reviews are kept.',
      },
    },
  ],

  settings: [
    {
      id: 'account',
      target: '[data-tour="settings-account"]',
      placement: 'bottom',
      optional: true,
      title: 'Your account',
      body: 'Your investigations, notes, chats, directory and connections are private to this account.',
    },
    {
      id: 'help',
      target: '[data-tour="help"]',
      placement: 'top',
      optional: true,
      title: 'Replay the guides',
      body: 'Take the introduction again, or show every page guide again.',
    },
  ],
}

/** The guide of the page at this path, if it has one. */
export function pageOf(pathname: string): PageId | undefined {
  if (pathname === '/investigations') return 'investigations'
  if (/^\/investigations\/[^/]+$/.test(pathname)) return 'workspace'
  if (pathname === '/settings') return 'settings'
  return undefined
}
