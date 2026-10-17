import { useMemo, useState } from 'react'
import { EmptyState, Select, SortTh, Table, TableWrap, Td } from '@/components/ui'
import { ProviderName } from '@/components/shared/ProviderMark'
import { SearchInput } from '@/components/shared/SearchInput'
import { StatusBadge, coverageStatus } from '@/components/shared/StatusBadge'
import { useOpenEvidence } from '@/features/evidence/EvidenceCitation'
import { Section } from '@/features/investigations/workspace/parts'
import { useFormat } from '@/hooks/useSettings'
import { useSort } from '@/hooks/useSort'
import { recordTypeLabel } from '@/lib/labels'
import { providerMeta, providerOrder } from '@/lib/providers'
import type { EvidenceRecord, InvestigationBundle, RecordType, SourceProvider } from '@/types/investigator'

type Key = 'title' | 'provider' | 'type' | 'author' | 'date'

function CoverageList({ b }: { b: InvestigationBundle }) {
  if (b.investigation.coverage.length === 0) {
    return <p className="text-caption text-ink-muted">No source has been searched yet.</p>
  }
  return (
    <ul className="grid gap-2 md:grid-cols-2">
      {b.investigation.coverage.map((c) => (
        <li key={c.provider} className="flex flex-col gap-1 border border-line-subtle px-3 py-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <ProviderName provider={c.provider} />
            <StatusBadge def={coverageStatus[c.status]} />
          </div>
          {c.warning ? <p className="text-caption text-ink-muted">{c.warning}</p> : null}
        </li>
      ))}
    </ul>
  )
}

export function SourcesSection({ bundle }: { bundle: InvestigationBundle }) {
  const fmt = useFormat()
  const { open } = useOpenEvidence()
  const records = bundle.evidence
  const [search, setSearch] = useState('')
  const [provider, setProvider] = useState('all')
  const [type, setType] = useState('all')

  const providers = useMemo(() => providerOrder.filter((p) => records.some((e) => e.provider === p)), [records])
  const types = useMemo(() => [...new Set(records.map((e) => e.recordType))], [records])
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return records.filter(
      (e) =>
        (provider === 'all' || e.provider === provider) &&
        (type === 'all' || e.recordType === type) &&
        (!q || `${e.title} ${e.author ?? ''} ${e.excerpt}`.toLowerCase().includes(q)),
    )
  }, [records, search, provider, type])

  const { sorted, sort, toggle } = useSort<EvidenceRecord, Key>(
    filtered,
    {
      title: (e) => e.title.toLowerCase(),
      provider: (e) => providerMeta[e.provider].name,
      type: (e) => e.recordType,
      author: (e) => (e.author ?? '').toLowerCase(),
      date: (e) => (e.timestamp ? new Date(e.timestamp).getTime() : Number.MAX_SAFE_INTEGER),
    },
    { key: 'date', dir: 'asc' },
  )

  return (
    <Section
      id="sources"
      title="Sources"
      description="What each source returned for this investigation, and the records it collected."
      aside={<span className="text-caption text-ink-muted">{sorted.length === records.length ? `${records.length} ${records.length === 1 ? 'record' : 'records'}` : `${sorted.length} of ${records.length} records`}</span>}
    >
      <div className="flex flex-col gap-6">
        <div>
          <h3 className="mb-2 text-body font-medium text-ink">Coverage</h3>
          <CoverageList b={bundle} />
        </div>
        <div>
          <h3 className="mb-2 text-body font-medium text-ink">Records</h3>
          {records.length === 0 ? (
            <EmptyState icon="database" title="No source records" body="The searched sources returned no records for this investigation. Check coverage above for sources that were not searched." />
          ) : (
            <>
              <div className="mb-4 grid gap-2 sm:grid-cols-[minmax(0,1fr)_11rem_11rem]">
                <SearchInput label="Search records" placeholder="Search title, author or excerpt" value={search} onChange={setSearch} />
                <Select aria-label="Provider" value={provider} onChange={(e) => setProvider(e.target.value)}>
                  <option value="all">All providers</option>
                  {providers.map((p: SourceProvider) => (
                    <option key={p} value={p}>
                      {providerMeta[p].name}
                    </option>
                  ))}
                </Select>
                <Select aria-label="Record type" value={type} onChange={(e) => setType(e.target.value)}>
                  <option value="all">All record types</option>
                  {types.map((t: RecordType) => (
                    <option key={t} value={t}>
                      {recordTypeLabel[t]}
                    </option>
                  ))}
                </Select>
              </div>
              {sorted.length === 0 ? (
                <EmptyState icon="search" title="No records match" body="Try a broader search or clear the filters." />
              ) : (
                <TableWrap>
                  <Table>
                    <caption className="sr-only">Source records for this investigation</caption>
                    <thead>
                      <tr>
                        <SortTh label="Record" active={sort.key === 'title'} dir={sort.dir} onSort={() => toggle('title')} />
                        <SortTh label="Provider" active={sort.key === 'provider'} dir={sort.dir} onSort={() => toggle('provider')} />
                        <SortTh label="Type" active={sort.key === 'type'} dir={sort.dir} onSort={() => toggle('type')} className="hidden md:table-cell" />
                        <SortTh label="Author" active={sort.key === 'author'} dir={sort.dir} onSort={() => toggle('author')} className="hidden lg:table-cell" />
                        <SortTh label="Date" active={sort.key === 'date'} dir={sort.dir} onSort={() => toggle('date')} className="hidden sm:table-cell" />
                      </tr>
                    </thead>
                    <tbody>
                      {sorted.map((e) => (
                        <tr key={e.id} onClick={() => open(e.id)} className="cursor-pointer hover:bg-primary/5">
                          <Td>
                            <button
                              type="button"
                              onClick={(ev) => {
                                ev.stopPropagation()
                                open(e.id)
                              }}
                              className="text-left font-medium underline-offset-2 hover:underline"
                            >
                              {e.title}
                            </button>
                          </Td>
                          <Td>
                            <ProviderName provider={e.provider} />
                          </Td>
                          <Td className="hidden md:table-cell">{recordTypeLabel[e.recordType]}</Td>
                          <Td className="hidden lg:table-cell">
                            {e.author ?? <span className="text-ink-muted">Unknown</span>}
                            {e.authorSide ? <span className="block text-ink-muted">{e.authorSide === 'customer' ? 'Customer side' : e.authorSide === 'internal' ? 'Our team' : 'Other party'}</span> : null}
                          </Td>
                          <Td className="hidden whitespace-nowrap sm:table-cell">{fmt.stamp(e.timestamp, e.timestampPrecision)}</Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </TableWrap>
              )}
            </>
          )}
        </div>
      </div>
    </Section>
  )
}
