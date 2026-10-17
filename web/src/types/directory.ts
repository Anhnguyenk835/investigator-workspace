/** Who the customers, projects and people are, and where each lives in the sources. */

export type Side = 'customer' | 'internal' | 'third_party'

export interface Customer {
  id: string
  name: string
  aliases: string[]
  emailDomains: string[]
}

export interface Project {
  id: string
  customerId?: string
  name: string
  aliases: string[]
  ticketPrefixes: string[]
  jiraProjects: string[]
  jiraLabels: string[]
  slackChannelIds: string[]
  gmailLabels: string[]
  confluenceSpaces: string[]
}

export interface Person {
  id: string
  name: string
  aliases: string[]
  emails: string[]
  slackIds: string[]
  jiraAccountIds: string[]
  side: Side
  role?: string
  customerId?: string
}

export interface DirectoryData {
  customers: Customer[]
  projects: Project[]
  people: Person[]
}

export type Suggestion = { id: string; label: string }
