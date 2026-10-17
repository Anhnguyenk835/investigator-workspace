import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Button, EmptyState, ErrorState, Select, SkeletonRows, Table, TableWrap, Td, Th } from '@/components/ui'
import { PageHeader } from '@/components/shared/PageHeader'
import { SearchInput } from '@/components/shared/SearchInput'
import { useApiQuery } from '@/hooks/useApiQuery'
import { useFormat } from '@/hooks/useSettings'
import { mockApi } from '@/lib/mockApi'
import type { ActivityEvent, ActivityKind } from '@/types/investigator'

const GROUPS: Record<string, ActivityKind[]> = {
  Investigations: ['investigation_created', 'investigation_rerun', 'investigation_updated', 'investigation_resolved'],
  Review: ['finding_reviewed', 'issue_reviewed', 'action_updated'],
  'Customer drafts': ['draft_saved', 'draft_approved'],
  Connectors: ['connector_connected', 'connector_disconnected', 'scope_changed'],
  Syncs: ['sync_completed', 'sync_failed'],
  Workspace: ['demo_reset'],
}

const OUTCOME: Record<ActivityEvent['outcome'], { label: string; tone: 'successSoft' | 'warningSoft' | 'dangerSoft' }> = {
  success: { label: 'Success', tone: 'successSoft' },
  warning: { label: 'Warning', tone: 'warningSoft' },
  failed: { label: 'Failed', tone: 'dangerSoft' },
}

function relatedLink(e: ActivityEvent): string | undefined {
  if (e.relatedType === 'investigation' && e.relatedId) return `/investigations/${e.relatedId}`
  if (e.relatedType === 'connector' && e.relatedId) return `/settings/connectors/${e.relatedId}`
  return undefined
}

export function ActivityPage() {
  const query = useApiQuery(() => mockApi.listActivity(), [])
  const fmt = useFormat()
  const [search, setSearch] = useState('')
  const [group, setGroup] = useState('all')
  const [actor, setActor] = useState('all')
  const [outcome, setOutcome] = useState('all')

  const all = useMemo(() => query.data ?? [], [query.data])
  const actors = useMemo(() => [...new Set(all.map((e) => e.actor))].sort(), [all])
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase()
    return all.filter((e) => {
      if (group !== 'all' && !GROUPS[group]?.includes(e.kind)) return false
      if (actor !== 'all' && e.actor !== actor) return false
      if (outcome !== 'all' && e.outcome !== outcome) return false
      return !q || `${e.label} ${e.relatedLabel} ${e.detail ?? ''} ${e.actor}`.toLowerCase().includes(q)
    })
  }, [all, search, group, actor, outcome])
  const active = search !== '' || group !== 'all' || actor !== 'all' || outcome !== 'all'
  const clear = () => {
    setSearch('')
    setGroup('all')
    setActor('all')
    setOutcome('all')
  }

  return (
    <>
      <PageHeader title="Activity" description="Actions taken in this workspace. In demo mode this log lives in your browser and can be reset." />
      {query.status === 'loading' ? <SkeletonRows rows={7} /> : null}
      {query.status === 'error' ? <ErrorState message={query.error} onRetry={query.reload} /> : null}
      {query.status === 'success' ? (
        <>
          <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,2fr)_repeat(3,minmax(0,1fr))_auto]">
            <SearchInput label="Search activity" placeholder="Search events, items or people" value={search} onChange={setSearch} />
            <Select aria-label="Event type" value={group} onChange={(e) => setGroup(e.target.value)}>
              <option value="all">All event types</option>
              {Object.keys(GROUPS).map((g) => (
                <option key={g}>{g}</option>
              ))}
            </Select>
            <Select aria-label="Actor" value={actor} onChange={(e) => setActor(e.target.value)}>
              <option value="all">All actors</option>
              {actors.map((a) => (
                <option key={a}>{a}</option>
              ))}
            </Select>
            <Select aria-label="Outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
              <option value="all">All outcomes</option>
              <option value="success">Success</option>
              <option value="warning">Warning</option>
              <option value="failed">Failed</option>
            </Select>
            <Button variant="ghost" onClick={clear} disabled={!active}>
              Clear filters
            </Button>
          </div>
          {all.length === 0 ? (
            <EmptyState icon="pulse" title="No activity yet" body="Actions such as reviewing findings, approving drafts and syncing connectors appear here." />
          ) : shown.length === 0 ? (
            <EmptyState icon="search" title="No events match these filters" body="Try clearing a filter." actions={<Button variant="outline" onClick={clear}>Clear filters</Button>} />
          ) : (
            <TableWrap>
              <Table>
                <caption className="sr-only">Activity events, newest first</caption>
                <thead>
                  <tr>
                    <Th>Event</Th>
                    <Th className="hidden md:table-cell">Actor</Th>
                    <Th>Related item</Th>
                    <Th className="hidden sm:table-cell">Timestamp</Th>
                    <Th>Outcome</Th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((e) => {
                    const link = relatedLink(e)
                    return (
                      <tr key={e.id}>
                        <Td>
                          {e.label}
                          {e.detail ? <span className="block text-ink-muted">{e.detail}</span> : null}
                        </Td>
                        <Td className="hidden md:table-cell">{e.actor}</Td>
                        <Td>
                          {link ? (
                            <Link to={link} className="underline-offset-2 hover:underline">
                              {e.relatedLabel}
                            </Link>
                          ) : (
                            e.relatedLabel
                          )}
                        </Td>
                        <Td className="hidden whitespace-nowrap sm:table-cell">{fmt.dateTime(e.at)}</Td>
                        <Td>
                          <Badge tone={OUTCOME[e.outcome].tone}>{OUTCOME[e.outcome].label}</Badge>
                        </Td>
                      </tr>
                    )
                  })}
                </tbody>
              </Table>
            </TableWrap>
          )}
        </>
      ) : null}
    </>
  )
}
