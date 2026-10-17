import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import { toConnectors, toDirectory } from '@/api/adapt'
import { Button, Card, CardBody, CardHeader, Checkbox, ErrorState, Input, Select, SkeletonRows, Textarea } from '@/components/ui'
import { Field } from '@/components/shared/Field'
import { PageHeader } from '@/components/shared/PageHeader'
import { ProviderMark } from '@/components/shared/ProviderMark'
import { StatusBadge, connectorStatus } from '@/components/shared/StatusBadge'
import { useToast } from '@/components/ui/Toast'
import { useApiQuery } from '@/hooks/useApiQuery'
import { providerMeta, supportedProviders } from '@/lib/providers'
import type { SourceProvider } from '@/types/investigator'

const TICKET_PATTERN = /^[A-Za-z][A-Za-z0-9_]+-\d+$/

/** Optional context goes into the question so the planner can use it as search hints. */
function questionWithHints(problem: string, customer: string, project: string, people: string): string {
  const hints = [
    customer.trim() && `Customer: ${customer.trim()}`,
    project.trim() && `Project: ${project.trim()}`,
    people.trim() && `People involved: ${people.trim()}`,
  ].filter(Boolean)
  return hints.length > 0 ? `${problem.trim()}\n\n${hints.join('\n')}` : problem.trim()
}

export function NewInvestigationPage() {
  const connectors = useApiQuery(async () => toConnectors(await api.listIntegrations()), [])
  const directory = useApiQuery(async () => toDirectory(await api.getDirectory()), [])
  const navigate = useNavigate()
  const toast = useToast()

  const [name, setName] = useState('')
  const [problem, setProblem] = useState('')
  const [customer, setCustomer] = useState('')
  const [project, setProject] = useState('')
  const [customerId, setCustomerId] = useState('')
  const [projectId, setProjectId] = useState('')
  const [ticket, setTicket] = useState('')
  const [people, setPeople] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  // Sources the person switched off; everything connected is on by default.
  const [off, setOff] = useState<Set<SourceProvider>>(new Set())
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState<string | undefined>()

  const dir = directory.data
  const useDirectory = Boolean(dir && (dir.customers.length > 0 || dir.projects.length > 0))
  const projectsOfCustomer = (dir?.projects ?? []).filter((p) => !customerId || p.customerId === customerId)
  const list = connectors.data ?? []
  const selectable = list.filter((c) => c.status === 'connected').map((c) => c.provider)
  const chosen = selectable.filter((p) => !off.has(p))
  const allChecked = selectable.length > 0 && chosen.length === selectable.length

  const toggle = (p: SourceProvider) =>
    setOff((cur) => {
      const next = new Set(cur)
      if (next.has(p)) next.delete(p)
      else next.add(p)
      return next
    })

  const validate = (): boolean => {
    const e: Record<string, string> = {}
    if (!name.trim()) e.name = 'Give the investigation a short name so you can find it later.'
    else if (name.trim().length > 120) e.name = 'Keep the name under 120 characters.'
    if (!problem.trim()) e.problem = 'Describe what happened so the investigation knows what to look for.'
    if (ticket.trim() && !TICKET_PATTERN.test(ticket.trim())) e.ticket = 'Ticket IDs look like IMPL-482. Fix it or leave this field empty.'
    if (from && to && from > to) e.range = 'The start date must be on or before the end date.'
    if (chosen.length === 0) e.sources = 'Connect and select at least one source to search.'
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const onSubmit = async (ev: FormEvent) => {
    ev.preventDefault()
    if (busy) return
    setFormError(undefined)
    if (!validate()) return
    setBusy(true)
    try {
      const inv = await api.createInvestigation({
        name: name.trim(),
        question: questionWithHints(problem, useDirectory ? '' : customer, useDirectory ? '' : project, people),
        customer_id: useDirectory && customerId ? customerId : undefined,
        project_id: useDirectory && projectId ? projectId : undefined,
        ticket_ids: ticket.trim() ? [ticket.trim().toUpperCase()] : undefined,
        date_from: from || undefined,
        date_to: to || undefined,
        // Only narrow when the person switched something off.
        sources: chosen.length === selectable.length ? undefined : chosen,
      })
      toast.success('Investigation started', 'It runs in the background; this page updates as it progresses.')
      navigate(`/investigations/${inv.id}`)
    } catch (e) {
      setFormError(e instanceof Error ? e.message : 'The investigation could not be created. Your input was kept.')
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto w-full max-w-4xl">
      <PageHeader
        crumbs={[{ label: 'Investigations', to: '/investigations' }, { label: 'New investigation' }]}
        title="New investigation"
        description="Describe the reported escalation"
      />

      <form onSubmit={onSubmit} noValidate className="grid gap-6">
        {formError ? <ErrorState title="Could not start the investigation" message={formError} /> : null}

        <Card>
          <CardHeader>
            <h2 className="text-body font-medium">The escalation</h2>
          </CardHeader>
          <CardBody className="flex flex-col gap-5">
            <Field label="Name" required error={errors.name}>
              <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
            </Field>
            <Field label="Escalation / issue" required error={errors.problem}>
              <Textarea
                rows={5}
                value={problem}
                onChange={(e) => setProblem(e.target.value)}
                placeholder="Describe the customer's issue, what they expected, and what needs to be clarified..."
              />
            </Field>
            <div className="grid gap-5 sm:grid-cols-2">
              {useDirectory ? (
                <>
                  <Field label="Customer">
                    <Select
                      value={customerId}
                      onChange={(e) => {
                        setCustomerId(e.target.value)
                        setProjectId('')
                      }}
                    >
                      <option value="">Any customer</option>
                      {dir?.customers.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Project">
                    <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
                      <option value="">Any project</option>
                      {projectsOfCustomer.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </Select>
                  </Field>
                </>
              ) : (
                <>
                  <Field label="Customer / account">
                    <Input value={customer} onChange={(e) => setCustomer(e.target.value)} />
                  </Field>
                  <Field label="Project">
                    <Input value={project} onChange={(e) => setProject(e.target.value)} />
                  </Field>
                </>
              )}
              <Field label="Existing ticket ID" error={errors.ticket}>
                <Input value={ticket} onChange={(e) => setTicket(e.target.value)} />
              </Field>
              <Field label="People involved">
                <Input value={people} onChange={(e) => setPeople(e.target.value)} />
              </Field>
              <Field label="From" error={errors.range}>
                <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
              </Field>
              <Field label="To">
                <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
              </Field>
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <h2 className="text-body font-medium">Sources to search</h2>
          </CardHeader>
          <CardBody className="flex flex-col gap-4">
            {connectors.status === 'loading' ? <SkeletonRows rows={4} /> : null}
            {connectors.status === 'error' ? <ErrorState message={connectors.error} onRetry={connectors.reload} /> : null}
            {connectors.status === 'success' && selectable.length === 0 ? (
              <div className="flex flex-col gap-3 border border-warning/50 bg-warning/10 p-4">
                <p className="text-body text-ink">No sources are connected, so there is nothing to search. Connect at least one source first.</p>
                <div>
                  <Link to="/settings/connectors" className="inline-flex h-control-md items-center border border-line bg-surface px-4 hover:bg-surface-muted">
                    Connect a source
                  </Link>
                </div>
              </div>
            ) : null}
            {connectors.status === 'success' && selectable.length > 0 ? (
              <Checkbox
                label="Search all connected sources"
                checked={allChecked}
                onChange={() => setOff(allChecked ? new Set(selectable) : new Set())}
              />
            ) : null}
            {errors.sources && selectable.length > 0 ? <p className="text-caption text-danger">{errors.sources}</p> : null}
            {connectors.status === 'success' ? (
              <ul className="grid gap-2 sm:grid-cols-2">
                {supportedProviders.map((p) => {
                  const c = list.find((x) => x.provider === p)
                  const ok = c?.status === 'connected'
                  return (
                    <li key={p} className="flex items-center justify-between gap-3 border border-line-subtle px-3 py-2">
                      <div className="flex min-w-0 items-center gap-2">
                        <ProviderMark provider={p} />
                        <Checkbox label={providerMeta[p].name} checked={ok && !off.has(p)} disabled={!ok} onChange={() => toggle(p)} />
                      </div>
                      {c ? <StatusBadge def={connectorStatus[c.status]} /> : null}
                    </li>
                  )
                })}
              </ul>
            ) : null}
            <p className="text-caption text-ink-muted">Sources are read with your own permissions. A source that is not connected is skipped and shown as not searched.</p>
          </CardBody>
        </Card>

        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => navigate('/investigations')} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy || (connectors.status === 'success' && selectable.length === 0)} aria-busy={busy}>
            {busy ? 'Starting…' : 'Start investigation'}
          </Button>
        </div>
      </form>
    </div>
  )
}
