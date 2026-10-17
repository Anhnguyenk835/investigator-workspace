/** The scripts of the first-run tours. Pure data: what to point at, and what to say. */

export type TourId = 'demo' | 'user'

export type Placement = 'right' | 'bottom' | 'top' | 'left'

export interface TourStep {
  id: string
  /** CSS selector of what to point at. No target: a centred card. */
  target?: string
  /** Page the step is shown on. The tour navigates there when it is not already there. */
  route?: string
  title: string
  body: string
  placement?: Placement
  /** Skipped, in either direction, when its target does not appear (for example no samples yet). */
  optional?: boolean
  /** The step points into the sidebar, which is a drawer on small screens. */
  nav?: boolean
  /** Going on from this step clicks its target (to open what it points at). */
  clickOnNext?: boolean
}

const DEMO: TourStep[] = [
  {
    id: 'welcome',
    title: 'Welcome to the demo',
    body: 'This workspace holds fictional data. The AI answers are real. Anything you create here is deleted after 24 hours.',
  },
  {
    id: 'investigations',
    target: '[data-tour="nav-investigations"]',
    route: '/investigations',
    placement: 'right',
    nav: true,
    title: 'Every case lives here',
    body: 'An investigation reconstructs what happened, who did what and what was promised, from your sources.',
  },
  {
    id: 'sample',
    target: '[data-tour="sample-row"]',
    route: '/investigations',
    placement: 'bottom',
    optional: true,
    clickOnNext: true,
    title: 'Start with a sample',
    body: 'Samples are finished investigations you can read. Next opens one.',
  },
  {
    id: 'tabs',
    target: '[data-tour="workspace-tabs"]',
    placement: 'bottom',
    optional: true,
    title: 'Read it by section',
    body: 'Summary, findings, timeline, commitments, gaps and sources. Every claim points at evidence.',
  },
  {
    id: 'evidence',
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
    id: 'new',
    target: '[data-tour="new-investigation"]',
    route: '/investigations',
    placement: 'bottom',
    title: 'Run your own',
    body: 'Describe what happened. Before anything is searched, you are asked where to look.',
  },
]

const USER: TourStep[] = [
  {
    id: 'welcome',
    title: 'Welcome to The Investigator',
    body: 'Your investigations, notes, chats and connections are private to your account. This tour takes about a minute.',
  },
  {
    id: 'connectors',
    target: '[data-tour="nav-connectors"]',
    route: '/settings/connectors',
    placement: 'right',
    nav: true,
    title: 'Connect your sources',
    body: 'Connect Gmail, Slack, Jira, Confluence and Notion. Sources are read with your own permissions.',
  },
  {
    id: 'directory',
    target: '[data-tour="nav-directory"]',
    route: '/settings/directory',
    placement: 'right',
    nav: true,
    title: 'Map customers and projects',
    body: 'Link each project to its channels, Jira projects and labels. Investigations then stay inside one customer.',
  },
  {
    id: 'new',
    target: '[data-tour="new-investigation"]',
    route: '/investigations',
    placement: 'bottom',
    title: 'Start an investigation',
    body: 'Describe what happened. Add a customer or ticket if you know it.',
  },
  {
    id: 'scope',
    route: '/investigations/new',
    title: 'You choose where to look',
    body: 'Before searching, the investigator asks which channels, projects and labels to read. That keeps cost and exposure low.',
  },
  {
    id: 'help',
    target: '[data-tour="help"]',
    route: '/settings',
    placement: 'bottom',
    title: 'Replay this any time',
    body: 'Take the tour again from Settings or from the sidebar.',
  },
]

export const TOURS: Record<TourId, TourStep[]> = { demo: DEMO, user: USER }
