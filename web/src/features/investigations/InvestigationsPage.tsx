import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import { toInvestigation } from '@/api/adapt'
import { Button, EmptyState, ErrorState, Icon, Select, SkeletonRows, SortTh, Table, TableWrap, Td } from '@/components/ui'
import { PageHeader } from '@/components/shared/PageHeader'
import { SearchInput } from '@/components/shared/SearchInput'
import { Badge } from '@/components/ui'
import { StatusBadge, investigationStatus } from '@/components/shared/StatusBadge'
import { CoverageMeter } from '@/features/investigations/CoverageMeter'
import { awaitingLabel } from '@/features/investigations/awaiting'
import { useApiQuery } from '@/hooks/useApiQuery'
import { useFormat } from '@/hooks/useSettings'
import { useSort } from '@/hooks/useSort'
import { coverageRatio } from '@/lib/coverage'
import type { Investigation, InvestigationStatus } from '@/types/investigator'

const STATUS_ORDER: InvestigationStatus[] = ['queued', 'investigating', 'needs_review', 'blocked', 'resolved', 'failed']
const DATE_FILTERS = [
  { id: 'all', label: 'Any time', days: 0 },
  { id: '7', label: 'Updated in last 7 days', days: 7 },
  { id: '30', label: 'Updated in last 30 days', days: 30 },
] as const

const RUNNING = new Set<InvestigationStatus>(['queued', 'investigating'])

export function InvestigationsPage() {
  const query = useApiQuery(async () => (await api.listInvestigations()).map(toInvestigation), [], {
    // Keep the list fresh while a run is going; stop when everything is at rest.
    pollMs: (rows) => (rows.some((i) => RUNNING.has(i.status)) ? 3000 : false),
  })
  const navigate = useNavigate()
  const fmt = useFormat()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('all')
  const [date, setDate] = useState<(typeof DATE_FILTERS)[number]['id']>('all')
  const [now] = useState(() => Date.now())

  const all = useMemo(() => query.data ?? [], [query.data])
  const filtersActive = search !== '' || status !== 'all' || date !== 'all'

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    const days = DATE_FILTERS.find((d) => d.id === date)?.days ?? 0
    const cutoff = days ? now - days * 86_400_000 : 0
    return all.filter((i) => {
      if (status !== 'all' && i.status !== status) return false
      if (cutoff && new Date(i.updatedAt).getTime() < cutoff) return false
      if (q && !`${i.title} ${i.ticketIds.join(' ')} ${i.problemStatement}`.toLowerCase().includes(q)) return false
      return true
    })
  }, [all, search, status, date, now])

  const { sorted, sort, toggle } = useSort<Investigation, 'title' | 'owner' | 'status' | 'coverage' | 'updated'>(
    filtered,
    {
      title: (i) => i.title.toLowerCase(),
      owner: (i) => (i.owner ?? '').toLowerCase(),
      status: (i) => STATUS_ORDER.indexOf(i.status),
      coverage: (i) => {
        const r = coverageRatio(i.coverage)
        return r.total === 0 ? -1 : r.searched / r.total
      },
      updated: (i) => new Date(i.updatedAt).getTime(),
    },
    { key: 'updated', dir: 'desc' },
  )

  const clear = () => {
    setSearch('')
    setStatus('all')
    setDate('all')
  }

  return (
    <>
      <PageHeader
        title="Investigations"
        actions={
          <Link
            to="/investigations/new"
            data-tour="new-investigation"
            className="inline-flex h-control-md items-center justify-center gap-2 border border-primary bg-primary px-4 font-medium text-primary-fg hover:bg-primary/90"
          >
            <Icon name="plus" /> New investigation
          </Link>
        }
      />

      {query.status === 'loading' ? <SkeletonRows rows={6} /> : null}
      {query.status === 'error' ? <ErrorState message={query.error} onRetry={query.reload} /> : null}

      {query.status === 'success' && all.length === 0 ? (
        <EmptyState
          icon="investigations"
          title="No investigations yet"
          body="Start with a customer escalation. The Investigator searches your connected sources and organizes the history with the evidence behind each claim."
          actions={<Button onClick={() => navigate('/investigations/new')}>Create your first investigation</Button>}
        />
      ) : null}

      {query.status === 'success' && all.length > 0 ? (
        <>
          <div data-tour="list-filters" className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,2fr)_repeat(2,minmax(0,1fr))_auto]">
            <SearchInput label="Search investigations" placeholder="Search by title, ticket or question" value={search} onChange={setSearch} />
            <Select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="all">All statuses</option>
              {STATUS_ORDER.map((s) => (
                <option key={s} value={s}>
                  {investigationStatus[s].label}
                </option>
              ))}
            </Select>
            <Select aria-label="Filter by date" value={date} onChange={(e) => setDate(e.target.value as typeof date)}>
              {DATE_FILTERS.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.label}
                </option>
              ))}
            </Select>
            <Button variant="ghost" onClick={clear} disabled={!filtersActive}>
              Clear filters
            </Button>
          </div>

          {sorted.length === 0 ? (
            <EmptyState
              icon="search"
              title="No investigations match these filters."
              body="Try a different search term or clear the filters."
              actions={<Button variant="outline" onClick={clear}>Clear filters</Button>}
            />
          ) : (
            <TableWrap>
              <Table>
                <caption className="sr-only">Investigations, {sorted.length} shown</caption>
                <thead>
                  <tr>
                    <SortTh label="Investigation" active={sort.key === 'title'} dir={sort.dir} onSort={() => toggle('title')} />
                    <SortTh label="Owner" active={sort.key === 'owner'} dir={sort.dir} onSort={() => toggle('owner')} className="hidden lg:table-cell" />
                    <SortTh label="Status" active={sort.key === 'status'} dir={sort.dir} onSort={() => toggle('status')} />
                    <SortTh label="Source coverage" active={sort.key === 'coverage'} dir={sort.dir} onSort={() => toggle('coverage')} className="hidden md:table-cell" />
                    <SortTh label="Last updated" active={sort.key === 'updated'} dir={sort.dir} onSort={() => toggle('updated')} className="hidden sm:table-cell" />
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((i, row) => (
                    <tr key={i.id} onClick={() => navigate(`/investigations/${i.id}`)} className="cursor-pointer hover:bg-primary/5">
                      <Td>
                        <Link to={`/investigations/${i.id}`} data-tour={row === 0 ? 'first-row' : undefined} onClick={(e) => e.stopPropagation()} className="font-medium text-ink underline-offset-2 hover:underline">
                          {i.title}
                        </Link>
                        {i.sample ? (
                          <Badge tone="accent" className="ml-2 align-middle">
                            Sample
                          </Badge>
                        ) : null}
                        {i.ticketIds.length > 0 ? <span className="block font-mono text-ink-muted">{i.ticketIds.join(', ')}</span> : null}
                      </Td>
                      <Td className="hidden lg:table-cell">{i.owner ?? <span className="text-ink-muted">Not assigned</span>}</Td>
                      <Td>
                        <StatusBadge def={investigationStatus[i.status]} />
                        {i.awaiting ? <span className="mt-1 block text-caption text-ink-muted">{awaitingLabel[i.awaiting]}</span> : null}
                      </Td>
                      <Td className="hidden md:table-cell">
                        <CoverageMeter coverage={i.coverage} />
                      </Td>
                      <Td className="hidden whitespace-nowrap sm:table-cell">{fmt.dateTime(i.updatedAt)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </TableWrap>
          )}
        </>
      ) : null}
    </>
  )
}
