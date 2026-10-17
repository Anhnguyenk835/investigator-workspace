import { useState } from 'react'
import { Link } from 'react-router-dom'
import { providerMeta } from '@/data/mockConnectors'
import { Button, ConfirmDialog, Dialog, EmptyState, ErrorState, Icon, SkeletonRows, Tabs } from '@/components/ui'
import { PageHeader } from '@/components/shared/PageHeader'
import { ProviderMark } from '@/components/shared/ProviderMark'
import { StatusBadge, connectorStatus } from '@/components/shared/StatusBadge'
import { DATE_RANGE_LABEL, ScopeForm, SyncHistoryTable, SyncProgress, scopeSummary } from '@/features/connectors/ConnectorPieces'
import { useProviderParam } from '@/features/connectors/useProviderParam'
import { useApiQuery } from '@/hooks/useApiQuery'
import { useRunAction } from '@/hooks/useRunAction'
import { useFormat } from '@/hooks/useSettings'
import { formatCount } from '@/lib/format'
import { mockApi } from '@/lib/mockApi'
import type { Connector, ConnectorScope } from '@/types/investigator'

type Tab = 'overview' | 'scope' | 'history' | 'access'

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[10rem_1fr] gap-3 border-b border-line-subtle py-2.5 text-caption last:border-b-0">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="min-w-0 break-words text-ink">{children}</dd>
    </div>
  )
}

function EditScopeDialog({ c, onClose }: { c: Connector; onClose: () => void }) {
  const [scope, setScope] = useState<ConnectorScope>(c.scope)
  const [error, setError] = useState<string>()
  const { run, busy } = useRunAction()
  return (
    <Dialog
      open
      onClose={onClose}
      title={`Edit scope · ${providerMeta[c.provider].name}`}
      description="Changes apply to the next sync. Existing indexed records are not removed."
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            disabled={busy}
            onClick={async () => {
              setError(undefined)
              if (scope.resources.length === 0) return setError(`Select at least one item under ${providerMeta[c.provider].resourceLabel}.`)
              if (scope.contentTypes.length === 0) return setError('Select at least one content type.')
              const ok = await run(() => mockApi.updateConnectorScope(c.provider, scope), 'Scope saved. Sync to apply it.')
              if (ok) onClose()
            }}
          >
            Save scope
          </Button>
        </>
      }
    >
      {error ? (
        <p role="alert" className="mb-4 text-caption text-danger">
          {error}
        </p>
      ) : null}
      <ScopeForm provider={c.provider} scope={scope} onChange={setScope} />
    </Dialog>
  )
}

export function ConnectorDetailPage() {
  const provider = useProviderParam()
  const connector = useApiQuery(() => (provider ? mockApi.getConnector(provider) : Promise.resolve(null)), [provider])
  const jobs = useApiQuery(() => (provider ? mockApi.listSyncJobs(provider) : Promise.resolve([])), [provider])
  const fmt = useFormat()
  const { run, busy } = useRunAction()
  const [tab, setTab] = useState<Tab>('overview')
  const [editing, setEditing] = useState(false)
  const [confirming, setConfirming] = useState(false)

  if (!provider) return <EmptyState icon="alert" title="Unknown connector" body="This provider is not in the connector catalog." actions={<Link to="/settings/connectors" className="underline">Back to connectors</Link>} />
  if (connector.status === 'loading') return <SkeletonRows rows={6} />
  if (connector.status === 'error') return <ErrorState message={connector.error} onRetry={connector.reload} />
  const c = connector.data
  if (!c) return <EmptyState icon="alert" title="Connector not found" body="No connector state exists for this provider." actions={<Link to="/settings/connectors" className="underline">Back to connectors</Link>} />

  const meta = providerMeta[provider]
  const crumbs = [{ label: 'Connectors', to: '/settings/connectors' }, { label: meta.name }]
  const running = jobs.data?.find((j) => j.status === 'running' || j.status === 'queued')

  if (c.status === 'not_connected' || c.status === 'connecting') {
    return (
      <>
        <PageHeader crumbs={crumbs} title={meta.name} meta={<StatusBadge def={connectorStatus[c.status]} />} />
        <EmptyState
          icon="plug"
          title={c.status === 'connecting' ? 'Setup is in progress' : `${meta.name} is not connected`}
          body={`${meta.description} Setup is simulated in demo mode: no account is linked and no credentials are requested.`}
          actions={
            <Link to={`/settings/connectors/${provider}/setup`} className="inline-flex h-control-md items-center border border-primary bg-primary px-4 font-medium text-primary-fg hover:bg-primary/90">
              {c.status === 'connecting' ? 'Continue setup' : `Connect ${meta.name}`}
            </Link>
          }
        />
      </>
    )
  }

  const canSync = c.status !== 'syncing' && c.status !== 'permission_revoked'
  const canReconnect = c.status === 'permission_revoked' || c.status === 'sync_failed' || c.status === 'needs_attention'
  const reauth = c.status === 'permission_revoked' || c.status === 'sync_failed'

  return (
    <>
      <PageHeader
        crumbs={crumbs}
        title={
          <span className="flex items-center gap-3">
            <ProviderMark provider={provider} className="size-9" /> {meta.name}
          </span>
        }
        description={`${c.accountLabel ?? ''} · ${c.workspaceLabel ?? ''}`}
        meta={<StatusBadge def={connectorStatus[c.status]} />}
        actions={
          <>
            {canReconnect ? (
              <Button variant="outline" disabled={busy} onClick={() => run(() => mockApi.reconnect(provider), `${meta.name} reauthorized (simulated)`)}>
                Reconnect
              </Button>
            ) : null}
            <Button disabled={!canSync || busy} title={!canSync ? (c.status === 'syncing' ? 'A sync is already running' : 'Reconnect before syncing') : undefined} onClick={() => run(() => mockApi.simulateSync(provider), 'Sync started')}>
              <Icon name="refresh" /> Sync now
            </Button>
            <Button variant="outline" onClick={() => setEditing(true)}>
              <Icon name="edit" /> Edit scope
            </Button>
            <Button variant="danger" onClick={() => setConfirming(true)}>
              Disconnect
            </Button>
          </>
        }
      />

      {c.errorMessage ? (
        <div role="alert" className="mb-5 flex flex-wrap items-center justify-between gap-3 border border-warning bg-warning/10 px-4 py-3">
          <p className="flex items-start gap-2 text-caption text-ink">
            <Icon name="alert" className="mt-0.5 text-warning" /> {c.errorMessage}
          </p>
          <div className="flex gap-2">
            {canReconnect ? (
              <Button size="sm" disabled={busy} onClick={() => run(() => mockApi.reconnect(provider), 'Reauthorized (simulated)')}>
                Reconnect
              </Button>
            ) : null}
            <Link to={`/settings/connectors/${provider}/sync`} className="inline-flex h-control-sm items-center border border-line bg-surface px-3 text-caption hover:bg-surface-muted">
              View sync history
            </Link>
          </div>
        </div>
      ) : null}

      {running ? (
        <div className="mb-5">
          <SyncProgress job={running} />
        </div>
      ) : null}

      <Tabs<Tab>
        label="Connector sections"
        value={tab}
        onChange={setTab}
        tabs={[
          { id: 'overview', label: 'Overview' },
          { id: 'scope', label: 'Data scope' },
          { id: 'history', label: 'Sync history' },
          { id: 'access', label: 'Access & permissions' },
        ]}
      />

      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="mt-5 max-w-4xl">
        {tab === 'overview' ? (
          <dl className="border border-line bg-surface px-5 py-2">
            <Row label="Status">
              <StatusBadge def={connectorStatus[c.status]} />
            </Row>
            <Row label="Last successful sync">{c.lastSuccessfulSyncAt ? fmt.dateTime(c.lastSuccessfulSyncAt) : 'Never'}</Row>
            <Row label="Indexed records">
              {formatCount(c.indexedRecordCount)} <span className="text-ink-muted">(simulated count)</span>
            </Row>
            <Row label="Selected scope">
              {scopeSummary(c)}
              <span className="block text-ink-muted">{DATE_RANGE_LABEL[c.scope.dateRange]}</span>
            </Row>
            <Row label="Permissions">{c.grantedPermissions.length > 0 ? `${c.grantedPermissions.length} granted (demo)` : 'None granted'}</Row>
            <Row label="Mode">Demo connector. No real account is linked.</Row>
          </dl>
        ) : null}

        {tab === 'scope' ? (
          <div className="border border-line bg-surface p-5">
            <dl>
              <Row label={meta.resourceLabel}>{scopeSummary(c)}</Row>
              <Row label="Date range">{DATE_RANGE_LABEL[c.scope.dateRange]}</Row>
              <Row label="Content types">{c.scope.contentTypes.map((id) => meta.contentTypes.find((t) => t.id === id)?.label ?? id).join(', ') || 'None'}</Row>
              <Row label="Archived content">{c.scope.includeArchived ? 'Included' : 'Excluded'}</Row>
            </dl>
            <Button className="mt-4" variant="outline" onClick={() => setEditing(true)}>
              <Icon name="edit" /> Edit scope
            </Button>
          </div>
        ) : null}

        {tab === 'history' ? (
          <div className="flex flex-col gap-3">
            {jobs.status === 'loading' ? <SkeletonRows rows={4} /> : null}
            {jobs.status === 'error' ? <ErrorState message={jobs.error} onRetry={jobs.reload} /> : null}
            {jobs.status === 'success' ? <SyncHistoryTable jobs={(jobs.data ?? []).slice(0, 5)} /> : null}
            <Link to={`/settings/connectors/${provider}/sync`} className="text-caption underline hover:text-info">
              Open full sync history
            </Link>
          </div>
        ) : null}

        {tab === 'access' ? (
          <div className="flex flex-col gap-5">
            <dl className="border border-line bg-surface px-5 py-2">
              <Row label="Granted permissions">
                {c.grantedPermissions.length === 0 ? (
                  'None'
                ) : (
                  <ul className="list-disc pl-4">
                    {c.grantedPermissions.map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                )}
              </Row>
              <Row label="Last permission check">{c.lastPermissionCheckAt ? fmt.dateTime(c.lastPermissionCheckAt) : 'Never'}</Row>
              <Row label="Reauthorization">{reauth ? 'Required' : 'Not required'}</Row>
              <Row label="Mode">Simulated permissions. Nothing was requested from a provider.</Row>
            </dl>
            {reauth ? (
              <div>
                <Button disabled={busy} onClick={() => run(() => mockApi.reconnect(provider), 'Reauthorized (simulated)')}>
                  Reconnect
                </Button>
              </div>
            ) : null}
            <section className="border border-danger bg-surface p-5">
              <h2 className="text-body font-medium text-ink">Danger zone</h2>
              <p className="mt-1 max-w-prose text-caption text-ink-muted">
                Disconnecting stops future syncs and removes this source from new investigations. Existing indexed demo records and past findings are kept.
              </p>
              <Button className="mt-3" variant="danger" onClick={() => setConfirming(true)}>
                Disconnect connector
              </Button>
            </section>
          </div>
        ) : null}
      </div>

      {editing ? <EditScopeDialog c={c} onClose={() => setEditing(false)} /> : null}
      <ConfirmDialog
        open={confirming}
        title={`Disconnect ${meta.name}?`}
        body={
          <div className="flex flex-col gap-2">
            <p>Future syncs stop and {meta.name} will not be searched by new investigations.</p>
            <p className="text-ink-muted">Existing indexed records and past findings are not deleted. Retention rules are not modeled in this prototype.</p>
          </div>
        }
        confirmLabel="Disconnect"
        busy={busy}
        onCancel={() => setConfirming(false)}
        onConfirm={async () => {
          const ok = await run(() => mockApi.disconnect(provider), `${meta.name} disconnected`)
          if (ok) setConfirming(false)
        }}
      />
    </>
  )
}
