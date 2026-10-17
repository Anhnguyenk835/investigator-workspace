import { Badge, EmptyState } from '@/components/ui'
import { priorityLabel } from '@/lib/labels'
import { ReviewBar } from '@/features/investigations/workspace/Annotations'
import { EvidenceLine, ItemCard, Meta, Section, scrollToId } from '@/features/investigations/workspace/parts'
import type { Finding, RecommendedAction } from '@/types/investigator'

function ActionCard({ a, findings }: { a: RecommendedAction; findings: Finding[] }) {
  const related = a.relatedFindingIds.map((id) => findings.find((f) => f.id === id)).filter((f): f is Finding => Boolean(f))
  return (
    <ItemCard id={a.id}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="max-w-prose text-body font-medium text-ink">{a.title}</h3>
        <Badge tone={a.priority === 'high' ? 'dangerSoft' : a.priority === 'medium' ? 'warningSoft' : 'muted'}>{priorityLabel[a.priority]} priority</Badge>
      </div>
      <p className="mt-2 text-caption text-ink-muted">{a.rationale}</p>
      <dl className="mt-3 grid gap-3 sm:grid-cols-2">
        <Meta label="Suggested owner">{a.suggestedOwner ?? <span className="text-warning">Owner not confirmed</span>}</Meta>
        <Meta label="Related findings">
          {related.length === 0 ? (
            <span className="text-ink-muted">None</span>
          ) : (
            <span className="flex flex-wrap gap-1.5">
              {related.map((f) => (
                <button key={f.id} type="button" onClick={() => scrollToId(f.id)} className="border border-line-subtle px-1.5 py-0.5 text-left hover:border-primary/60">
                  {f.title}
                </button>
              ))}
            </span>
          )}
        </Meta>
      </dl>
      {a.evidenceIds.length > 0 ? (
        <div className="mt-3">
          <EvidenceLine label="Evidence" ids={a.evidenceIds} />
        </div>
      ) : null}
      <ReviewBar targetId={a.id} />
    </ItemCard>
  )
}

export function ActionsSection({ actions, findings }: { actions: RecommendedAction[]; findings: Finding[] }) {
  return (
    <Section
      id="actions"
      title="Recommended actions"
      description="Suggestions only. Nothing is created in a ticket system or sent to anyone."
      aside={<span className="text-caption text-ink-muted">{actions.length} suggested</span>}
    >
      {actions.length === 0 ? (
        <EmptyState icon="check" title="No recommended actions" body="Nothing could be recommended from the evidence found." />
      ) : (
        <div className="flex flex-col gap-3">
          {actions.map((a) => (
            <ActionCard key={a.id} a={a} findings={findings} />
          ))}
        </div>
      )}
    </Section>
  )
}
