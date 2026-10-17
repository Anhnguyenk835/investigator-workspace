import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '@/api/client'
import { toConnectors } from '@/api/adapt'
import { ConfirmDialog, EmptyState, ErrorState, SkeletonRows } from '@/components/ui'
import { useToast } from '@/components/ui/Toast'
import { PageHeader } from '@/components/shared/PageHeader'
import { SearchInput } from '@/components/shared/SearchInput'
import { ComingSoonCard, ConnectorCard } from '@/features/connectors/ConnectorCard'
import { useAuth } from '@/features/auth/AuthProvider'
import { useApiQuery } from '@/hooks/useApiQuery'
import { useRunAction } from '@/hooks/useRunAction'
import { cn } from '@/lib/cn'
import { isSupported, providerMeta, providerOrder } from '@/lib/providers'
import type { Connector, SourceProvider } from '@/types/investigator'

type Filter = 'all' | 'connected' | 'not_connected' | 'attention'

const matches: Record<Filter, (c: Connector) => boolean> = {
  all: () => true,
  connected: (c) => c.status === 'connected',
  not_connected: (c) => c.status === 'not_connected' || c.status === 'unavailable',
  attention: (c) => c.status === 'reauth_required',
}

const filters: [Filter, string][] = [
  ['all', 'All'],
  ['connected', 'Connected'],
  ['not_connected', 'Not connected'],
  ['attention', 'Needs attention'],
]

/** What a provider's error code means for the person, without echoing the provider's text. */
const OAUTH_ERRORS: Record<string, string> = {
  access_denied: 'You cancelled the connection, so nothing was connected.',
  invalid_state: 'That connection attempt expired or was already used. Start again.',
  expired_state: 'That connection attempt expired. Start again.',
  not_configured: 'This server has no app credentials for that provider.',
  provider_unreachable: 'The provider did not respond. Try again in a moment.',
}

/** Reports the result of the redirect back from a provider, then clears it from the URL. */
function useOAuthResult(reload: () => void) {
  const [params, setParams] = useSearchParams()
  const toast = useToast()
  const connected = params.get('connected')
  const error = params.get('error')
  const provider = params.get('provider')

  useEffect(() => {
    if (!connected && !error) return
    if (connected) toast.success('Connected', 'The source can now be searched in new investigations.')
    else toast.error('Not connected', OAUTH_ERRORS[error ?? ''] ?? `The provider returned an error (${error}).`)
    setParams({}, { replace: true })
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, error, provider])
}

export function ConnectorsPage() {
  const { isDemo } = useAuth()
  const query = useApiQuery(async () => toConnectors(await api.listIntegrations()), [])
  const { run, busy } = useRunAction()
  const [filter, setFilter] = useState<Filter>('all')
  const [search, setSearch] = useState('')
  const [disconnecting, setDisconnecting] = useState<Connector>()
  useOAuthResult(query.refresh)

  const all = useMemo(() => query.data ?? [], [query.data])
  const counts = (Object.keys(matches) as Filter[]).reduce(
    (acc, f) => ({ ...acc, [f]: all.filter(matches[f]).length }),
    {} as Record<Filter, number>,
  )

  const q = search.trim().toLowerCase()
  const fits = (p: SourceProvider) => !q || `${providerMeta[p].name} ${providerMeta[p].description}`.toLowerCase().includes(q)
  const shown = providerOrder.filter(isSupported).flatMap((p) => all.filter((c) => c.provider === p && matches[filter](c) && fits(p)))
  // Planned providers have no connection state, so they only appear when nothing is filtered by state.
  const soon = filter === 'all' ? providerOrder.filter((p) => !isSupported(p) && fits(p)) : []

  const connect = (c: Connector) =>
    run(async () => {
      const { authorization_url } = await api.authorizeIntegration(c.integration)
      window.location.assign(authorization_url)
    })

  return (
    <>
      <PageHeader title="Connectors" description={isDemo ? 'The demo reads stored fictional data from these sources. Nothing is connected to a real account.' : 'Sources are read with your own permissions. Connect one to include it in new investigations.'} />

      {query.status === 'loading' ? <SkeletonRows rows={6} /> : null}
      {query.status === 'error' ? <ErrorState message={query.error} onRetry={query.reload} /> : null}
      {query.status === 'success' ? (
        <>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div role="group" aria-label="Filter connectors" className="inline-flex flex-wrap border border-line">
              {filters.map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  aria-pressed={filter === id}
                  onClick={() => setFilter(id)}
                  className={cn('px-3 py-2 text-caption', filter === id ? 'bg-primary text-primary-fg' : 'bg-surface text-ink hover:bg-surface-muted')}
                >
                  {label} <span className="opacity-70">{counts[id]}</span>
                </button>
              ))}
            </div>
            <SearchInput className="w-full sm:w-72" label="Search connectors" placeholder="Search connectors..." value={search} onChange={setSearch} />
          </div>

          {shown.length + soon.length === 0 ? (
            <EmptyState
              icon="plug"
              title="No connectors match"
              body="No connector fits this filter or search."
              actions={
                <button
                  type="button"
                  className="inline-flex h-control-md items-center border border-line bg-surface px-4 hover:bg-surface-muted"
                  onClick={() => {
                    setFilter('all')
                    setSearch('')
                  }}
                >
                  Show all connectors
                </button>
              }
            />
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {shown.map((c) => (
                <ConnectorCard key={c.provider} c={c} demo={isDemo} busy={busy} onConnect={connect} onDisconnect={setDisconnecting} />
              ))}
              {soon.map((p) => (
                <ComingSoonCard key={p} provider={p} />
              ))}
            </div>
          )}
        </>
      ) : null}

      <ConfirmDialog
        open={Boolean(disconnecting)}
        title={`Disconnect ${disconnecting ? providerMeta[disconnecting.provider].name : ''}?`}
        body={
          disconnecting && disconnecting.sharedWith.length > 0
            ? `This also disconnects ${disconnecting.sharedWith.map((p) => providerMeta[p].name).join(', ')}, which use the same connection. Stored access is deleted; investigations you already ran keep their evidence.`
            : 'Stored access is deleted and new investigations will skip this source. Investigations you already ran keep their evidence.'
        }
        confirmLabel="Disconnect"
        busy={busy}
        onCancel={() => setDisconnecting(undefined)}
        onConfirm={async () => {
          if (!disconnecting) return
          const done = await run(async () => {
            await api.disconnectIntegration(disconnecting.integration)
            return true
          }, 'Disconnected')
          if (done) {
            setDisconnecting(undefined)
            query.refresh()
          }
        }}
      />
    </>
  )
}
