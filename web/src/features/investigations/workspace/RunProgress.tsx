import { Icon } from '@/components/ui'
import { ProviderName } from '@/components/shared/ProviderMark'
import type { LogEntry } from '@/features/investigations/useRunEvents'
import { useFormat } from '@/hooks/useSettings'
import type { Investigation } from '@/types/investigator'

const VISIBLE = 14

function Row({ entry, current }: { entry: LogEntry; current: boolean }) {
  const icon = entry.kind === 'error' ? 'alert' : current ? 'refresh' : 'circleCheck'
  const tone = entry.kind === 'error' ? 'text-danger' : current ? 'animate-spin text-info' : 'text-success'
  return (
    <li className="flex items-start gap-2 text-caption">
      <Icon name={icon} className={`mt-0.5 shrink-0 ${tone}`} />
      <span className="min-w-0 text-ink">
        {entry.kind === 'tool' ? (
          <span className="inline-flex flex-wrap items-center gap-x-2">
            <span>{entry.label}</span>
            {entry.provider ? <ProviderName provider={entry.provider} /> : null}
          </span>
        ) : (
          entry.label
        )}
        {entry.detail ? <span className="block text-ink-muted">{entry.detail}</span> : null}
      </span>
    </li>
  )
}

/** Live progress of a run: the steps the server has finished, newest last. */
export function RunProgress({ inv, entries, live }: { inv: Investigation; entries: LogEntry[]; live: boolean }) {
  const fmt = useFormat()
  const shown = entries.slice(-VISIBLE)
  const hidden = entries.length - shown.length
  return (
    <section aria-label="Investigation progress" className="border border-info bg-surface px-5 py-4">
      <div className="flex flex-wrap items-center gap-2">
        <Icon name="refresh" className="animate-spin text-info" />
        <h2 className="text-heading text-ink">{inv.status === 'queued' ? 'Queued' : 'Investigating'}</h2>
      </div>
      <p className="mt-1 text-caption text-ink-muted">
        Started {fmt.dateTime(inv.createdAt)}.{' '}
        {live ? 'Steps appear here as they finish.' : 'Live progress is unavailable; this page still updates every few seconds.'}
      </p>
      {shown.length > 0 ? (
        <ol className="mt-4 flex flex-col gap-2" aria-live="polite">
          {hidden > 0 ? <li className="text-caption text-ink-muted">{hidden} earlier steps not shown</li> : null}
          {shown.map((e, i) => (
            <Row key={`${e.id}-${i}`} entry={e} current={i === shown.length - 1 && e.kind !== 'error'} />
          ))}
        </ol>
      ) : (
        <p className="mt-3 text-caption text-ink-muted">Waiting for the first step…</p>
      )}
    </section>
  )
}
