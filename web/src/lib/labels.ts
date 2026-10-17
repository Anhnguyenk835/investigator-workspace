import type { RecordType, TimelineEventType } from '@/types/investigator'

export const recordTypeLabel: Record<RecordType, string> = {
  email: 'Email',
  chat_message: 'Chat message',
  issue: 'Issue',
  issue_change: 'Issue change',
  issue_comment: 'Issue comment',
  page: 'Page',
  page_comment: 'Page comment',
}

export const eventTypeLabel: Record<TimelineEventType, string> = {
  customer_request: 'Customer request',
  internal_discussion: 'Internal discussion',
  commitment: 'Promise or commitment',
  assignment: 'Assignment',
  status_change: 'Status change',
  document_update: 'Document update',
  blocker: 'Blocker',
  deadline_change: 'Deadline change',
  delivery: 'Delivery',
  escalation: 'Escalation',
  other: 'Other',
}

export const priorityLabel = { high: 'High', medium: 'Medium', low: 'Low' } as const

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.setAttribute('readonly', '')
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      return ok
    } catch {
      return false
    }
  }
}
