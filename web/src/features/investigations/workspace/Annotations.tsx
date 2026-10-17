import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api } from '@/api/client'
import { toAnnotation } from '@/api/adapt'
import { Badge, Button, Icon, Textarea } from '@/components/ui'
import { useApiQuery } from '@/hooks/useApiQuery'
import { useActor } from '@/hooks/useActor'
import { useFormat } from '@/hooks/useSettings'
import { useRunAction } from '@/hooks/useRunAction'
import type { Annotation, AnnotationKind, InvestigationBundle } from '@/types/investigator'

interface Value {
  items: Annotation[]
  add: (targetId: string, kind: AnnotationKind, text: string) => Promise<boolean>
  remove: (id: string) => Promise<boolean>
  /** Notes can be read but not added (a shared sample). */
  readOnly: boolean
}

const Ctx = createContext<Value | null>(null)

/** Notes and reviews of one investigation, kept with the claims they are about. */
export function AnnotationsProvider({ investigationId, readOnly = false, children }: { investigationId: string; readOnly?: boolean; children: ReactNode }) {
  const query = useApiQuery(async () => (await api.listAnnotations(investigationId)).map(toAnnotation), [investigationId])
  const { refresh } = query
  const add = useCallback(
    async (targetId: string, kind: AnnotationKind, text: string) => {
      await api.addAnnotation(investigationId, { target_id: targetId, kind, text })
      refresh()
      return true
    },
    [investigationId, refresh],
  )
  const remove = useCallback(
    async (id: string) => {
      await api.deleteAnnotation(investigationId, id)
      refresh()
      return true
    },
    [investigationId, refresh],
  )
  const value = useMemo(() => ({ items: query.data ?? [], add, remove, readOnly }), [query.data, add, remove, readOnly])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

const LABEL: Record<AnnotationKind, string> = { note: 'Note', reviewed: 'Reviewed', disputed: 'Disputed' }

/** What people said about one claim, and the means to add to it. */
export function ReviewBar({ targetId }: { targetId: string }) {
  const ctx = useContext(Ctx)
  const fmt = useFormat()
  const actor = useActor()
  const { run, busy } = useRunAction()
  const [writing, setWriting] = useState<AnnotationKind | undefined>(undefined)
  const [text, setText] = useState('')
  if (!ctx) return null
  const mine = ctx.items.filter((a) => a.targetId === targetId)
  if (ctx.readOnly && mine.length === 0) return null

  const submit = async (kind: AnnotationKind, body: string) => {
    const ok = await run(() => ctx.add(targetId, kind, body.trim()), kind === 'note' ? 'Note added' : kind === 'reviewed' ? 'Marked as reviewed' : 'Marked as disputed')
    if (ok) {
      setWriting(undefined)
      setText('')
    }
  }

  return (
    <div className="mt-3 flex flex-col gap-2 border-t border-line-subtle pt-3">
      {mine.length > 0 ? (
        <ul className="flex flex-col gap-1.5" aria-label="Reviews and notes">
          {mine.map((a) => (
            <li key={a.id} className="flex flex-wrap items-start gap-2 border-l-2 border-primary/50 bg-surface-muted px-3 py-1.5 text-caption text-ink">
              <Badge tone={a.kind === 'reviewed' ? 'successSoft' : a.kind === 'disputed' ? 'dangerSoft' : 'muted'}>{LABEL[a.kind]}</Badge>
              <span className="min-w-0 flex-1">
                {a.text ? <span className="block whitespace-pre-wrap">{a.text}</span> : null}
                <span className="text-ink-muted">
                  {a.author} · {fmt.date(a.createdAt)}
                </span>
              </span>
              {!ctx.readOnly && a.author === (actor || 'Someone') ? (
                <button type="button" aria-label="Delete this" title="Delete" className="text-ink-muted hover:text-danger" onClick={() => void run(() => ctx.remove(a.id), 'Removed')}>
                  <Icon name="trash" className="size-3.5" />
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {ctx.readOnly ? null : writing ? (
        <div className="flex flex-col gap-2">
          <Textarea aria-label={writing === 'note' ? 'Note' : 'Why you dispute this'} rows={2} value={text} onChange={(e) => setText(e.target.value)} autoFocus />
          <div className="flex gap-2">
            <Button size="sm" disabled={busy || (writing === 'note' && !text.trim())} onClick={() => void submit(writing, text)}>
              {writing === 'note' ? 'Save note' : 'Mark disputed'}
            </Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => setWriting(undefined)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="outline" disabled={busy} onClick={() => void submit('reviewed', '')}>
            <Icon name="check" /> Mark reviewed
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => setWriting('disputed')}>
            Dispute
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => setWriting('note')}>
            <Icon name="note" /> Add note
          </Button>
          {!actor ? (
            <span className="text-caption text-ink-muted">
              Your name is not set, so this is labelled "Someone". <Link to="/settings" className="underline underline-offset-2">Set it in Settings</Link>.
            </span>
          ) : null}
        </div>
      )}
    </div>
  )
}

/**
 * Notes and reviews stay with a claim only while a run states that claim the same way.
 * After a re-run that words something differently, they are listed here instead of lost.
 */
export function OrphanedNotes({ b }: { b: InvestigationBundle }) {
  const ctx = useContext(Ctx)
  const fmt = useFormat()
  if (!ctx) return null
  const live = new Set(
    [b.findings, b.commitments, b.timeline, b.contradictions, b.gaps, b.actions, b.blockers].flatMap((group) => group.map((x) => x.id)),
  )
  const orphans = ctx.items.filter((a) => !live.has(a.targetId))
  if (orphans.length === 0) return null
  return (
    <section aria-label="Notes on claims that changed" className="border border-line bg-surface px-5 py-4">
      <h2 className="text-heading text-ink">Notes on claims that changed</h2>
      <p className="mt-0.5 text-caption text-ink-muted">The latest run no longer states these claims the same way, so they are shown here instead of next to a claim.</p>
      <ul className="mt-3 flex flex-col gap-2">
        {orphans.map((a) => (
          <li key={a.id} className="flex flex-wrap items-start gap-2 border-l-2 border-line bg-surface-muted px-3 py-1.5 text-caption text-ink">
            <Badge tone={a.kind === 'reviewed' ? 'successSoft' : a.kind === 'disputed' ? 'dangerSoft' : 'muted'}>{LABEL[a.kind]}</Badge>
            <span className="min-w-0 flex-1">
              {a.text || 'No text'}
              <span className="block text-ink-muted">
                {a.author} · {fmt.date(a.createdAt)}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
