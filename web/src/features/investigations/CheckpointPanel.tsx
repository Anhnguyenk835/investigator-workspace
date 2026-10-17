import { useState } from 'react'
import { api } from '@/api/client'
import type { ResumeValueDto, ReviewDecisionDto } from '@/api/dto'
import { Button, Checkbox, Icon, Input, Select, Textarea } from '@/components/ui'
import { Field } from '@/components/shared/Field'
import { useToast } from '@/components/ui/Toast'
import { awaitingLabel } from '@/features/investigations/awaiting'
import { useRunAction } from '@/hooks/useRunAction'
import type { Investigation } from '@/types/investigator'

interface ClarificationQuestion {
  key: 'project_id' | 'customer_id' | 'source_scope'
  question: string
  options: string[]
  /** Readable names for the option values, when the directory knows them. */
  labels: Record<string, string>
  /** For source_scope: the source being narrowed, and that several parts may be chosen. */
  source: string
  multi: boolean
}

function asQuestions(pending: Record<string, unknown> | undefined): ClarificationQuestion[] {
  const raw = pending?.questions
  if (!Array.isArray(raw)) return []
  return raw.flatMap((q) => {
    if (typeof q !== 'object' || q === null) return []
    const { key, question, options, labels, source, multi } = q as Record<string, unknown>
    if ((key !== 'project_id' && key !== 'customer_id' && key !== 'source_scope') || typeof question !== 'string' || !Array.isArray(options)) return []
    const names = typeof labels === 'object' && labels !== null ? Object.fromEntries(Object.entries(labels as Record<string, unknown>).map(([k, v]) => [k, String(v)])) : {}
    return [{ key, question, options: options.map(String), labels: names, source: typeof source === 'string' ? source : '', multi: multi === true }]
  })
}

const num = (v: unknown): number => (typeof v === 'number' ? v : 0)

/** The three places the investigation stops and waits for a person. */
export function CheckpointPanel({ inv, onDone }: { inv: Investigation; onDone: () => void }) {
  const toast = useToast()
  const { run, busy } = useRunAction()

  const submit = async (value: ResumeValueDto, message: string) => {
    const ok = await run(async () => {
      await api.resumeInvestigation(inv.id, value)
      return true
    }, message)
    if (ok) onDone()
    else toast.error('Could not continue', 'The investigation is still waiting for you. Try again.')
  }

  const [open, setOpen] = useState(true)
  if (!inv.awaiting) return null
  const bodyId = `checkpoint-${inv.id}`
  return (
    <section aria-label="Your input is needed" className="border border-warning bg-surface">
      <h2 className={open ? 'border-b border-line-subtle' : undefined}>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-center gap-2 px-5 py-3 text-left hover:bg-surface-muted"
        >
          <Icon name="alert" className="text-warning" />
          <span className="flex-1 text-heading text-ink">{awaitingLabel[inv.awaiting]}</span>
          <span className="text-caption text-ink-muted">{open ? 'Collapse' : 'Expand'}</span>
          <Icon name={open ? 'chevronUp' : 'chevronDown'} className="text-ink-muted" />
        </button>
      </h2>
      <div id={bodyId} hidden={!open} className="px-5 py-4">
        {inv.awaiting === 'clarification' ? <Clarification inv={inv} busy={busy} onSubmit={submit} /> : null}
        {inv.awaiting === 'review' ? <Review inv={inv} busy={busy} onSubmit={submit} /> : null}
        {inv.awaiting === 'draft_approval' ? <DraftApproval inv={inv} busy={busy} onSubmit={submit} /> : null}
      </div>
    </section>
  )
}

interface PanelProps {
  inv: Investigation
  busy: boolean
  onSubmit: (value: ResumeValueDto, message: string) => Promise<void>
}

const SOURCE_NAME: Record<string, string> = { slack: 'Slack', jira: 'Jira', gmail: 'Gmail', confluence: 'Confluence' }

/** What was chosen in one source: everything, or these parts. */
type ScopeAnswer = { all: boolean; picked: string[] }

function Clarification({ inv, busy, onSubmit }: PanelProps) {
  const questions = asQuestions(inv.pending)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [scope, setScope] = useState<Record<string, ScopeAnswer>>({})
  const [find, setFind] = useState<Record<string, string>>({})
  const single = questions.filter((q) => q.key !== 'source_scope')
  const scoped = questions.filter((q) => q.key === 'source_scope')
  const done = (q: ClarificationQuestion) => (q.key === 'source_scope' ? Boolean(scope[q.source]?.all || scope[q.source]?.picked.length) : Boolean(answers[q.key]))
  const complete = questions.length > 0 && questions.every(done)
  const set = (source: string, next: ScopeAnswer) => setScope((s) => ({ ...s, [source]: next }))

  return (
    <form
      className="flex flex-col gap-5"
      onSubmit={(e) => {
        e.preventDefault()
        void onSubmit(
          {
            project_id: answers.project_id,
            customer_id: answers.customer_id,
            scope: Object.fromEntries(Object.entries(scope).map(([source, a]) => [source, a.all ? [] : a.picked])),
          },
          'Continuing the investigation',
        )
      }}
    >
      <p className="max-w-prose text-body text-ink">
        {scoped.length > 0
          ? 'Say where to look before anything is read. Searching a whole account is slower, costs more, and reads more than this case needs. Choose the parts that matter, or search all of a source on purpose.'
          : 'The records found belong to more than one case. Pick the one you mean; the search then restarts for that case only.'}
      </p>
      {single.map((q) => (
        <Field key={q.key} label={q.question}>
          <Select value={answers[q.key] ?? ''} onChange={(e) => setAnswers((a) => ({ ...a, [q.key]: e.target.value }))}>
            <option value="" disabled>
              Choose one
            </option>
            {q.options.map((o) => (
              <option key={o} value={o}>
                {q.labels[o] ?? o}
              </option>
            ))}
          </Select>
        </Field>
      ))}
      {scoped.map((q) => {
        const a = scope[q.source] ?? { all: false, picked: [] }
        const term = (find[q.source] ?? '').trim().toLowerCase()
        const shown = q.options.filter((o) => !term || (q.labels[o] ?? o).toLowerCase().includes(term))
        const name = SOURCE_NAME[q.source] ?? q.source
        return (
          <fieldset key={q.source} className="flex flex-col gap-2 border border-line p-4">
            <legend className="px-1 text-body font-medium text-ink">{q.question}</legend>
            <Checkbox
              label={`Search all of ${name}`}
              description="Reads every part this account can see. Use it when the case really spans them."
              checked={a.all}
              onChange={(e) => set(q.source, { all: e.target.checked, picked: e.target.checked ? [] : a.picked })}
            />
            {a.all ? null : (
              <>
                {q.options.length > 8 ? <Input aria-label={`Find in ${name}`} placeholder={`Find in ${name}...`} value={find[q.source] ?? ''} onChange={(e) => setFind((f) => ({ ...f, [q.source]: e.target.value }))} /> : null}
                <div className="flex max-h-56 flex-col gap-2 overflow-y-auto pr-1">
                  {shown.length === 0 ? <p className="text-caption text-ink-muted">Nothing matches.</p> : null}
                  {shown.map((o) => (
                    <Checkbox
                      key={o}
                      label={q.labels[o] ?? o}
                      checked={a.picked.includes(o)}
                      onChange={(e) => set(q.source, { all: false, picked: e.target.checked ? [...a.picked, o] : a.picked.filter((x) => x !== o) })}
                    />
                  ))}
                </div>
                <p className="text-caption text-ink-muted">{a.picked.length > 0 ? `${a.picked.length} selected` : 'Choose at least one, or search all.'}</p>
              </>
            )}
          </fieldset>
        )
      })}
      <div>
        <Button type="submit" disabled={busy || !complete}>
          Continue investigation
        </Button>
      </div>
    </form>
  )
}

const DECISIONS: { id: ReviewDecisionDto; label: string; help: string; noteRequired: boolean }[] = [
  { id: 'approved', label: 'Approve the findings', help: 'A customer draft is written from the verified findings.', noteRequired: false },
  { id: 'needs_more_evidence', label: 'Search for more evidence', help: 'Tell the investigation what to look for. It searches again with your note.', noteRequired: true },
  { id: 'revise', label: 'Revise the findings', help: 'Tell the investigation what to change. It rewrites the findings from the same evidence.', noteRequired: true },
]

function Review({ inv, busy, onSubmit }: PanelProps) {
  const [decision, setDecision] = useState<ReviewDecisionDto>('approved')
  const [note, setNote] = useState('')
  const chosen = DECISIONS.find((d) => d.id === decision) ?? DECISIONS[0]!
  const p = inv.pending ?? {}
  const flagged = p.validation_passed === false

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(e) => {
        e.preventDefault()
        void onSubmit({ decision, note: note.trim() }, 'Review submitted')
      }}
    >
      <div className="flex flex-col gap-2">
        <p className="text-body text-ink">Check the findings against their evidence before deciding.</p>
        <dl className="flex flex-wrap gap-x-6 gap-y-1">
          {[
            ['Findings', num(p.findings)],
            ['Contradictions', num(p.conflicts)],
            ['Gaps', num(p.gaps)],
            ['Suggested actions', num(p.actions)],
          ].map(([label, n]) => (
            <div key={label} className="flex items-baseline gap-1.5">
              <dd className="order-first text-body font-medium tabular-nums text-ink">{n}</dd>
              <dt className="text-caption text-ink-muted">{label}</dt>
            </div>
          ))}
        </dl>
      </div>
      {flagged ? <p className="text-caption text-warning">Some quality checks are still flagged. See the summary tab before approving.</p> : null}
      <fieldset className="flex flex-col gap-1.5">
        <legend className="mb-1 text-caption font-medium text-ink">Your decision</legend>
        {DECISIONS.map((d) => (
          <label key={d.id} className="flex cursor-pointer items-start gap-3 border border-line-subtle px-3 py-2 hover:bg-surface-muted has-[:checked]:border-primary/60 has-[:checked]:bg-primary/5">
            <input type="radio" name="decision" className="mt-1 size-4 accent-primary" checked={decision === d.id} onChange={() => setDecision(d.id)} />
            <span>
              <span className="block text-body text-ink">{d.label}</span>
              <span className="block text-caption text-ink-muted">{d.help}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <Field label={chosen.noteRequired ? 'Note' : 'Note (optional)'} required={chosen.noteRequired}>
        <Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <div>
        <Button type="submit" disabled={busy || (chosen.noteRequired && !note.trim())}>
          Submit review
        </Button>
      </div>
    </form>
  )
}

function DraftApproval({ inv, busy, onSubmit }: PanelProps) {
  const original = typeof inv.pending?.draft === 'string' ? inv.pending.draft : ''
  const warnings = Array.isArray(inv.pending?.warnings) ? inv.pending.warnings.map(String) : []
  const [text, setText] = useState(original)
  const [note, setNote] = useState('')
  const [asking, setAsking] = useState(false)

  return (
    <div className="flex flex-col gap-4">
      <p className="text-body text-ink">Read and edit the customer update. Approving records your sign-off and closes the investigation.</p>
      {warnings.length > 0 ? (
        <div role="status" className="border border-warning/50 bg-warning/10 p-3">
          <p className="text-caption font-medium text-ink">The checks flagged this draft</p>
          <ul className="mt-1 flex list-disc flex-col gap-1 pl-5 text-caption text-ink">
            {warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <Field label="Customer update">
        <Textarea rows={10} value={text} onChange={(e) => setText(e.target.value)} />
      </Field>
      {asking ? (
        <Field label="What should change?" required>
          <Textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} autoFocus />
        </Field>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button
          disabled={busy || !text.trim() || asking}
          onClick={() => void onSubmit({ approved: true, draft: text !== original ? text : undefined }, 'Draft approved')}
        >
          <Icon name="check" /> Approve draft
        </Button>
        {asking ? (
          <>
            <Button variant="outline" disabled={busy || !note.trim()} onClick={() => void onSubmit({ approved: false, note: note.trim() }, 'Changes requested')}>
              Send request
            </Button>
            <Button variant="ghost" disabled={busy} onClick={() => setAsking(false)}>
              Cancel
            </Button>
          </>
        ) : (
          <Button variant="outline" disabled={busy} onClick={() => setAsking(true)}>
            Request changes
          </Button>
        )}
      </div>
    </div>
  )
}
