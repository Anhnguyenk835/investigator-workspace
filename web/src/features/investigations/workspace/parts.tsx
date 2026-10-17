import { revealAndFlash } from '@/features/agent/highlight'
import { type ReactNode } from 'react'
import { CitationList, EvidenceCitation } from '@/features/evidence/EvidenceCitation'
import { cn } from '@/lib/cn'
import type { SupportCheck } from '@/types/investigator'

export function scrollToId(id: string) {
  void revealAndFlash(id)
}

export function Section({
  id,
  title,
  aside,
  description,
  children,
}: {
  id: string
  title: string
  aside?: ReactNode
  description?: ReactNode
  children: ReactNode
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-8 border border-line bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line-subtle px-5 py-3">
        <div>
          <h2 id={`${id}-title`} className="text-heading text-ink">
            {title}
          </h2>
          {description ? <p className="mt-0.5 text-caption text-ink-muted">{description}</p> : null}
        </div>
        {aside}
      </div>
      <div className="px-5 py-4">{children}</div>
    </section>
  )
}

/** Item card that can be a scroll target (related-item chips link here). */
export function ItemCard({ id, children, className }: { id: string; children: ReactNode; className?: string }) {
  return (
    <article id={id} tabIndex={-1} className={cn('scroll-mt-8 border border-line-subtle bg-surface p-4 outline-offset-2', className)}>
      {children}
    </article>
  )
}

export function Meta({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-overline uppercase text-ink-muted">{label}</dt>
      <dd className="mt-0.5 text-caption text-ink">{children}</dd>
    </div>
  )
}

export function EvidenceLine({ label, ids }: { label: string; ids: string[] }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-caption text-ink-muted">{label}</span>
      <CitationList ids={ids} />
    </div>
  )
}

const VERDICT_LABEL = { supported: 'Says it', partial: 'Says part of it', unsupported: 'Does not say it' } as const

/** What each cited record actually says about a claim: the passage it was judged on. */
export function SupportQuotes({ support }: { support: SupportCheck[] }) {
  if (support.length === 0) return null
  return (
    <ul className="flex flex-col gap-2" aria-label="What the cited records say">
      {support.map((c) => (
        <li key={c.evidenceId} className="flex items-start gap-2 text-caption">
          <EvidenceCitation id={c.evidenceId} />
          <div className="min-w-0">
            <span className={cn('text-overline uppercase', c.verdict === 'supported' ? 'text-success' : c.verdict === 'partial' ? 'text-warning' : 'text-danger')}>{VERDICT_LABEL[c.verdict]}</span>
            {c.quote ? <blockquote className="mt-0.5 border-l-2 border-primary/50 pl-2 text-ink">{c.quote}</blockquote> : null}
          </div>
        </li>
      ))}
    </ul>
  )
}
