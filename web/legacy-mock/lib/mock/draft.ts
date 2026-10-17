import { evidenceById } from '@/data/mockEvidence'
import type { MockState } from '@/types/investigator'

/**
 * Deterministic customer-update generator. It only reuses customer-safe wording
 * (`customerStatement`, `customerQuestion`, `customerStep`) attached to reviewed
 * analysis items, never raw internal notes, and it never states a new date.
 */
export function generateDraft(s: MockState, investigationId: string): string {
  const inv = s.investigations.find((i) => i.id === investigationId)
  if (!inv) throw new Error('Investigation not found.')

  const findings = s.findings.filter((f) => f.investigationId === investigationId)
  const gaps = s.gaps.filter((g) => g.investigationId === investigationId)
  const actions = s.actions.filter((a) => a.investigationId === investigationId)

  const contact = findings
    .flatMap((f) => f.supportingEvidenceIds)
    .map((id) => evidenceById.get(id))
    .find((e) => e?.authorSide === 'customer')?.author
  const greeting = contact ? `Hi ${contact.split(' ')[0]},` : 'Hello,'

  const confirmed = findings
    .filter((f) => f.status === 'verified' && f.customerStatement)
    .map((f) => `- ${f.customerStatement}`)
  const confirming = gaps
    .filter((g) => g.review === 'unresolved' && g.customerQuestion)
    .map((g) => `- ${g.customerQuestion}`)
  const steps = actions
    .filter((a) => (a.status === 'accepted' || a.status === 'in_progress') && a.customerStep)
    .map((a) => `- ${a.customerStep}`)

  const subject = `Update on ${inv.projectName ?? inv.title}`
  const lines: string[] = [
    `Subject: ${subject}`,
    '',
    greeting,
    '',
    `Thank you for your patience, and I am sorry for the frustration this has caused. I have reviewed the history of ${inv.projectName ? `your ${inv.projectName.toLowerCase()}` : 'this request'} so that I can give you an accurate update.`,
    '',
  ]

  lines.push('What we have confirmed')
  lines.push(...(confirmed.length > 0 ? confirmed : ['- We are still completing our review and will share confirmed details shortly.']))
  lines.push('')

  if (confirming.length > 0) {
    lines.push('What we are still confirming', ...confirming, '')
  }

  lines.push('Next steps')
  lines.push(
    ...(steps.length > 0
      ? steps
      : ['- We are agreeing the next steps internally and will follow up with you.']),
  )
  lines.push(
    '',
    'I will not give you a date until it has been confirmed with our team, so that you receive one you can rely on. I will update you as soon as we have it.',
    '',
    'Thank you again for your patience.',
    '',
    `Best regards,`,
    inv.owner,
  )
  return lines.join('\n')
}
