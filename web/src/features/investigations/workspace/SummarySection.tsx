import type { ReactNode } from 'react'
import { SimpleMarkdown } from '@/components/shared/SimpleMarkdown'
import { Badge, Icon } from '@/components/ui'
import { CitationList } from '@/features/evidence/EvidenceCitation'
import { Section } from '@/features/investigations/workspace/parts'
import { coverageRatio } from '@/lib/coverage'
import type { InvestigationBundle } from '@/types/investigator'

/** The three counts and the review badge, side by side in the section header. */
function SummaryAside({ metrics, indicator }: { metrics: { label: string; value: string }[]; indicator: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-end gap-x-5 gap-y-1">
      <dl className="flex flex-wrap items-baseline gap-x-5 gap-y-1">
        {metrics.map((m) => (
          <div key={m.label} className="flex items-baseline gap-1.5">
            <dt className="text-overline uppercase text-ink-muted">{m.label}</dt>
            <dd className="text-caption font-medium text-ink">{m.value}</dd>
          </div>
        ))}
      </dl>
      {indicator}
    </div>
  )
}

const BLOCKER_KIND = { blocker: 'Blocker', dependency: 'Dependency', probable_cause: 'Probable cause' } as const

export function SummarySection({ b }: { b: InvestigationBundle }) {
  const inv = b.investigation
  const verified = b.findings.filter((f) => f.status === 'verified').length
  const { searched, total } = coverageRatio(inv.coverage)
  const resolved = inv.status === 'resolved'

  const indicator = resolved ? (
    <Badge tone="successSoft">
      <Icon name="circleCheck" className="size-3" /> Resolved{inv.resolvedBy ? ` by ${inv.resolvedBy}` : ''}
    </Badge>
  ) : (
    <Badge tone="warningSoft">
      <Icon name="alert" className="size-3" /> AI-generated — review required
    </Badge>
  )

  const metrics = [
    { label: 'Findings', value: b.findings.length === 0 ? 'None' : `${verified} verified of ${b.findings.length}` },
    { label: 'Evidence records', value: String(b.evidence.length) },
    { label: 'Sources searched', value: total === 0 ? 'None yet' : `${searched} of ${total}` },
  ]

  return (
    <Section id="summary" title="Investigation summary" aside={<SummaryAside metrics={metrics} indicator={indicator} />}>
      <div className="flex flex-col gap-5">
        <div className="flex flex-col gap-3">
        {inv.summary ? (
          <p className="whitespace-pre-wrap text-body text-ink">{inv.summary}</p>
        ) : (
          <p className="text-body text-ink-muted">No summary was produced. Check the findings and sources for what was found.</p>
        )}
        {inv.searchNotes ? (
          <details className="group">
            <summary className="flex cursor-pointer list-none items-center gap-1.5 text-caption font-medium text-ink marker:hidden">
              <Icon name="chevronRight" className="size-3.5 text-ink-muted transition-transform group-open:rotate-90" />
              How this was searched
              <span className="font-normal text-ink-muted">· the search agent's own notes, not checked against the evidence</span>
            </summary>
            <div className="mt-3 border-l-2 border-line-subtle pl-4">
              <SimpleMarkdown source={inv.searchNotes} />
            </div>
          </details>
        ) : null}
        </div>

        {b.blockers.length > 0 ? (
          <div className="border-t border-line-subtle pt-4">
            <h3 className="mb-2 text-body font-medium text-ink">Blockers and dependencies</h3>
            <ul className="flex flex-col gap-2">
              {b.blockers.map((x) => (
                <li key={x.id} id={x.id} className="flex flex-wrap items-center gap-2 text-body text-ink">
                  <Badge tone="muted">{BLOCKER_KIND[x.kind]}</Badge>
                  <span>{x.description}</span>
                  {x.basis === 'inferred' ? <Badge tone="warningSoft">Inferred</Badge> : null}
                  <CitationList ids={x.evidenceIds} />
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {!inv.validationPassed && inv.validationIssues.length > 0 ? (
          <div className="border-t border-line-subtle pt-4">
            <h3 className="mb-2 text-body font-medium text-ink">Checks still flagged</h3>
            <ul className="flex list-disc flex-col gap-1 pl-5 text-caption text-ink">
              {inv.validationIssues.map((i, n) => (
                <li key={`${i.code}-${n}`}>
                  <span className="text-ink-muted">{i.severity === 'error' ? 'Error' : 'Warning'}: </span>
                  {i.detail}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {inv.reviewerNotes.length > 0 ? (
          <div className="border-t border-line-subtle pt-4">
            <h3 className="mb-2 text-body font-medium text-ink">Reviewer notes</h3>
            <ul className="flex list-disc flex-col gap-1 pl-5 text-caption text-ink">
              {inv.reviewerNotes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </Section>
  )
}
