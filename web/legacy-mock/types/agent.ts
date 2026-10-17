import type { SourceProvider } from '@/types/investigator'

export type AgentIntent =
  | 'summary'
  | 'timeline'
  | 'commitments'
  | 'blocker'
  | 'conflicts'
  | 'next_steps'
  | 'draft'
  | 'unsupported'

export interface AgentBullet {
  text: string
  evidenceIds: string[]
  tone?: 'neutral' | 'warning'
  timelineEventId?: string
  findingId?: string
  commitmentId?: string
}

export interface AgentSection {
  heading: string
  kind: 'direct' | 'interpretation' | 'unknown' | 'conflict' | 'info'
  bullets: AgentBullet[]
}

export interface AgentToolActivity {
  id: string
  label: string
  /** The mock operation that produced this result. */
  operation: string
  provider?: SourceProvider
  summary: string
  count: number
  evidenceIds: string[]
}

export interface NewActionInput {
  id: string
  title: string
  rationale: string
  priority: 'low' | 'medium' | 'high'
  relatedFindingIds: string[]
  relatedEvidenceIds: string[]
  customerStep?: string
}

export type AgentAction =
  | { id: string; kind: 'open_evidence'; label: string; evidenceId: string }
  | { id: string; kind: 'show_timeline'; label: string; timelineEventId: string }
  | { id: string; kind: 'view_finding'; label: string; findingId: string }
  | { id: string; kind: 'add_action'; label: string; action: NewActionInput }
  | { id: string; kind: 'open_response'; label: string }
  | { id: string; kind: 'apply_note'; label: string; noteText: string }

export interface AgentMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: string
  evidenceIds: string[]
  intent?: AgentIntent
  tools?: AgentToolActivity[]
  sections?: AgentSection[]
  preview?: string
  actions?: AgentAction[]
  followUps?: string[]
  /** True when the agent could not verify the answer and wants the user to decide what to inspect. */
  needsInput?: boolean
}

export interface AgentConversation {
  id: string
  investigationId: string
  messages: AgentMessage[]
  updatedAt: string
}

export interface AgentResponse {
  message: AgentMessage
}

export interface SendMessageInput {
  investigationId: string
  message: string
  conversationId: string
}

export interface MockAgentService {
  sendMessage(
    input: SendMessageInput,
    onTool?: (tool: AgentToolActivity) => void,
  ): Promise<AgentResponse>
}
