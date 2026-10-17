import { useState } from 'react'
import { providerMeta } from '@/data/mockConnectors'
import { Button, Checkbox, Drawer, EmptyState, Icon, Progress, Select, Table, TableWrap, Td, Th } from '@/components/ui'
import { StatusBadge, syncStatus } from '@/components/shared/StatusBadge'
import { useFormat } from '@/hooks/useSettings'
import { useRunAction } from '@/hooks/useRunAction'
import { formatCount, formatDuration } from '@/lib/format'
import { mockApi } from '@/lib/mockApi'
import { SYNC_STAGES } from '@/lib/mock/store'
import type { Connector, ConnectorScope, DateRange, SyncJob } from '@/types/investigator'

export const DATE_RANGE_LABEL: Record<DateRange, string> = {
  '30d': 'Last 30 days',
  '90d': 'Last 90 days',
  '1y': 'Last 12 months',
  all: 'All available history',
}

export function scopeSummary(c: Connector): string {
  const meta = providerMeta[c.provider]
  const names = c.scope.resources.map((id) => meta.resources.find((r) => r.id === id)?.label ?? id)
  return names.length > 0 ? names.join(', ') : 'Nothing selected'
}

export function ScopeForm({ provider, scope, onChange }: { provider: Connector['provider']; scope: ConnectorScope; onChange: (s: ConnectorScope) => void }) {
  const meta = providerMeta[provider]
  const toggle = (key: 'resources' | 'contentTypes', id: string) =>
    onChange({ ...scope, [key]: scope[key].includes(id) ? scope[key].filter((x) => x !== id) : [...scope[key], id] })
  return (
    <div className="flex flex-col gap-6">
      <fieldset className="flex flex-col gap-3">
        <legend className="mb-1 text-overline uppercase text-ink-muted">{meta.resourceLabel}</legend>
        {meta.resources.map((r) => (
          <Checkbox key={r.id} label={r.label} checked={scope.resources.includes(r.id)} onChange={() => toggle('resources', r.id)} />
        ))}
        <p className="text-caption text-ink-muted">Start with the minimum. Only selected items are indexed.</p>
      </fieldset>
      <fieldset className="flex flex-col gap-3">
        <legend className="mb-1 text-overline uppercase text-ink-muted">Content types</legend>
        {meta.contentTypes.map((t) => (
          <Checkbox key={t.id} label={t.label} checked={scope.contentTypes.includes(t.id)} onChange={() => toggle('contentTypes', t.id)} />
        ))}
      </fieldset>
      <div className="flex flex-col gap-1.5">
        <label htmlFor="scope-range" className="text-overline uppercase text-ink-muted">
          Date range
        </label>
        <Select id="scope-range" value={scope.dateRange} onChange={(e) => onChange({ ...scope, dateRange: e.target.value as DateRange })}>
          {(Object.keys(DATE_RANGE_LABEL) as DateRange[]).map((r) => (
            <option key={r} value={r}>
              {DATE_RANGE_LABEL[r]}
            </option>
          ))}
        </Select>
      </div>
      <Checkbox label="Include archived content" description="Where the provider supports it." checked={scope.includeArchived} onChange={(e) => onChange({ ...scope, includeArchived: e.target.checked })} />
    </div>
  )
}

export function SyncProgress({ job }: { job: SyncJob }) {
  const running = job.status === 'running' || job.status === 'queued'
  const stage = running ? job.stage : SYNC_STAGES.length - 1
  return (
    <div className="border border-info bg-surface p-4" role="status" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-body font-medium text-ink">{running ? SYNC_STAGES[Math.min(stage, SYNC_STAGES.length - 1)] + '…' : 'Finished'}</p>
        <span className="border border-info/50 bg-info/10 px-2 py-0.5 text-overline uppercase text-info">Simulated sync</span>
      </div>
      <Progress className="mt-3" value={stage} max={SYNC_STAGES.length - 1} label="Sync progress" />
      <ol className="mt-3 grid gap-1.5 sm:grid-cols-2">
        {SYNC_STAGES.map((label, i) => (
          <li key={label} className="flex items-center gap-2 text-caption">
            <Icon name={i < stage || !running ? 'circleCheck' : i === stage ? 'refresh' : 'dot'} className={i < stage || !running ? 'text-success' : i === stage ? 'animate-spin text-info' : 'text-line-subtle'} />
            <span className={i <= stage ? 'text-ink' : 'text-ink-muted'}>{label}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}

export function SyncSummary({ job }: { job: SyncJob }) {
  const fmt = useFormat()
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <StatusBadge def={syncStatus[job.status]} />
        <span className="text-caption text-ink-muted">Completed {fmt.dateTime(job.completedAt)} (simulated counts)</span>
      </div>
      <dl className="grid grid-cols-3 gap-3 border border-line-subtle p-4">
        {[
          ['Discovered', job.recordsFetched],
          ['Indexed', job.recordsIndexed],
          ['Skipped', job.recordsSkipped],
        ].map(([label, n]) => (
          <div key={label}>
            <dt className="text-overline uppercase text-ink-muted">{label}</dt>
            <dd className="text-title text-ink">{formatCount(Number(n))}</dd>
          </div>
        ))}
      </dl>
      {job.status === 'partial' || job.status === 'failed' ? (
        <p role="alert" className="flex items-start gap-2 border border-warning bg-warning/10 px-3 py-2 text-caption text-ink">
          <Icon name="alert" className="mt-0.5 text-warning" />
          {job.status === 'partial' ? 'This sync was partial. ' : ''}
          {job.errorMessage}
        </p>
      ) : null}
    </div>
  )
}

export function SyncHistoryTable({ jobs, showConnector = false }: { jobs: SyncJob[]; showConnector?: boolean }) {
  const fmt = useFormat()
  const [selected, setSelected] = useState<SyncJob | null>(null)
  const { run, busy } = useRunAction()
  const current = selected ? (jobs.find((j) => j.id === selected.id) ?? selected) : null

  if (jobs.length === 0) {
    return <EmptyState icon="refresh" title="No syncs yet" body="Run a sync to index records from this source. Each run is listed here." />
  }
  return (
    <>
      <TableWrap>
        <Table>
          <caption className="sr-only">Sync jobs</caption>
          <thead>
            <tr>
              <Th>Sync ID</Th>
              {showConnector ? <Th>Connector</Th> : null}
              <Th>Started</Th>
              <Th className="hidden sm:table-cell">Duration</Th>
              <Th className="hidden md:table-cell">Fetched</Th>
              <Th className="hidden md:table-cell">Indexed</Th>
              <Th className="hidden md:table-cell">Skipped</Th>
              <Th>Status</Th>
              <Th>
                <span className="sr-only">Details</span>
              </Th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id}>
                <Td className="font-mono">{j.id}</Td>
                {showConnector ? <Td>{providerMeta[j.connectorId].name}</Td> : null}
                <Td className="whitespace-nowrap">{fmt.dateTime(j.startedAt)}</Td>
                <Td className="hidden sm:table-cell">{formatDuration(j.startedAt, j.completedAt)}</Td>
                <Td className="hidden md:table-cell">{formatCount(j.recordsFetched)}</Td>
                <Td className="hidden md:table-cell">{formatCount(j.recordsIndexed)}</Td>
                <Td className="hidden md:table-cell">{formatCount(j.recordsSkipped)}</Td>
                <Td>
                  <StatusBadge def={syncStatus[j.status]} />
                </Td>
                <Td>
                  <Button size="sm" variant="ghost" onClick={() => setSelected(j)} aria-label={`View details for ${j.id}`}>
                    View details
                  </Button>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </TableWrap>
      <Drawer
        open={current !== null}
        onClose={() => setSelected(null)}
        title={current ? `Sync ${current.id}` : 'Sync'}
        description={current ? providerMeta[current.connectorId].name : undefined}
        footer={
          <>
            {current && (current.status === 'failed' || current.status === 'partial') ? (
              <Button
                disabled={busy}
                onClick={async () => {
                  const ok = await run(() => mockApi.retrySync(current.id), 'Retry started. A new sync job was created.')
                  if (ok) setSelected(null)
                }}
              >
                <Icon name="refresh" /> Retry sync
              </Button>
            ) : null}
            <Button variant="outline" onClick={() => setSelected(null)}>
              Close
            </Button>
          </>
        }
      >
        {current ? (
          <div className="flex flex-col gap-4">
            {current.status === 'running' || current.status === 'queued' ? <SyncProgress job={current} /> : <SyncSummary job={current} />}
            <dl className="text-caption">
              {[
                ['Trigger', current.trigger],
                ['Started', fmt.dateTime(current.startedAt)],
                ['Duration', formatDuration(current.startedAt, current.completedAt)],
                ['Error code', current.errorCode ?? 'None'],
              ].map(([k, v]) => (
                <div key={k} className="grid grid-cols-[7rem_1fr] gap-3 border-b border-line-subtle py-2">
                  <dt className="text-ink-muted">{k}</dt>
                  <dd className="text-ink">{v}</dd>
                </div>
              ))}
            </dl>
            {current.status === 'failed' && current.errorMessage ? <p className="text-body text-ink">{current.errorMessage}</p> : null}
            {current.status === 'failed' || current.status === 'partial' ? (
              <p className="text-caption text-ink-muted">Retrying creates a new job and does not duplicate already indexed records.</p>
            ) : null}
          </div>
        ) : null}
      </Drawer>
    </>
  )
}
