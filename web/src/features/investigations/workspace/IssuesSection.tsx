import { Badge, EmptyState } from '@/components/ui'
import { CitationList } from '@/features/evidence/EvidenceCitation'
import { ReviewBar } from '@/features/investigations/workspace/Annotations'
import { ItemCard, Meta, Section } from '@/features/investigations/workspace/parts'
import type { Contradiction, Gap } from '@/types/investigator'

const ORIGIN = {
  coverage: 'A source was not fully searched',
  analysis: 'Found in the analysis',
  quality: 'Found by the quality checks',
} as const

function GapCard({ g }: { g: Gap }) {
  return (
    <ItemCard id={g.id}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h4 className="max-w-prose text-body font-medium text-ink">{g.missing}</h4>
        <Badge tone="muted">{ORIGIN[g.origin]}</Badge>
      </div>
      <dl className="mt-3 grid gap-3 md:grid-cols-3">
        <Meta label="Why it matters">{g.whyItMatters}</Meta>
        <Meta label="Evidence that could resolve it">{g.resolvingEvidence}</Meta>
        <Meta label="Suggested follow-up">{g.followUp}</Meta>
      </dl>
      <ReviewBar targetId={g.id} />
    </ItemCard>
  )
}

function ContradictionCard({ c }: { c: Contradiction }) {
  const sides = [
    { label: 'Claim A', claim: c.claimA },
    { label: 'Claim B', claim: c.claimB },
  ]
  return (
    <ItemCard id={c.id}>
      <div className="grid gap-3 md:grid-cols-2">
        {sides.map(({ label, claim }) => (
          <div key={label} className="border border-line-subtle bg-surface-muted p-3">
            <p className="text-overline uppercase text-ink-muted">{label}</p>
            <p className="mt-1 text-body text-ink">{claim.text}</p>
            <div className="mt-2">
              <CitationList ids={claim.evidenceIds} />
            </div>
          </div>
        ))}
      </div>
      <p className="mt-3 text-caption text-ink-muted">{c.explanation}</p>
      <p className="mt-1 text-caption text-ink-muted">Neither claim has been chosen as correct. A reviewer decides.</p>
      <ReviewBar targetId={c.id} />
    </ItemCard>
  )
}

export function IssuesSection({ gaps, contradictions }: { gaps: Gap[]; contradictions: Contradiction[] }) {
  return (
    <Section id="issues" title="Gaps & contradictions" description="Missing evidence and conflicting evidence are tracked separately.">
      <div className="flex flex-col gap-8">
        <div>
          <h3 className="mb-3 text-body font-medium text-ink">
            Gaps <span className="font-normal text-ink-muted">· missing evidence ({gaps.length})</span>
          </h3>
          {gaps.length === 0 ? (
            <EmptyState icon="circleCheck" title="No gaps identified" body="No missing information was identified. Sources that were not searched can still hold relevant records." />
          ) : (
            <div className="flex flex-col gap-3">
              {gaps.map((g) => (
                <GapCard key={g.id} g={g} />
              ))}
            </div>
          )}
        </div>
        <div>
          <h3 className="mb-3 text-body font-medium text-ink">
            Contradictions <span className="font-normal text-ink-muted">· conflicting evidence ({contradictions.length})</span>
          </h3>
          {contradictions.length === 0 ? (
            <EmptyState icon="circleCheck" title="No contradictions identified" body="No competing claims were found in the searched sources." />
          ) : (
            <div className="flex flex-col gap-3">
              {contradictions.map((c) => (
                <ContradictionCard key={c.id} c={c} />
              ))}
            </div>
          )}
        </div>
      </div>
    </Section>
  )
}
