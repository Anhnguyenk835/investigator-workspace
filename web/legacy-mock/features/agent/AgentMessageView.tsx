import { useState } from 'react'
import { Badge, Button, Icon } from '@/components/ui'
import { AgentOrb } from '@/features/agent/AgentOrb'
import { cn } from '@/lib/cn'
import { useFormat } from '@/hooks/useSettings'
import { CitationList } from '@/features/evidence/EvidenceCitation'
import type { AgentAction, AgentBullet, AgentMessage, AgentSection, AgentToolActivity } from '@/types/agent'

const SECTION_LABEL: Record<AgentSection['kind'], string> = {
  direct: 'Direct evidence',
  interpretation: 'Interpretation',
  unknown: 'Unknown',
  conflict: 'Conflict',
  info: 'Note',
}
const SECTION_TONE: Record<AgentSection['kind'], 'successSoft' | 'infoSoft' | 'warningSoft' | 'dangerSoft' | 'muted'> = {
  direct: 'successSoft',
  interpretation: 'infoSoft',
  unknown: 'warningSoft',
  conflict: 'dangerSoft',
  info: 'muted',
}

export function AgentAvatar({ className, animated, busy }: { className?: string; animated?: boolean; busy?: boolean }) {
  return <AgentOrb className={className} animated={animated} busy={busy} />
}

export interface AgentHandlers {
  run: (action: AgentAction) => void
  isDone: (action: AgentAction) => boolean
  showTimeline: (id: string) => void
  viewFinding: (id: string) => void
  viewCommitment: (id: string) => void
  busy: boolean
  sendFollowUp: (text: string) => void
}

export function ToolList({ tools, live }: { tools: AgentToolActivity[]; live?: boolean }) {
  const [open, setOpen] = useState<Set<string>>(new Set())
  if (tools.length === 0) return null
  return (
    <ul className="flex flex-col" aria-label="Agent activity">
      {tools.map((t) => {
        const expanded = open.has(t.id)
        return (
          <li key={t.id} className="border-b border-line-subtle last:border-b-0">
            <button
              type="button"
              aria-expanded={expanded}
              onClick={() =>
                setOpen((cur) => {
                  const next = new Set(cur)
                  if (next.has(t.id)) next.delete(t.id)
                  else next.add(t.id)
                  return next
                })
              }
              className="flex w-full items-center gap-2 py-1.5 text-left text-caption text-ink-muted hover:text-ink"
            >
              <Icon name="check" className="size-3.5 text-success" />
              <span className="min-w-0 flex-1 truncate">{t.label}</span>
              <span className="shrink-0 text-overline">{t.count}</span>
              <Icon name={expanded ? 'chevronUp' : 'chevronDown'} className="size-3.5" />
            </button>
            {expanded ? (
              <div className="flex flex-col gap-1.5 pb-2 pl-5 text-caption text-ink-muted">
                <p>{t.summary}</p>
                <code className="block break-all bg-surface-muted px-2 py-1 font-mono text-overline normal-case tracking-normal">{t.operation}</code>
                {t.evidenceIds.length > 0 ? <CitationList ids={t.evidenceIds.slice(0, 8)} /> : null}
              </div>
            ) : null}
          </li>
        )
      })}
      {live ? (
        <li className="flex items-center gap-2 py-1.5 text-caption text-ink-muted" aria-hidden="true">
          <Icon name="refresh" className="size-3.5 animate-spin" /> Working…
        </li>
      ) : null}
    </ul>
  )
}

function BulletView({ b, h }: { b: AgentBullet; h: AgentHandlers }) {
  return (
    <li className="flex flex-col gap-1">
      <p className={cn('text-caption text-ink', b.tone === 'warning' && 'text-warning')}>{b.text}</p>
      {b.evidenceIds.length > 0 || b.timelineEventId || b.findingId || b.commitmentId ? (
        <div className="flex flex-wrap items-center gap-1.5">
          {b.evidenceIds.length > 0 ? <CitationList ids={b.evidenceIds} /> : null}
          {b.timelineEventId ? (
            <Button variant="ghost" size="sm" className="h-6 px-1.5 text-overline" onClick={() => h.showTimeline(b.timelineEventId ?? '')}>
              Show on timeline
            </Button>
          ) : null}
          {b.findingId ? (
            <Button variant="ghost" size="sm" className="h-6 px-1.5 text-overline" onClick={() => h.viewFinding(b.findingId ?? '')}>
              View finding
            </Button>
          ) : null}
          {b.commitmentId ? (
            <Button variant="ghost" size="sm" className="h-6 px-1.5 text-overline" onClick={() => h.viewCommitment(b.commitmentId ?? '')}>
              View commitment
            </Button>
          ) : null}
        </div>
      ) : null}
    </li>
  )
}

function ActionButton({ a, h }: { a: AgentAction; h: AgentHandlers }) {
  const done = h.isDone(a)
  const label =
    done && a.kind === 'add_action' ? 'Added · View action' : done && a.kind === 'apply_note' ? 'Note added' : a.label
  return (
    <Button
      variant="outline"
      size="sm"
      disabled={h.busy || (done && a.kind === 'apply_note')}
      onClick={() => h.run(a)}
    >
      <Icon name={done ? 'check' : a.kind === 'add_action' ? 'plus' : a.kind === 'open_response' ? 'edit' : a.kind === 'apply_note' ? 'note' : 'external'} />
      {label}
    </Button>
  )
}

export function AssistantMessage({ m, h, last }: { m: AgentMessage; h: AgentHandlers; last: boolean }) {
  const fmt = useFormat()
  const [preview, setPreview] = useState(false)
  return (
    <div className="flex items-start gap-2">
    <AgentAvatar />
    <article className="flex min-w-0 flex-1 flex-col gap-3 border border-line-subtle bg-surface p-3" aria-label="Agent message">
      <div className="flex items-center gap-2 text-overline uppercase text-ink-muted">
        Investigator Agent
        <time dateTime={m.createdAt} className="ml-auto normal-case tracking-normal">
          {fmt.dateTime(m.createdAt)}
        </time>
      </div>
      {m.tools && m.tools.length > 0 ? (
        <div className="bg-surface-muted px-3 py-1">
          <ToolList tools={m.tools} />
        </div>
      ) : null}
      <p className="text-body text-ink">{m.content}</p>
      {m.sections?.map((s) => (
        <section key={s.heading} className="flex flex-col gap-2 border-t border-line-subtle pt-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={SECTION_TONE[s.kind]}>{SECTION_LABEL[s.kind]}</Badge>
            <h3 className="text-caption font-medium text-ink">{s.heading}</h3>
          </div>
          <ul className="flex flex-col gap-2.5">
            {s.bullets.map((b, i) => (
              <BulletView key={i} b={b} h={h} />
            ))}
          </ul>
        </section>
      ))}
      {m.preview ? (
        <div className="border-t border-line-subtle pt-2">
          <Button variant="ghost" size="sm" aria-expanded={preview} onClick={() => setPreview((v) => !v)}>
            <Icon name={preview ? 'chevronUp' : 'chevronDown'} /> {preview ? 'Hide draft preview' : 'Preview draft'}
          </Button>
          {preview ? <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap bg-surface-muted p-3 font-sans text-caption text-ink">{m.preview}</pre> : null}
        </div>
      ) : null}
      {m.actions && m.actions.length > 0 ? (
        <div className="flex flex-wrap gap-2 border-t border-line-subtle pt-2">
          {m.actions.map((a) => (
            <ActionButton key={a.id} a={a} h={h} />
          ))}
        </div>
      ) : null}
      {last && m.followUps && m.followUps.length > 0 ? (
        <div className="flex flex-wrap gap-1.5" aria-label="Suggested follow-ups">
          {m.followUps.map((f) => (
            <button
              key={f}
              type="button"
              disabled={h.busy}
              onClick={() => h.sendFollowUp(f)}
              className="border border-line bg-surface px-2.5 py-1 text-caption text-ink-muted hover:border-primary/60 hover:text-ink disabled:opacity-40"
            >
              {f}
            </button>
          ))}
        </div>
      ) : null}
    </article>
    </div>
  )
}

export function UserMessage({ m }: { m: AgentMessage }) {
  return (
    <article className="ml-8 self-end border border-primary/20 bg-primary/10 px-3 py-2 text-body text-ink" aria-label="Your message">
      <p className="whitespace-pre-wrap">{m.content}</p>
    </article>
  )
}
