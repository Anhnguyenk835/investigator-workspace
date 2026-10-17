import { useState } from 'react'
import { api } from '@/api/client'
import type { CustomerDto, PersonDto, ProjectDto } from '@/api/dto'
import { toDirectory } from '@/api/adapt'
import { Badge, Button, ConfirmDialog, Dialog, EmptyState, ErrorState, Icon, Input, Select, SkeletonRows, Table, TableWrap, Tabs, Td, Th } from '@/components/ui'
import { Field } from '@/components/shared/Field'
import { PageHeader } from '@/components/shared/PageHeader'
import { useAuth } from '@/features/auth/AuthProvider'
import { ListField, fromList, toList } from '@/features/directory/ListField'
import { useApiQuery } from '@/hooks/useApiQuery'
import { useRunAction } from '@/hooks/useRunAction'
import type { Customer, DirectoryData, Person, Project, Side } from '@/types/directory'

const TABS = [
  { id: 'customers', label: 'Customers' },
  { id: 'projects', label: 'Projects' },
  { id: 'people', label: 'People' },
] as const
type TabId = (typeof TABS)[number]['id']

const SIDE_LABEL: Record<Side, string> = { customer: 'Customer side', internal: 'Our team', third_party: 'Other party' }

type Editing = { kind: TabId; entry?: Customer | Project | Person } | undefined

export function DirectoryPage() {
  const { isDemo } = useAuth()
  const query = useApiQuery(async () => toDirectory(await api.getDirectory()), [])
  const [tab, setTab] = useState<TabId>('customers')
  const [editing, setEditing] = useState<Editing>()
  const [deleting, setDeleting] = useState<{ kind: TabId; id: string; name: string }>()
  const { run, busy } = useRunAction()
  const data = query.data

  const remove = async () => {
    if (!deleting) return
    const done = await run(async () => {
      await api.deleteDirectoryEntry(deleting.kind, deleting.id)
      return true
    }, 'Removed')
    if (done) {
      setDeleting(undefined)
      query.refresh()
    }
  }

  return (
    <>
      <PageHeader
        title="Directory"
        description="Who your customers, projects and people are, and where each one lives in Slack, Jira, Gmail and Confluence. Investigations use it to stay inside one customer and to tell the customer's words from your team's."
        actions={
          isDemo ? undefined : (
            <Button onClick={() => setEditing({ kind: tab })}>
              <Icon name="plus" /> Add {tab === 'customers' ? 'customer' : tab === 'projects' ? 'project' : 'person'}
            </Button>
          )
        }
      />
      {isDemo ? (
        <p role="note" className="mb-4 flex items-start gap-2 border border-line bg-surface-muted px-4 py-3 text-body text-ink">
          <Icon name="info" className="mt-0.5 shrink-0 text-ink-muted" />
          <span>This directory belongs to the demo data and cannot be edited. Sign in with Google to keep your own.</span>
        </p>
      ) : null}
      {query.status === 'loading' ? <SkeletonRows rows={5} /> : null}
      {query.status === 'error' ? <ErrorState message={query.error} onRetry={query.reload} /> : null}
      {data ? (
        <div className="flex flex-col gap-4">
          <Tabs tabs={[...TABS]} value={tab} onChange={setTab} label="Directory sections" />
          {tab === 'customers' ? <Customers data={data} onEdit={(e) => setEditing({ kind: 'customers', entry: e })} onDelete={(e) => setDeleting({ kind: 'customers', id: e.id, name: e.name })} /> : null}
          {tab === 'projects' ? <Projects data={data} onEdit={(e) => setEditing({ kind: 'projects', entry: e })} onDelete={(e) => setDeleting({ kind: 'projects', id: e.id, name: e.name })} /> : null}
          {tab === 'people' ? <People data={data} onEdit={(e) => setEditing({ kind: 'people', entry: e })} onDelete={(e) => setDeleting({ kind: 'people', id: e.id, name: e.name })} /> : null}
        </div>
      ) : null}

      {editing && data ? (
        <EntryDialog
          editing={editing}
          data={data}
          onClose={() => setEditing(undefined)}
          onSaved={() => {
            setEditing(undefined)
            query.refresh()
          }}
        />
      ) : null}
      <ConfirmDialog
        open={Boolean(deleting)}
        title={`Remove ${deleting?.name ?? ''}?`}
        body="Investigations already run keep the records they collected. New investigations will no longer use this entry."
        confirmLabel="Remove"
        busy={busy}
        onCancel={() => setDeleting(undefined)}
        onConfirm={() => void remove()}
      />
    </>
  )
}

function Row({ onEdit, onDelete, children }: { onEdit: () => void; onDelete: () => void; children: React.ReactNode }) {
  const { isDemo } = useAuth()
  return (
    <tr>
      {children}
      <Td className="whitespace-nowrap text-right">
        {isDemo ? null : (
          <>
            <Button size="sm" variant="ghost" onClick={onEdit}>
              Edit
            </Button>
            <Button size="sm" variant="ghost" onClick={onDelete}>
              Remove
            </Button>
          </>
        )}
      </Td>
    </tr>
  )
}

const dash = <span className="text-ink-muted">—</span>
const list = (items: string[]) => (items.length > 0 ? items.join(', ') : dash)

function Customers({ data, onEdit, onDelete }: { data: DirectoryData; onEdit: (c: Customer) => void; onDelete: (c: Customer) => void }) {
  if (data.customers.length === 0) {
    return <EmptyState icon="user" title="No customers yet" body="Add a customer with the names it goes by and its email domains. Mail to or from those domains is then recognised as theirs." />
  }
  return (
    <TableWrap>
      <Table>
        <caption className="sr-only">Customers</caption>
        <thead>
          <tr>
            <Th>Customer</Th>
            <Th>Also called</Th>
            <Th>Email domains</Th>
            <Th>Projects</Th>
            <Th />
          </tr>
        </thead>
        <tbody>
          {data.customers.map((c) => (
            <Row key={c.id} onEdit={() => onEdit(c)} onDelete={() => onDelete(c)}>
              <Td className="font-medium">{c.name}</Td>
              <Td>{list(c.aliases)}</Td>
              <Td>{list(c.emailDomains)}</Td>
              <Td>{data.projects.filter((p) => p.customerId === c.id).length}</Td>
            </Row>
          ))}
        </tbody>
      </Table>
    </TableWrap>
  )
}

function Projects({ data, onEdit, onDelete }: { data: DirectoryData; onEdit: (p: Project) => void; onDelete: (p: Project) => void }) {
  if (data.projects.length === 0) {
    return <EmptyState icon="investigations" title="No projects yet" body="A project says which Slack channels, Jira projects, Gmail labels and Confluence spaces belong together. A case limited to it reads only those." />
  }
  const owner = (p: Project) => data.customers.find((c) => c.id === p.customerId)?.name
  return (
    <TableWrap>
      <Table>
        <caption className="sr-only">Projects</caption>
        <thead>
          <tr>
            <Th>Project</Th>
            <Th>Customer</Th>
            <Th>Slack</Th>
            <Th>Jira</Th>
            <Th>Gmail</Th>
            <Th>Confluence</Th>
            <Th />
          </tr>
        </thead>
        <tbody>
          {data.projects.map((p) => (
            <Row key={p.id} onEdit={() => onEdit(p)} onDelete={() => onDelete(p)}>
              <Td className="font-medium">{p.name}</Td>
              <Td>{owner(p) ?? dash}</Td>
              <Td>{p.slackChannelIds.length > 0 ? `${p.slackChannelIds.length} channel${p.slackChannelIds.length === 1 ? '' : 's'}` : dash}</Td>
              <Td>{list([...p.jiraProjects, ...p.jiraLabels.map((l) => `label:${l}`)])}</Td>
              <Td>{list(p.gmailLabels)}</Td>
              <Td>{list(p.confluenceSpaces)}</Td>
            </Row>
          ))}
        </tbody>
      </Table>
    </TableWrap>
  )
}

function People({ data, onEdit, onDelete }: { data: DirectoryData; onEdit: (p: Person) => void; onDelete: (p: Person) => void }) {
  if (data.people.length === 0) {
    return <EmptyState icon="user" title="No people yet" body="Add the people who appear in your sources, with an email, Slack id or Jira account. Records then show whether the author is on the customer's side or on yours." />
  }
  return (
    <TableWrap>
      <Table>
        <caption className="sr-only">People</caption>
        <thead>
          <tr>
            <Th>Person</Th>
            <Th>Side</Th>
            <Th>Role</Th>
            <Th>Known as</Th>
            <Th />
          </tr>
        </thead>
        <tbody>
          {data.people.map((p) => (
            <Row key={p.id} onEdit={() => onEdit(p)} onDelete={() => onDelete(p)}>
              <Td className="font-medium">{p.name}</Td>
              <Td>
                <Badge tone={p.side === 'customer' ? 'infoSoft' : p.side === 'internal' ? 'successSoft' : 'muted'}>{SIDE_LABEL[p.side]}</Badge>
              </Td>
              <Td>{p.role ?? dash}</Td>
              <Td>{list([...p.emails, ...p.slackIds, ...p.jiraAccountIds])}</Td>
            </Row>
          ))}
        </tbody>
      </Table>
    </TableWrap>
  )
}

function EntryDialog({ editing, data, onClose, onSaved }: { editing: NonNullable<Editing>; data: DirectoryData; onClose: () => void; onSaved: () => void }) {
  const { run, busy } = useRunAction()
  const e = editing.entry
  const c = e as Customer | undefined
  const p = e as Project | undefined
  const q = e as Person | undefined
  const [name, setName] = useState(e?.name ?? '')
  const [aliases, setAliases] = useState(fromList(e?.aliases ?? []))
  const [domains, setDomains] = useState(fromList(c?.emailDomains ?? []))
  const [customerId, setCustomerId] = useState((p?.customerId ?? q?.customerId) ?? '')
  const [prefixes, setPrefixes] = useState(fromList(p?.ticketPrefixes ?? []))
  const [jiraProjects, setJiraProjects] = useState(fromList(p?.jiraProjects ?? []))
  const [jiraLabels, setJiraLabels] = useState(fromList(p?.jiraLabels ?? []))
  const [channels, setChannels] = useState(fromList(p?.slackChannelIds ?? []))
  const [labels, setLabels] = useState(fromList(p?.gmailLabels ?? []))
  const [spaces, setSpaces] = useState(fromList(p?.confluenceSpaces ?? []))
  const [emails, setEmails] = useState(fromList(q?.emails ?? []))
  const [slackIds, setSlackIds] = useState(fromList(q?.slackIds ?? []))
  const [jiraIds, setJiraIds] = useState(fromList(q?.jiraAccountIds ?? []))
  const [side, setSide] = useState<Side>(q?.side ?? 'third_party')
  const [role, setRole] = useState(q?.role ?? '')
  const [error, setError] = useState<string>()

  const noun = editing.kind === 'customers' ? 'customer' : editing.kind === 'projects' ? 'project' : 'person'

  const save = async () => {
    if (!name.trim()) return setError('Give it a name.')
    setError(undefined)
    const base = { name: name.trim(), aliases: toList(aliases) }
    const done = await run(async () => {
      if (editing.kind === 'customers') {
        await api.saveDirectoryEntry<CustomerDto>('customers', { ...base, email_domains: toList(domains) }, e?.id)
      } else if (editing.kind === 'projects') {
        await api.saveDirectoryEntry<ProjectDto>(
          'projects',
          {
            ...base,
            customer_id: customerId || null,
            ticket_prefixes: toList(prefixes),
            jira_projects: toList(jiraProjects),
            jira_labels: toList(jiraLabels),
            slack_channel_ids: toList(channels),
            gmail_labels: toList(labels),
            confluence_spaces: toList(spaces),
          },
          e?.id,
        )
      } else {
        await api.saveDirectoryEntry<PersonDto>(
          'people',
          { ...base, emails: toList(emails), slack_ids: toList(slackIds), jira_account_ids: toList(jiraIds), side, role: role.trim() || null, customer_id: customerId || null },
          e?.id,
        )
      }
      return true
    }, 'Saved')
    if (done) onSaved()
  }

  const customerSelect = (
    <Field label="Customer">
      <Select value={customerId} onChange={(ev) => setCustomerId(ev.target.value)}>
        <option value="">None</option>
        {data.customers.map((x) => (
          <option key={x.id} value={x.id}>
            {x.name}
          </option>
        ))}
      </Select>
    </Field>
  )

  return (
    <Dialog
      open
      onClose={onClose}
      title={`${e ? 'Edit' : 'Add'} ${noun}`}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void save()} disabled={busy}>
            Save
          </Button>
        </>
      }
    >
      <div className="flex max-h-[65vh] flex-col gap-4 overflow-y-auto pr-1">
        <Field label="Name" required error={error}>
          <Input value={name} onChange={(ev) => setName(ev.target.value)} data-autofocus />
        </Field>
        <Field label="Also called" hint="Other names used in messages, separated by commas. The question is matched against them.">
          <Input value={aliases} onChange={(ev) => setAliases(ev.target.value)} />
        </Field>
        {editing.kind === 'customers' ? (
          <Field label="Email domains" hint="For example acme.com. Mail to or from these domains is treated as theirs.">
            <Input value={domains} onChange={(ev) => setDomains(ev.target.value)} />
          </Field>
        ) : null}
        {editing.kind === 'projects' ? (
          <>
            {customerSelect}
            <Field label="Ticket prefixes" hint="For example HPF- . A ticket id in the question then names this project.">
              <Input value={prefixes} onChange={(ev) => setPrefixes(ev.target.value)} />
            </Field>
            <ListField label="Slack channel ids" hint="Only these channels are read for this project." value={channels} onChange={setChannels} source="slack" />
            <ListField label="Jira projects" hint="Project keys, for example HPF." value={jiraProjects} onChange={setJiraProjects} source="jira" />
            <Field label="Jira labels" hint="Optional: only issues carrying one of these labels.">
              <Input value={jiraLabels} onChange={(ev) => setJiraLabels(ev.target.value)} />
            </Field>
            <ListField label="Gmail labels" hint="Mail with one of these labels (or to or from the customer's domains) is read." value={labels} onChange={setLabels} source="gmail" />
            <ListField label="Confluence spaces" value={spaces} onChange={setSpaces} source="confluence" />
          </>
        ) : null}
        {editing.kind === 'people' ? (
          <>
            <Field label="Side">
              <Select value={side} onChange={(ev) => setSide(ev.target.value as Side)}>
                <option value="customer">Customer side</option>
                <option value="internal">Our team</option>
                <option value="third_party">Other party (counsel, administrator…)</option>
              </Select>
            </Field>
            <Field label="Role" hint="For example CSM, counsel, investor.">
              <Input value={role} onChange={(ev) => setRole(ev.target.value)} />
            </Field>
            {customerSelect}
            <Field label="Email addresses">
              <Input value={emails} onChange={(ev) => setEmails(ev.target.value)} />
            </Field>
            <Field label="Slack user ids" hint="For example U01ABC234.">
              <Input value={slackIds} onChange={(ev) => setSlackIds(ev.target.value)} />
            </Field>
            <Field label="Jira account ids">
              <Input value={jiraIds} onChange={(ev) => setJiraIds(ev.target.value)} />
            </Field>
          </>
        ) : null}
      </div>
    </Dialog>
  )
}
