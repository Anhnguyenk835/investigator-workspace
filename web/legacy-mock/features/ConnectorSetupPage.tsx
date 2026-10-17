import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { providerMeta } from '@/data/mockConnectors'
import { Badge, Button, Checkbox, EmptyState, ErrorState, Icon, SkeletonRows } from '@/components/ui'
import { PageHeader } from '@/components/shared/PageHeader'
import { ProviderMark } from '@/components/shared/ProviderMark'
import { DATE_RANGE_LABEL, ScopeForm, SyncProgress, SyncSummary, scopeSummary } from '@/features/connectors/ConnectorPieces'
import { useProviderParam } from '@/features/connectors/useProviderParam'
import { useApiQuery } from '@/hooks/useApiQuery'
import { useRunAction } from '@/hooks/useRunAction'
import { formatCount } from '@/lib/format'
import { mockApi, type TestConnectionResult } from '@/lib/mockApi'
import { isConnected } from '@/lib/mock/analysis'
import { cn } from '@/lib/cn'
import type { ConnectorScope } from '@/types/investigator'

const STEPS = ['Connect account', 'Choose data scope', 'Test access', 'Start sync'] as const

function Stepper({ step }: { step: number }) {
  return (
    <ol className="mb-6 grid grid-cols-2 gap-px border border-line bg-line-subtle sm:grid-cols-4" aria-label="Setup steps">
      {STEPS.map((label, i) => {
        const n = i + 1
        const done = n < step
        const current = n === step
        return (
          <li key={label} aria-current={current ? 'step' : undefined} className={cn('flex items-center gap-3 bg-surface px-3 py-3 text-caption', current && 'bg-primary/10')}>
            <span className={cn('flex size-6 shrink-0 items-center justify-center border text-overline', done ? 'border-success bg-success text-success-fg' : current ? 'border-primary bg-primary text-primary-fg' : 'border-line-subtle text-ink-muted')}>
              {done ? <Icon name="check" className="size-3" /> : n}
            </span>
            <span className={current ? 'font-medium text-ink' : 'text-ink-muted'}>
              {label}
              <span className="sr-only">{done ? ' (complete)' : current ? ' (current)' : ''}</span>
            </span>
          </li>
        )
      })}
    </ol>
  )
}

export function ConnectorSetupPage() {
  const provider = useProviderParam()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const connector = useApiQuery(() => (provider ? mockApi.getConnector(provider) : Promise.resolve(null)), [provider])
  const jobs = useApiQuery(() => (provider ? mockApi.listSyncJobs(provider) : Promise.resolve([])), [provider])
  const { run, busy } = useRunAction()
  const [scope, setScope] = useState<ConnectorScope | null>(null)
  const [scopeError, setScopeError] = useState<string>()
  const [simulateError, setSimulateError] = useState(false)
  const [result, setResult] = useState<TestConnectionResult | null>(null)

  const c = connector.data
  const requested = Number(params.get('step') ?? '1')
  const connecting = c?.status === 'connecting'
  const setupJob = jobs.data?.find((j) => j.trigger === 'setup')
  // Step 4 can be revisited after reload while a setup sync exists and setup itself is done.
  const step = connecting ? Math.min(Math.max(requested, 2), 3) : setupJob && c && isConnected(c) ? 4 : 1

  const go = (n: number) => setParams({ step: String(n) }, { replace: true })

  useEffect(() => {
    if (c && scope === null && connecting) setScope(c.scope)
  }, [c, scope, connecting])

  if (!provider) return <EmptyState icon="alert" title="Unknown connector" body="This provider is not in the connector catalog." actions={<Link to="/settings/connectors" className="underline">Back to connectors</Link>} />
  const meta = providerMeta[provider]
  if (connector.status === 'loading') return <SkeletonRows rows={6} />
  if (connector.status === 'error') return <ErrorState message={connector.error} onRetry={connector.reload} />
  if (!c) return <EmptyState icon="alert" title="Connector not found" body="No connector state exists for this provider." />

  const crumbs = [{ label: 'Connectors', to: '/settings/connectors' }, { label: meta.name, to: `/settings/connectors/${provider}` }, { label: 'Setup' }]

  // Already connected and not mid-setup: setup does not apply.
  if (isConnected(c) && !setupJob) {
    return (
      <>
        <PageHeader crumbs={crumbs} title={`${meta.name} is already connected`} />
        <EmptyState
          icon="circleCheck"
          title="Nothing to set up"
          body="Use Manage to change the scope, sync, reconnect or disconnect this connector."
          actions={<Link to={`/settings/connectors/${provider}`} className="inline-flex h-control-md items-center border border-primary bg-primary px-4 font-medium text-primary-fg">Open connector</Link>}
        />
      </>
    )
  }

  const cancel = async () => {
    await run(() => mockApi.cancelSetup(provider))
    navigate('/settings/connectors')
  }

  const latestSetup = jobs.data?.find((j) => j.trigger === 'setup')

  return (
    <>
      <PageHeader
        crumbs={crumbs}
        title={
          <span className="flex items-center gap-3">
            <ProviderMark provider={provider} className="size-9" /> Connect {meta.name}
          </span>
        }
        description="A four-step simulated setup."
        meta={
          <p className="flex items-start gap-2 border border-info/50 bg-info/10 px-3 py-2 text-caption text-ink">
            <Icon name="info" className="mt-0.5 text-info" />
            <span>
              <strong>Demo mode.</strong> This flow is simulated. No real account is linked, no OAuth happens, and you are never asked for a password or token.
            </span>
          </p>
        }
      />
      <Stepper step={step} />

      <div className="max-w-3xl border border-line bg-surface p-5">
        {step === 1 ? (
          <div className="flex flex-col gap-5">
            <h2 className="text-heading">Connect account</h2>
            <dl className="grid gap-4 sm:grid-cols-2">
              <div>
                <dt className="text-overline uppercase text-ink-muted">Data that may be accessed</dt>
                <dd className="mt-1 text-body text-ink">{meta.recordTypes}</dd>
              </div>
              <div>
                <dt className="text-overline uppercase text-ink-muted">Permissions requested</dt>
                <dd className="mt-1">
                  <ul className="list-disc pl-4 text-body text-ink">
                    {meta.permissions.map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                </dd>
              </div>
            </dl>
            <p className="max-w-prose text-caption text-ink-muted">
              A real connector would only request read access, so investigations can cite original records. Here, simulating the connection links the demo account <code className="font-mono">{meta.demoAccount}</code>.
            </p>
            <div className="flex flex-wrap justify-end gap-2">
              <Button variant="outline" onClick={() => navigate('/settings/connectors')} disabled={busy}>
                Cancel
              </Button>
              <Button
                disabled={busy}
                onClick={async () => {
                  const ok = await run(() => mockApi.simulateConnection(provider), 'Demo account linked (simulated)')
                  if (ok) {
                    setScope(ok.scope)
                    go(2)
                  }
                }}
              >
                Simulate connection
              </Button>
            </div>
          </div>
        ) : null}

        {step === 2 && scope ? (
          <div className="flex flex-col gap-5">
            <div>
              <h2 className="text-heading">Choose data scope</h2>
              <p className="mt-1 text-caption text-ink-muted">
                Connected as {c.accountLabel} · {c.workspaceLabel}
              </p>
            </div>
            {scopeError ? (
              <p role="alert" className="text-caption text-danger">
                {scopeError}
              </p>
            ) : null}
            <ScopeForm provider={provider} scope={scope} onChange={(s) => { setScope(s); setScopeError(undefined) }} />
            <div className="flex flex-wrap justify-between gap-2">
              <Button variant="ghost" onClick={cancel} disabled={busy}>
                Cancel setup
              </Button>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => go(1)}>
                  Back
                </Button>
                <Button
                  disabled={busy}
                  onClick={async () => {
                    if (scope.resources.length === 0) return setScopeError(`Select at least one item under ${meta.resourceLabel}.`)
                    if (scope.contentTypes.length === 0) return setScopeError('Select at least one content type.')
                    const ok = await run(() => mockApi.updateConnectorScope(provider, scope, { log: false }))
                    if (ok) {
                      setResult(null)
                      go(3)
                    }
                  }}
                >
                  Continue
                </Button>
              </div>
            </div>
          </div>
        ) : null}

        {step === 3 ? (
          <div className="flex flex-col gap-5">
            <h2 className="text-heading">Test access</h2>
            <dl className="grid gap-3 border border-line-subtle p-4 sm:grid-cols-2">
              <div>
                <dt className="text-overline uppercase text-ink-muted">Authentication</dt>
                <dd className="text-caption text-ink">Signed in as {c.accountLabel} (simulated)</dd>
              </div>
              <div>
                <dt className="text-overline uppercase text-ink-muted">{meta.resourceLabel}</dt>
                <dd className="text-caption text-ink">{scopeSummary(c)}</dd>
              </div>
              <div>
                <dt className="text-overline uppercase text-ink-muted">Date range</dt>
                <dd className="text-caption text-ink">{DATE_RANGE_LABEL[c.scope.dateRange]}</dd>
              </div>
              <div>
                <dt className="text-overline uppercase text-ink-muted">Record estimate</dt>
                <dd className="text-caption text-ink">{result?.ok ? `About ${formatCount(result.recordEstimate)} (simulated)` : 'Run the test to estimate'}</dd>
              </div>
            </dl>
            <Checkbox label="Simulate a permission error (demo)" description="Use this to see how a failed test is reported." checked={simulateError} onChange={(e) => setSimulateError(e.target.checked)} />
            {result ? (
              result.ok ? (
                <div role="status" className="border border-success bg-success/10 p-4">
                  <p className="flex items-center gap-2 text-body font-medium text-ink">
                    <Icon name="circleCheck" className="text-success" /> Connection test passed
                  </p>
                  <p className="mt-2 text-overline uppercase text-ink-muted">Granted permissions (demo)</p>
                  <ul className="list-disc pl-4 text-caption text-ink">
                    {result.permissions.map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                </div>
              ) : (
                <div role="alert" className="border border-danger bg-danger/10 p-4">
                  <p className="flex items-center gap-2 text-body font-medium text-ink">
                    <Icon name="x" className="text-danger" /> Connection test failed <Badge tone="dangerSoft">{result.errorCode}</Badge>
                  </p>
                  <p className="mt-1 text-caption text-ink">{result.errorMessage}</p>
                  <p className="mt-1 text-caption text-ink-muted">Turn off the simulated error and test again, or go back and change the scope.</p>
                </div>
              )
            ) : null}
            <div className="flex flex-wrap justify-between gap-2">
              <Button variant="ghost" onClick={cancel} disabled={busy}>
                Cancel setup
              </Button>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => go(2)} disabled={busy}>
                  Back
                </Button>
                <Button variant="outline" disabled={busy} onClick={async () => setResult((await run(() => mockApi.testConnection(provider, { simulatePermissionError: simulateError }))) ?? null)}>
                  Test connection
                </Button>
                <Button
                  disabled={!result?.ok || busy}
                  onClick={async () => {
                    // Starting the sync leaves the connecting state; step 4 follows from the job.
                    const job = await run(() => mockApi.simulateSync(provider, 'setup'))
                    if (job) setParams({}, { replace: true })
                  }}
                >
                  Start sync
                </Button>
              </div>
            </div>
          </div>
        ) : null}

        {step === 4 && latestSetup ? (
          <div className="flex flex-col gap-5">
            <h2 className="text-heading">Start sync</h2>
            {latestSetup.status === 'running' || latestSetup.status === 'queued' ? (
              <SyncProgress job={latestSetup} />
            ) : (
              <>
                <SyncSummary job={latestSetup} />
                <dl className="text-caption text-ink-muted">Date range covered: {DATE_RANGE_LABEL[c.scope.dateRange]}. Counts are simulated.</dl>
                <div className="flex flex-wrap gap-2">
                  <Link to={`/settings/connectors/${provider}`} className="inline-flex h-control-md items-center border border-primary bg-primary px-4 font-medium text-primary-fg hover:bg-primary/90">
                    Open connector
                  </Link>
                  <Link to="/investigations/new" className="inline-flex h-control-md items-center border border-line bg-surface px-4 hover:bg-surface-muted">
                    Start an investigation
                  </Link>
                </div>
              </>
            )}
          </div>
        ) : null}
      </div>
    </>
  )
}
