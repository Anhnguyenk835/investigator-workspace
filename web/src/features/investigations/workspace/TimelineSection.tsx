import { useMemo, useState } from 'react'
import { Badge, Button, EmptyState, Icon, Select, type IconName } from '@/components/ui'
import { StatusBadge, supportStatus } from '@/components/shared/StatusBadge'
import { ProviderName } from '@/components/shared/ProviderMark'
import { useEvidenceIndex } from '@/features/evidence/EvidenceIndex'
import { CitationList } from '@/features/evidence/EvidenceCitation'
import { useFormat } from '@/hooks/useSettings'
import { cn } from '@/lib/cn'
import { eventTypeLabel } from '@/lib/labels'
import { providerMeta } from '@/lib/providers'
import { Section, scrollToId } from '@/features/investigations/workspace/parts'
import type { Commitment, Finding, SourceProvider, TimelineEvent, TimelineEventType } from '@/types/investigator'

const ICONS: Record<TimelineEventType, IconName> = {
  customer_request: 'user',
  internal_discussion: 'note',
  commitment: 'check',
  assignment: 'user',
  status_change: 'edit',
  document_update: 'doc',
  blocker: 'ban',
  deadline_change: 'clock',
  delivery: 'circleCheck',
  escalation: 'alert',
  other: 'dot',
}

function TimelineItem({
  e,
  expanded,
  onToggle,
  findings,
  commitments,
}: {
  e: TimelineEvent
  expanded: boolean
  onToggle: () => void
  findings: Finding[]
  commitments: Commitment[]
}) {
  const fmt = useFormat()
  const index = useEvidenceIndex()
  const tone = e.eventType === 'blocker' ? 'border-danger text-danger' : e.eventType === 'deadline_change' ? 'border-warning text-warning' : 'border-line-subtle text-ink-muted'
  // Related means "cites at least one of the same records".
  const shares = (ids: string[]) => ids.some((id) => e.evidenceIds.includes(id))
  const related = findings.filter((f) => shares([...f.supportingEvidenceIds, ...f.contradictingEvidenceIds]))
  const relatedC = commitments.filter((c) => shares(c.evidenceIds))
  const regionId = `tl-${e.id}`
  return (
    <li id={e.id} tabIndex={-1} className="group relative flex scroll-mt-8 gap-4 pb-6 outline-offset-4 last:pb-0">
      <span aria-hidden="true" className="absolute bottom-0 left-4 top-9 w-px bg-line-subtle group-last:hidden" />
      <span className={cn('relative z-10 flex size-8 shrink-0 items-center justify-center border bg-surface', tone)}>
        <Icon name={ICONS[e.eventType]} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-caption text-ink-muted">
          <time dateTime={e.occurredAt} className="font-medium text-ink">
            {fmt.stamp(e.occurredAt, e.precision)}
          </time>
          <Badge tone={e.eventType === 'blocker' ? 'dangerSoft' : e.eventType === 'deadline_change' ? 'warningSoft' : 'muted'}>{eventTypeLabel[e.eventType]}</Badge>
          {e.provider ? <ProviderName provider={e.provider} /> : null}
          {e.actor ? <span>{e.actor}</span> : null}
          {e.supportStatus === 'partial' || e.supportStatus === 'unsupported' ? <StatusBadge def={supportStatus[e.supportStatus]} /> : null}
        </div>
        <h3 className="mt-1 text-body font-medium text-ink">{e.title}</h3>
        <p className="mt-0.5 text-caption text-ink-muted">{e.description}</p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <CitationList ids={e.evidenceIds} />
          <Button variant="ghost" size="sm" aria-expanded={expanded} aria-controls={regionId} onClick={onToggle}>
            <Icon name={expanded ? 'chevronUp' : 'chevronDown'} /> {expanded ? 'Hide details' : 'Details'}
          </Button>
        </div>
        {expanded ? (
          <div id={regionId} className="mt-2 flex flex-col gap-3 border-l-2 border-primary/50 bg-surface-muted px-4 py-3">
            {e.evidenceIds.map((id) => {
              const rec = index.get(id)
              const quote = e.support.find((c) => c.evidenceId === id)?.quote
              return rec ? (
                <div key={id}>
                  <p className="text-overline uppercase text-ink-muted">
                    {providerMeta[rec.provider].name} · {rec.title}
                  </p>
                  <p className="mt-1 whitespace-pre-wrap text-caption text-ink">{quote ?? rec.excerpt}</p>
                  {quote ? <p className="text-overline text-ink-muted">The passage this event rests on. Open the record for the rest.</p> : null}
                </div>
              ) : null
            })}
            {e.precision !== 'exact' ? (
              <p className="flex items-center gap-1.5 text-caption text-warning">
                <Icon name="alert" className="size-3.5" /> The source gives a date only; no time of day has been assumed.
              </p>
            ) : null}
            {related.length > 0 || relatedC.length > 0 ? (
              <div className="ml-auto flex flex-wrap items-center gap-2">
                <span className="text-caption text-ink-muted">Related:</span>
                {related.map((f) => (
                  <button key={f.id} type="button" onClick={() => scrollToId(f.id)} className="border border-line-subtle bg-surface px-2 py-0.5 text-caption text-ink hover:border-primary/60">
                    Finding: {f.title}
                  </button>
                ))}
                {relatedC.map((c) => (
                  <button key={c.id} type="button" onClick={() => scrollToId(c.id)} className="border border-line-subtle bg-surface px-2 py-0.5 text-caption text-ink hover:border-primary/60">
                    Commitment: {c.statement.length > 48 ? `${c.statement.slice(0, 45)}…` : c.statement}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </li>
  )
}

export function TimelineSection({
  events,
  findings,
  commitments,
}: {
  events: TimelineEvent[]
  findings: Finding[]
  commitments: Commitment[]
}) {
  const [order, setOrder] = useState<'asc' | 'desc'>('asc')
  const [provider, setProvider] = useState<'all' | SourceProvider>('all')
  const [type, setType] = useState<'all' | TimelineEventType>('all')
  const [open, setOpen] = useState<Set<string>>(new Set())

  const providers = useMemo(() => [...new Set(events.map((e) => e.provider).filter((p): p is SourceProvider => Boolean(p)))], [events])
  const types = useMemo(() => [...new Set(events.map((e) => e.eventType))], [events])

  const shown = useMemo(() => {
    const list = events.filter((e) => (provider === 'all' || e.provider === provider) && (type === 'all' || e.eventType === type))
    const mult = order === 'asc' ? 1 : -1
    // Events with no time go last in either order; the UI never invents one.
    return list.sort((a, b) => {
      if (!a.occurredAt || !b.occurredAt) return a.occurredAt ? -1 : b.occurredAt ? 1 : 0
      return a.occurredAt.localeCompare(b.occurredAt) * mult
    })
  }, [events, provider, type, order])

  const toggle = (id: string) =>
    setOpen((cur) => {
      const next = new Set(cur)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  const allOpen = shown.length > 0 && shown.every((e) => open.has(e.id))

  const controls = (
    <div className="ml-auto flex flex-wrap items-center gap-2">
            <div role="group" aria-label="Sort order" className="inline-flex border border-line">
                {(['asc', 'desc'] as const).map((o) => (
                  <button
                    key={o}
                    type="button"
                    aria-pressed={order === o}
                    onClick={() => setOrder(o)}
                    className={cn('px-2.5 py-1 text-caption', order === o ? 'bg-primary text-primary-fg' : 'bg-surface text-ink hover:bg-surface-muted')}
                  >
                    {o === 'asc' ? 'Oldest first' : 'Newest first'}
                  </button>
                ))}
              </div>
              <Select size="sm" className="w-32" aria-label="Filter timeline by source" value={provider} onChange={(e) => setProvider(e.target.value as typeof provider)}>
                <option value="all">All sources</option>
                {providers.map((p) => (
                  <option key={p} value={p}>
                    {providerMeta[p].name}
                  </option>
                ))}
              </Select>
              <Select size="sm" className="w-32" aria-label="Filter timeline by event type" value={type} onChange={(e) => setType(e.target.value as typeof type)}>
                <option value="all">All event types</option>
                {types.map((t) => (
                  <option key={t} value={t}>
                    {eventTypeLabel[t]}
                  </option>
                ))}
              </Select>
              <Button variant="outline" size="sm" onClick={() => setOpen(allOpen ? new Set() : new Set(shown.map((e) => e.id)))}>
                {allOpen ? 'Collapse all' : 'Expand all'}
              </Button>
      </div>
  )

  return (
    <Section
      id="timeline"
      title="Timeline"
      aside={events.length > 0 ? controls : <span className="text-caption text-ink-muted">0 events</span>}
    >
      {events.length === 0 ? (
        <EmptyState icon="clock" title="No timeline events" body="No dated records were found in the searched sources." />
      ) : (
        <>
          {shown.length === 0 ? (
            <EmptyState
              icon="filter"
              title="No events match these filters"
              body="The timeline is not empty; the current filters hide every event."
              actions={
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setProvider('all')
                    setType('all')
                  }}
                >
                  Clear filters
                </Button>
              }
            />
          ) : (
            <ol aria-label="Timeline events">
              {shown.map((e) => (
                <TimelineItem key={e.id} e={e} expanded={open.has(e.id)} onToggle={() => toggle(e.id)} findings={findings} commitments={commitments} />
              ))}
            </ol>
          )}
        </>
      )}
    </Section>
  )
}
