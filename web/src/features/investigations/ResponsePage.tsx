import { Navigate, useParams } from 'react-router-dom'
import { Badge, Button, EmptyState, Icon } from '@/components/ui'
import { StatusBadge, findingStatus } from '@/components/shared/StatusBadge'
import { useToast } from '@/components/ui/Toast'
import { CitationList } from '@/features/evidence/EvidenceCitation'
import { copyText } from '@/lib/labels'
import type { DraftStatus, InvestigationBundle } from '@/types/investigator'

const DRAFT_BADGE: Record<DraftStatus, { label: string; tone: 'muted' | 'infoSoft' | 'successSoft' | 'warningSoft' }> = {
  none: { label: 'No draft', tone: 'muted' },
  drafted: { label: 'Awaiting approval', tone: 'warningSoft' },
  approved: { label: 'Approved', tone: 'successSoft' },
  changes_requested: { label: 'Changes requested', tone: 'warningSoft' },
  not_possible: { label: 'Not possible', tone: 'muted' },
}

function ContextBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border border-line bg-surface">
      <h2 className="border-b border-line-subtle px-4 py-2.5 text-overline uppercase text-ink-muted">{title}</h2>
      <div className="px-4 py-3">{children}</div>
    </section>
  )
}

/** The customer update, read-only. Editing and approving happen in the review panel above. */
export function ResponsePanel({ b }: { b: InvestigationBundle }) {
  const toast = useToast()
  const { draft } = b
  const verified = b.findings.filter((f) => f.status === 'verified')
  const badge = DRAFT_BADGE[draft.status]

  if (draft.status === 'none') {
    return (
      <EmptyState
        icon="doc"
        title="No customer draft yet"
        body={
          b.investigation.awaiting === 'review'
            ? 'A draft is written after you approve the findings in the review panel above.'
            : 'A draft is written once the findings are approved. It uses verified findings only.'
        }
      />
    )
  }
  if (draft.status === 'not_possible') {
    return (
      <EmptyState
        icon="alert"
        title="No customer draft was written"
        body="A draft needs at least one verified finding, and none was verified. Gather more evidence first; the draft never states what the evidence does not support."
      />
    )
  }

  if (b.investigation.awaiting === 'draft_approval') {
    return (
      <EmptyState
        icon="doc"
        title="The draft is waiting for you"
        body="Read, edit and approve the customer update in the panel at the top of this page. It appears here once you decide."
      />
    )
  }

  const copy = async () => {
    if (await copyText(draft.body)) toast.success('Draft copied to clipboard')
    else toast.error('Could not copy', 'Clipboard access was blocked by the browser.')
  }

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="flex min-w-0 flex-col gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <Badge tone={badge.tone}>{badge.label}</Badge>
          <p className="text-caption text-ink-muted">Nothing is sent from this product. A person copies the approved text into their own channel.</p>
        </div>
        {draft.warnings.length > 0 ? (
          <div role="status" className="border border-warning/50 bg-warning/10 p-4">
            <p className="flex items-center gap-2 text-body font-medium text-ink">
              <Icon name="alert" /> The checks flagged this draft
            </p>
            <ul className="mt-2 flex list-disc flex-col gap-1 pl-5 text-caption text-ink">
              {draft.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <pre className="whitespace-pre-wrap border border-line bg-surface px-4 py-3 font-sans text-body text-ink">{draft.body}</pre>
        <div>
          <Button variant="outline" size="sm" onClick={copy}>
            <Icon name="copy" /> Copy draft
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-4">
        <ContextBlock title="Facts the draft may use">
          {verified.length === 0 ? (
            <p className="text-caption text-ink-muted">No finding is verified.</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {verified.map((f) => (
                <li key={f.id} className="flex flex-col gap-1 text-caption text-ink">
                  {f.claim}
                  <span className="flex flex-wrap items-center gap-2">
                    <StatusBadge def={findingStatus[f.status]} />
                    <CitationList ids={f.supportingEvidenceIds} />
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-caption text-ink-muted">Only verified findings are used. Internal notes are never included.</p>
        </ContextBlock>
      </div>
    </div>
  )
}

/** Old standalone URL: opens the workspace on its Response tab. */
export function ResponseRedirect() {
  const { id = '' } = useParams()
  return <Navigate to={`/investigations/${id}?tab=response`} replace />
}
