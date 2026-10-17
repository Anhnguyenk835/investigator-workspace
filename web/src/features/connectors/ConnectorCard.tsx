import { Badge, Button } from '@/components/ui'
import { ProviderMark } from '@/components/shared/ProviderMark'
import { StatusBadge, connectorStatus } from '@/components/shared/StatusBadge'
import { useFormat } from '@/hooks/useSettings'
import { providerMeta } from '@/lib/providers'
import { relativeTime } from '@/lib/format'
import type { Connector, SourceProvider } from '@/types/investigator'

export function ConnectorCard({
  c,
  busy,
  demo = false,
  onConnect,
  onDisconnect,
}: {
  c: Connector
  busy: boolean
  /** The demo: sources show the stored data, and there is nothing to connect. */
  demo?: boolean
  onConnect: (c: Connector) => void
  onDisconnect: (c: Connector) => void
}) {
  const meta = providerMeta[c.provider]
  const fmt = useFormat()
  const connected = c.status === 'connected' || c.status === 'reauth_required'
  const shared = c.sharedWith.map((p) => providerMeta[p].name).join(', ')

  return (
    <article className="flex min-w-0 flex-col gap-3 border border-line bg-surface p-4 shadow-sm" aria-label={meta.name}>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="flex items-center gap-3">
          <ProviderMark provider={c.provider} className="size-9" />
          <h3 className="text-body font-medium text-ink">{meta.name}</h3>
        </div>
        <StatusBadge def={connectorStatus[c.status]} />
      </div>
      <p className="text-caption text-ink-muted">{meta.description}</p>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-caption">
        <div className="col-span-2">
          <dt className="text-overline uppercase text-ink-muted">Account</dt>
          <dd className="truncate text-ink">{connected ? (c.account ?? 'Connected') : 'None'}</dd>
        </div>
        <div>
          <dt className="text-overline uppercase text-ink-muted">Connected</dt>
          <dd className="text-ink" title={c.connectedAt ? fmt.dateTime(c.connectedAt) : undefined}>
            {connected && c.connectedAt ? relativeTime(c.connectedAt) : '—'}
          </dd>
        </div>
        <div>
          <dt className="text-overline uppercase text-ink-muted">Reads</dt>
          <dd className="text-ink">{meta.recordTypes}</dd>
        </div>
      </dl>
      {shared ? <p className="text-caption text-ink-muted">One connection covers {meta.name} and {shared}.</p> : null}
      {c.status === 'reauth_required' ? (
        <p className="text-caption text-ink">Access expired or was revoked. Searches skip this source until you connect it again.</p>
      ) : null}
      {c.status === 'unavailable' ? (
        <p className="text-caption text-ink-muted">This server has no app credentials for {meta.name}. An administrator has to add them before anyone can connect.</p>
      ) : null}
      <div className="mt-auto flex flex-wrap gap-2 pt-1">
        {demo ? <p className="text-caption text-ink-muted">{connected ? 'Demo data. Sign in to connect your own account.' : 'Not part of the demo data.'}</p> : null}
        {demo ? null : c.status === 'not_connected' ? (
          <Button size="sm" disabled={busy} onClick={() => onConnect(c)}>
            Connect
          </Button>
        ) : null}
        {!demo && c.status === 'reauth_required' ? (
          <Button size="sm" disabled={busy} onClick={() => onConnect(c)}>
            Reconnect
          </Button>
        ) : null}
        {!demo && (c.status === 'connected' || c.status === 'reauth_required') ? (
          <Button size="sm" variant="outline" disabled={busy} onClick={() => onDisconnect(c)}>
            Disconnect
          </Button>
        ) : null}
        {!demo && c.status === 'unavailable' ? (
          <Button size="sm" variant="outline" disabled>
            Connect
          </Button>
        ) : null}
      </div>
    </article>
  )
}

/** A provider that is planned but cannot be connected yet. Nothing here is actionable. */
export function ComingSoonCard({ provider }: { provider: SourceProvider }) {
  const meta = providerMeta[provider]
  return (
    <article className="flex min-w-0 flex-col gap-3 border border-line-subtle bg-surface-muted/50 p-4" aria-label={`${meta.name}, coming soon`}>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="flex items-center gap-3">
          <span className="opacity-70 grayscale">
            <ProviderMark provider={provider} className="size-9" />
          </span>
          <h3 className="text-body font-medium text-ink-muted">{meta.name}</h3>
        </div>
        <Badge tone="muted">Coming soon</Badge>
      </div>
      <p className="text-caption text-ink-muted">{meta.description}</p>
      <div className="mt-auto pt-1">
        <Button size="sm" variant="outline" disabled>
          Connect
        </Button>
      </div>
    </article>
  )
}
