import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, exportUrl } from '@/api/client'
import { toBundle, toDirectory } from '@/api/adapt'
import { ApiError } from '@/api/http'
import { Badge, Button, ConfirmDialog, Dialog, Drawer, EmptyState, ErrorState, Icon, SkeletonRows, Tabs } from '@/components/ui'
import { useToast } from '@/components/ui/Toast'
import { PageHeader } from '@/components/shared/PageHeader'
import { StatusBadge, investigationStatus } from '@/components/shared/StatusBadge'
import { AgentOrb } from '@/features/agent/AgentOrb'
import { AgentPanel } from '@/features/agent/AgentPanel'
import { REVEAL_EVENT } from '@/features/agent/highlight'
import { useRegisterBundle } from '@/features/evidence/EvidenceIndex'
import { CheckpointPanel } from '@/features/investigations/CheckpointPanel'
import { ResponsePanel } from '@/features/investigations/ResponsePage'
import { awaitingLabel } from '@/features/investigations/awaiting'
import { ActionsSection } from '@/features/investigations/workspace/ActionsSection'
import { CommitmentsSection } from '@/features/investigations/workspace/CommitmentsSection'
import { FindingsSection } from '@/features/investigations/workspace/FindingsSection'
import { IssuesSection } from '@/features/investigations/workspace/IssuesSection'
import { RunProgress } from '@/features/investigations/workspace/RunProgress'
import { SourcesSection } from '@/features/investigations/workspace/SourcesSection'
import { SummarySection } from '@/features/investigations/workspace/SummarySection'
import { TimelineSection } from '@/features/investigations/workspace/TimelineSection'
import { useRunEvents } from '@/features/investigations/useRunEvents'
import { useApiQuery } from '@/hooks/useApiQuery'
import { useFormat } from '@/hooks/useSettings'
import { useActor } from '@/hooks/useActor'
import { useRunAction } from '@/hooks/useRunAction'
import { AnnotationsProvider, OrphanedNotes } from '@/features/investigations/workspace/Annotations'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { readJson, writeJson } from '@/lib/storage'
import type { InvestigationBundle } from '@/types/investigator'

const AGENT_OPEN_KEY = 'investigator.agent.open'

const TABS = [
  { id: 'summary', label: 'Summary' },
  { id: 'findings', label: 'Findings' },
  { id: 'timeline', label: 'Timeline' },
  { id: 'commitments', label: 'Commitments' },
  { id: 'issues', label: 'Gaps & contradictions' },
  { id: 'actions', label: 'Actions' },
  { id: 'sources', label: 'Sources' },
  { id: 'response', label: 'Response' },
] as const

type TabId = (typeof TABS)[number]['id']

/** Which tab holds the record with this element id. */
function tabFor(b: InvestigationBundle, id: string): TabId | undefined {
  if (TABS.some((t) => t.id === id)) return id as TabId
  if (b.findings.some((x) => x.id === id)) return 'findings'
  if (b.timeline.some((x) => x.id === id)) return 'timeline'
  if (b.commitments.some((x) => x.id === id)) return 'commitments'
  if (b.gaps.some((x) => x.id === id) || b.contradictions.some((x) => x.id === id)) return 'issues'
  if (b.actions.some((x) => x.id === id)) return 'actions'
  if (b.blockers.some((x) => x.id === id)) return 'summary'
  return undefined
}

function Header({ b, onChanged }: { b: InvestigationBundle; onChanged: () => void }) {
  const inv = b.investigation
  const fmt = useFormat()
  const actor = useActor()
  const toast = useToast()
  const { run, busy } = useRunAction()
  const [exporting, setExporting] = useState(false)
  const [rerunning, setRerunning] = useState(false)
  const running = inv.status === 'queued' || inv.status === 'investigating'
  const readOnly = inv.sample === true
  const assign = (owner: string | null) =>
    void run(async () => {
      await api.setOwner(inv.id, owner)
      onChanged()
      return true
    }, owner ? `Assigned to ${owner}` : 'Unassigned')
  const directory = useApiQuery(async () => toDirectory(await api.getDirectory()), [])
  const projectName = directory.data?.projects.find((p) => p.id === inv.projectId)?.name
  const customerName = directory.data?.customers.find((c) => c.id === inv.customerId)?.name
  const scope = [
    projectName ?? customerName ?? '',
    inv.ticketIds.length > 0 ? inv.ticketIds.join(', ') : '',
    inv.dateFrom || inv.dateTo ? `${inv.dateFrom ?? 'start'} to ${inv.dateTo ?? 'today'}` : '',
  ].filter(Boolean)

  return (
    <PageHeader
      crumbs={[{ label: 'Investigations', to: '/investigations' }, { label: inv.title }]}
      title={inv.title}
      description={scope.join(' · ') || undefined}
      actions={
        <span data-tour="workspace-actions" className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => setExporting(true)}>
            <Icon name="download" /> Export
          </Button>
          <Button variant="outline" disabled={running || busy || readOnly} title={readOnly ? 'A sample cannot be run again. Start your own investigation.' : running ? 'It is already running' : 'Run it again with the same question and scope'} onClick={() => setRerunning(true)}>
            <Icon name="refresh" /> Run again
          </Button>
          <Dialog
            open={exporting}
            onClose={() => setExporting(false)}
            title="Export this investigation"
            description="A report with every claim tied to numbered evidence, plus notes and reviews. It says it is AI-generated."
            footer={
              <Button variant="outline" onClick={() => setExporting(false)}>
                Close
              </Button>
            }
          >
            <ul className="flex flex-col gap-2">
              {(
                [
                  ['md', 'Markdown', 'For pasting into a ticket, wiki or email.'],
                  ['html', 'Printable page', 'Opens in a new tab. Print it from your browser and choose Save as PDF.'],
                  ['json', 'Raw data', 'The full record, for other tools.'],
                ] as const
              ).map(([format, label, help]) => (
                <li key={format}>
                  <a
                    href={exportUrl(inv.id, format)}
                    target={format === 'html' ? '_blank' : undefined}
                    rel="noreferrer noopener"
                    className="flex flex-col border border-line px-3 py-2 hover:bg-surface-muted"
                  >
                    <span className="text-body font-medium text-ink">{label}</span>
                    <span className="text-caption text-ink-muted">{help}</span>
                  </a>
                </li>
              ))}
            </ul>
          </Dialog>
          <ConfirmDialog
            open={rerunning}
            tone="solid"
            title="Run this investigation again?"
            body="It searches the sources again from the start with the same question and scope. Notes and reviews are kept: they show next to a claim when the new run states it the same way, and are listed on the Summary tab when it does not. The current results are replaced as the new run finishes."
            confirmLabel="Run again"
            busy={busy}
            onCancel={() => setRerunning(false)}
            onConfirm={async () => {
              const ok = await run(async () => {
                await api.rerun(inv.id)
                onChanged()
                return true
              }, 'Running again')
              if (ok) setRerunning(false)
              else toast.error('Could not start another run')
            }}
          />
        </span>
      }
      meta={
        <>
          <div className="flex w-full flex-wrap items-center justify-between gap-x-4 gap-y-2 py-1 text-body">
            <span className="flex flex-wrap items-center gap-2">
              <StatusBadge def={investigationStatus[inv.status]} />
              {readOnly ? <Badge tone="accent">Sample</Badge> : null}
              {inv.awaiting && !readOnly ? <span className="text-caption text-ink-muted">{awaitingLabel[inv.awaiting]}</span> : null}
            </span>
            <span className="flex flex-wrap items-center gap-2">
              <span className="text-ink-muted">Owner</span>
              <span className="text-ink">{inv.owner ?? 'Not assigned'}</span>
              {!readOnly && actor && inv.owner !== actor ? (
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => assign(actor)}>
                  Assign to me
                </Button>
              ) : null}
              {!readOnly && inv.owner ? (
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => assign(null)}>
                  Clear
                </Button>
              ) : null}
            </span>
            <span>
              <span className="text-ink-muted">Created</span> <span className="text-ink">{fmt.short(inv.createdAt)}</span>
            </span>
            <span>
              <span className="text-ink-muted">Updated</span>{' '}
              <span className="text-ink" title={fmt.dateTime(inv.updatedAt)}>
                {fmt.short(inv.updatedAt)}
              </span>
            </span>
          </div>
          {inv.status === 'resolved' ? (
            <p className="text-caption text-ink-muted">
              Resolved{inv.resolvedBy ? ` by ${inv.resolvedBy}` : ''} on {fmt.dateTime(inv.resolvedAt)}.
            </p>
          ) : null}
        </>
      }
    />
  )
}

export function WorkspacePage() {
  const { id = '' } = useParams()
  const query = useApiQuery(
    async () => {
      try {
        return toBundle(await api.getInvestigation(id))
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null
        throw e
      }
    },
    [id],
    // Poll while the run is going, so progress and checkpoints appear without a refresh.
    // The event stream refreshes the page the moment something is saved; polling is the fallback.
    { pollMs: (b) => (b && (b.investigation.status === 'queued' || b.investigation.status === 'investigating') ? 5000 : false) },
  )
  const [params] = useSearchParams()
  const [agentOpen, setAgentOpenState] = useState(() => readJson(AGENT_OPEN_KEY) === true)
  const [agentDrawer, setAgentDrawer] = useState(false)
  const wide = useMediaQuery('(min-width: 1280px)')
  const setAgentOpen = (v: boolean) => {
    setAgentOpenState(v)
    writeJson(AGENT_OPEN_KEY, v)
  }
  const [tab, setTab] = useState<TabId>(() => {
    const t = params.get('tab')
    return TABS.some((x) => x.id === t) ? (t as TabId) : 'summary'
  })

  const bundle = query.data ?? undefined
  useRegisterBundle(bundle)
  const running = bundle?.investigation.status === 'queued' || bundle?.investigation.status === 'investigating'
  const progress = useRunEvents(id, Boolean(running), query.refresh)

  useEffect(() => {
    const onReveal = (e: Event) => {
      const next = bundle ? tabFor(bundle, String((e as CustomEvent<string>).detail)) : undefined
      if (next) setTab(next)
    }
    window.addEventListener(REVEAL_EVENT, onReveal)
    return () => window.removeEventListener(REVEAL_EVENT, onReveal)
  }, [bundle])

  if (query.status === 'loading') return <SkeletonRows rows={8} />
  if (query.status === 'error') return <ErrorState message={query.error} onRetry={query.reload} />
  const b = query.data
  if (!b) {
    return (
      <EmptyState
        icon="alert"
        title="Investigation not found"
        body="No investigation has this ID. It may have been removed, or the link is wrong."
        actions={
          <Link to="/investigations" className="inline-flex h-control-md items-center border border-line bg-surface px-4 hover:bg-surface-muted">
            Back to investigations
          </Link>
        }
      />
    )
  }

  const inv = b.investigation

  const agentRail = wide && agentOpen

  return (
    <div className={agentRail ? 'xl:mr-[28.08rem]' : undefined}>
      <Header b={b} onChanged={query.refresh} />

      {agentRail ? null : (
        <button
          type="button"
          aria-label="Open Investigator Agent"
          title="Investigator Agent"
          aria-expanded={wide ? agentOpen : agentDrawer}
          aria-controls="investigator-agent"
          data-tour="agent"
          onClick={() => (wide ? setAgentOpen(true) : setAgentDrawer(true))}
          className="fixed bottom-6 right-6 z-40 rounded-[999px] transition-transform hover:scale-105"
        >
          <AgentOrb animated className="size-14" />
        </button>
      )}
      <div className="grid items-start gap-8">
        <div className="flex min-w-0 flex-col gap-6">
          {running ? <RunProgress inv={inv} entries={progress.entries} live={!progress.ended} /> : null}

          {!running && inv.status === 'failed' ? (
            <ErrorState
              title="This investigation failed"
              message={`${inv.failureReason ?? 'The run did not complete.'} Evidence collected before the failure is kept below.`}
            />
          ) : null}

          {inv.sample ? (
            <p role="note" className="flex items-start gap-2 border border-line bg-surface-muted px-4 py-3 text-body text-ink">
              <Icon name="info" className="mt-0.5 shrink-0 text-ink-muted" />
              <span>
                This is a shared sample, read-only. You can read it and ask the agent about it. Notes, reviews and re-runs are for investigations you start yourself.{' '}
                <Link to="/investigations/new" className="underline underline-offset-2">
                  Start your own
                </Link>
                .
              </span>
            </p>
          ) : null}

          {inv.awaiting && !inv.sample ? <CheckpointPanel inv={inv} onDone={query.refresh} /> : null}

          {!running ? (
            <>
              <div data-tour="workspace-tabs">
                <Tabs tabs={[...TABS]} value={tab} onChange={setTab} label="Investigation sections" />
              </div>
              <AnnotationsProvider investigationId={inv.id} readOnly={inv.sample === true}>
              <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="flex min-w-0 flex-col gap-6">
                {tab === 'summary' ? (
                  <>
                    <SummarySection b={b} />
                    <OrphanedNotes b={b} />
                  </>
                ) : null}
                {tab === 'findings' ? <FindingsSection findings={b.findings} /> : null}
                {tab === 'timeline' ? <TimelineSection events={b.timeline} findings={b.findings} commitments={b.commitments} /> : null}
                {tab === 'commitments' ? <CommitmentsSection commitments={b.commitments} /> : null}
                {tab === 'issues' ? <IssuesSection gaps={b.gaps} contradictions={b.contradictions} /> : null}
                {tab === 'actions' ? <ActionsSection actions={b.actions} findings={b.findings} /> : null}
                {tab === 'sources' ? <SourcesSection bundle={b} /> : null}
                {tab === 'response' ? <ResponsePanel b={b} /> : null}
              </div>
              </AnnotationsProvider>
            </>
          ) : null}
        </div>
      </div>

      {agentRail ? (
        <div id="investigator-agent" className="fixed inset-y-0 right-0 z-30 w-[28.08rem] border-l border-line shadow-lg">
          <AgentPanel inv={inv} variant="rail" onCollapse={() => setAgentOpen(false)} />
        </div>
      ) : null}

      <Drawer open={agentDrawer && !wide} onClose={() => setAgentDrawer(false)} title="Investigator Agent" width="sm:max-w-[30.24rem]">
        <div id="investigator-agent" className="-mx-5 -my-4 h-[calc(100dvh-5.5rem)]">
          <AgentPanel inv={inv} variant="drawer" />
        </div>
      </Drawer>
    </div>
  )
}
