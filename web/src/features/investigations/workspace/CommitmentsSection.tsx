import { Badge, EmptyState } from '@/components/ui'
import { StatusBadge, commitmentStatus, supportStatus } from '@/components/shared/StatusBadge'
import { useFormat } from '@/hooks/useSettings'
import { ReviewBar } from '@/features/investigations/workspace/Annotations'
import { EvidenceLine, ItemCard, Meta, Section, SupportQuotes } from '@/features/investigations/workspace/parts'
import type { Commitment } from '@/types/investigator'

export function CommitmentsSection({ commitments }: { commitments: Commitment[] }) {
  const fmt = useFormat()
  const unknown = <span className="text-ink-muted">Not stated</span>
  return (
    <Section
      id="commitments"
      title="Commitments & deadlines"
      description="Status is computed from the stated due date, today's date and the evidence on file."
      aside={<span className="text-caption text-ink-muted">{commitments.length} {commitments.length === 1 ? 'commitment' : 'commitments'}</span>}
    >
      {commitments.length === 0 ? (
        <EmptyState icon="clock" title="No commitments found" body="No promise or deadline was identified in the searched sources." />
      ) : (
        <div className="flex flex-col gap-3">
          {commitments.map((c) => (
            <ItemCard key={c.id} id={c.id}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <h3 className="max-w-prose text-body font-medium text-ink">{c.statement}</h3>
                <div className="flex flex-wrap items-center gap-2">
                  {c.basis === 'inferred' ? <Badge tone="warningSoft">Inferred</Badge> : null}
                  {c.supportStatus === 'partial' || c.supportStatus === 'unsupported' ? <StatusBadge def={supportStatus[c.supportStatus]} /> : null}
                  <StatusBadge def={commitmentStatus[c.status]} />
                </div>
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
                <Meta label="Committed by">{c.committedBy ?? unknown}</Meta>
                <Meta label="Responsible">{c.owner ?? <span className="text-warning">Owner not confirmed</span>}</Meta>
                <Meta label="Promised">{c.promisedAt ? fmt.date(c.promisedAt) : unknown}</Meta>
                <Meta label="Due">{c.dueDate ? fmt.date(`${c.dueDate}T00:00:00Z`) : unknown}</Meta>
              </dl>
              {c.support.length > 0 ? (
                <div className="mt-3">
                  <SupportQuotes support={c.support} />
                </div>
              ) : null}
              <div className="mt-3 flex flex-col gap-1.5">
                <EvidenceLine label="Evidence" ids={c.evidenceIds} />
                {c.fulfilledByEvidenceIds.length > 0 ? <EvidenceLine label="Fulfilled by" ids={c.fulfilledByEvidenceIds} /> : null}
              </div>
              <ReviewBar targetId={c.id} />
            </ItemCard>
          ))}
        </div>
      )}
    </Section>
  )
}
