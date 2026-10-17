import { Link } from 'react-router-dom'
import { providerMeta } from '@/data/mockConnectors'
import { Button, EmptyState, ErrorState, Icon, SkeletonRows } from '@/components/ui'
import { PageHeader } from '@/components/shared/PageHeader'
import { SyncHistoryTable, SyncProgress } from '@/features/connectors/ConnectorPieces'
import { useProviderParam } from '@/features/connectors/useProviderParam'
import { useApiQuery } from '@/hooks/useApiQuery'
import { useRunAction } from '@/hooks/useRunAction'
import { mockApi } from '@/lib/mockApi'

export function SyncHistoryPage() {
  const provider = useProviderParam()
  const jobs = useApiQuery(() => (provider ? mockApi.listSyncJobs(provider) : Promise.resolve([])), [provider])
  const connector = useApiQuery(() => (provider ? mockApi.getConnector(provider) : Promise.resolve(null)), [provider])
  const { run, busy } = useRunAction()

  if (!provider) return <EmptyState icon="alert" title="Unknown connector" body="This provider is not in the connector catalog." actions={<Link to="/settings/connectors" className="underline">Back to connectors</Link>} />
  const meta = providerMeta[provider]
  const c = connector.data
  const canSync = Boolean(c) && c?.status !== 'not_connected' && c?.status !== 'connecting' && c?.status !== 'syncing' && c?.status !== 'permission_revoked'
  const running = jobs.data?.find((j) => j.status === 'running' || j.status === 'queued')

  return (
    <>
      <PageHeader
        crumbs={[{ label: 'Connectors', to: '/settings/connectors' }, { label: meta.name, to: `/settings/connectors/${provider}` }, { label: 'Sync history' }]}
        title={`${meta.name} sync history`}
        description="Every sync job for this connector. Counts are simulated."
        actions={
          <Button disabled={!canSync || busy} title={!canSync ? 'This connector cannot sync right now' : undefined} onClick={() => run(() => mockApi.simulateSync(provider), 'Sync started')}>
            <Icon name="refresh" /> Sync now
          </Button>
        }
      />
      {running ? (
        <div className="mb-5">
          <SyncProgress job={running} />
        </div>
      ) : null}
      {jobs.status === 'loading' ? <SkeletonRows rows={5} /> : null}
      {jobs.status === 'error' ? <ErrorState message={jobs.error} onRetry={jobs.reload} /> : null}
      {jobs.status === 'success' ? <SyncHistoryTable jobs={jobs.data ?? []} /> : null}
    </>
  )
}
