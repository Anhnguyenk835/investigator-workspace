import { Badge, EmptyState } from '@/components/ui'
import { StatusBadge, findingStatus, supportStatus } from '@/components/shared/StatusBadge'
import { ReviewBar } from '@/features/investigations/workspace/Annotations'
import { EvidenceLine, ItemCard, Section, SupportQuotes } from '@/features/investigations/workspace/parts'
import type { Finding } from '@/types/investigator'

function FindingCard({ f }: { f: Finding }) {
  return (
    <ItemCard id={f.id}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="text-body font-medium text-ink">{f.title}</h3>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="muted">{f.basis === 'inference' ? 'Inference' : 'Direct evidence'}</Badge>
          {f.supportStatus !== 'unchecked' ? <StatusBadge def={supportStatus[f.supportStatus]} /> : null}
          <StatusBadge def={findingStatus[f.status]} />
        </div>
      </div>
      <p className="mt-2 text-body text-ink">{f.claim}</p>
      {f.explanation ? <p className="mt-1 text-caption text-ink-muted">{f.explanation}</p> : null}
      {f.support.length > 0 ? (
        <div className="mt-3">
          <SupportQuotes support={f.support} />
        </div>
      ) : null}
      <div className="mt-3 flex flex-col gap-1.5">
        <p className="text-caption text-ink-muted">
          Evidence: {f.supportingEvidenceIds.length} supporting
          {f.contradictingEvidenceIds.length > 0 ? `, ${f.contradictingEvidenceIds.length} contradicting` : ''}
        </p>
        <EvidenceLine label="Supporting" ids={f.supportingEvidenceIds} />
        {f.contradictingEvidenceIds.length > 0 ? <EvidenceLine label="Contradicting" ids={f.contradictingEvidenceIds} /> : null}
      </div>
      {f.reviewFlag ? (
        <p role="note" className="mt-3 border-l-2 border-warning bg-surface-muted px-3 py-2 text-caption text-ink">
          <span className="block text-overline uppercase text-warning">Check before relying on this</span>
          {f.reviewFlag}
        </p>
      ) : null}
      <ReviewBar targetId={f.id} />
      {f.reviewerNote ? (
        <p className="mt-3 border-l-2 border-primary/50 bg-surface-muted px-3 py-2 text-caption text-ink">
          <span className="block text-overline uppercase text-ink-muted">Reviewer note</span>
          {f.reviewerNote}
        </p>
      ) : null}
    </ItemCard>
  )
}

export function FindingsSection({ findings }: { findings: Finding[] }) {
  return (
    <Section id="findings" title="Key findings" aside={<span className="text-caption text-ink-muted">{findings.length} {findings.length === 1 ? 'finding' : 'findings'}</span>}>
      {findings.length === 0 ? (
        <EmptyState icon="search" title="No findings" body="No finding is supported by the searched sources. This does not mean nothing happened; some sources may not have been searched." />
      ) : (
        <div className="flex flex-col gap-3">
          {findings.map((f) => (
            <FindingCard key={f.id} f={f} />
          ))}
        </div>
      )}
    </Section>
  )
}
