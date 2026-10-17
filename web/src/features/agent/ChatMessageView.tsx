import type { ReactNode } from 'react'
import { Icon } from '@/components/ui'
import { AgentOrb } from '@/features/agent/AgentOrb'
import { ProviderName } from '@/components/shared/ProviderMark'
import { EvidenceCitation } from '@/features/evidence/EvidenceCitation'
import { cn } from '@/lib/cn'
import type { ChatMessage, ChatTool } from '@/types/investigator'

/** `[E:a]`, or several ids in one bracket: `[E:a, E:b]`. */
const MARKER = /(\[E:[^\]]+\])/g

/** The record ids a marker names, or undefined when the text is not a marker. */
function idsIn(part: string): string[] | undefined {
  const m = /^\[(E:[^\]]+)\]$/.exec(part)
  if (!m?.[1]) return undefined
  const ids = m[1].split(',').map((p) => p.trim())
  return ids.every((p) => /^E:\S+$/.test(p)) ? ids.map((p) => p.slice(2)) : undefined
}

/** One line of an answer: **bold** and citation chips. */
function Inline({ text, pending }: { text: string; pending: boolean }) {
  return (
    <>
      {text.split(/(\*\*[^*]+\*\*)/).map((chunk, i) => {
        const bold = /^\*\*([^*]+)\*\*$/.exec(chunk)
        const body = bold?.[1] ?? chunk
        const parts = body.split(MARKER).map((part, j) => {
          const ids = idsIn(part)
          return ids ? ids.map((id) => <EvidenceCitation key={`${j}-${id}`} id={id} pending={pending} />) : <span key={j}>{part}</span>
        })
        return bold ? (
          <strong key={i} className="font-medium">
            {parts}
          </strong>
        ) : (
          <span key={i}>{parts}</span>
        )
      })}
    </>
  )
}

const BULLET = /^\s*[*-]\s+/

/**
 * An answer with the little formatting models use (bold, bullet lists) and each complete
 * `[E:id]` marker shown as a citation chip. An unfinished marker at the end of a stream is held back.
 */
export function CitedText({ text, streaming = false }: { text: string; streaming?: boolean }) {
  const visible = streaming ? text.replace(/\[E:[^\]]*$/, '') : text
  const blocks: { bullet: boolean; lines: string[] }[] = []
  for (const line of visible.split('\n')) {
    if (line.trim() === '') {
      blocks.push({ bullet: false, lines: [] })
      continue
    }
    const bullet = BULLET.test(line)
    const last = blocks[blocks.length - 1]
    if (last && last.lines.length > 0 && last.bullet === bullet) last.lines.push(line)
    else blocks.push({ bullet, lines: [line] })
  }
  return (
    <div className="flex flex-col gap-2 break-words text-body text-ink">
      {blocks
        .filter((b) => b.lines.length > 0)
        .map((b, i) =>
          b.bullet ? (
            <ul key={i} className="flex list-disc flex-col gap-1 pl-5">
              {b.lines.map((l, j) => (
                <li key={j}>
                  <Inline text={l.replace(BULLET, '')} pending={streaming} />
                </li>
              ))}
            </ul>
          ) : (
            <p key={i} className="whitespace-pre-wrap">
              <Inline text={b.lines.join('\n')} pending={streaming} />
            </p>
          ),
        )}
    </div>
  )
}

function toolLine(t: ChatTool): string {
  if (['searched', 'partial', 'no_matches', 'cached'].includes(t.status)) {
    const found = t.records === 0 ? 'no matching records' : `${t.records} ${t.records === 1 ? 'record' : 'records'}${t.newRecords > 0 ? `, ${t.newRecords} new` : ''}`
    return t.status === 'partial' ? `${found} (not fully searched)` : found
  }
  return t.status.replaceAll('_', ' ')
}

export function ToolList({ tools, live = false }: { tools: ChatTool[]; live?: boolean }) {
  if (tools.length === 0) return null
  return (
    <ul className="flex flex-col gap-1" aria-label="Searches the assistant ran">
      {tools.map((t, i) => (
        <li key={i} className="flex flex-wrap items-center gap-x-2 text-caption text-ink-muted">
          <Icon name={live && i === tools.length - 1 ? 'search' : 'circleCheck'} className="size-3.5" />
          <span>Searched</span>
          {t.source ? <ProviderName provider={t.source} /> : <span>a source</span>}
          <span>· {toolLine(t)}</span>
        </li>
      ))}
    </ul>
  )
}

export function UserMessage({ m }: { m: ChatMessage }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-[4px] border border-primary/40 bg-primary/10 px-3 py-2 text-body text-ink">{m.content}</p>
    </div>
  )
}

/** The agent's small mark beside what it says; the answer sits to its right. */
export function AgentTurn({ children, animated = false, label }: { children: ReactNode; animated?: boolean; label: string }) {
  return (
    <div className="flex items-start gap-2.5">
      <AgentOrb className="mt-1 size-6 shrink-0" animated={animated} busy={animated} />
      <article className="flex min-w-0 flex-1 flex-col gap-2 rounded-[4px] border border-line-subtle bg-surface p-3" aria-label={label}>
        {children}
      </article>
    </div>
  )
}

export function AssistantMessage({ m }: { m: ChatMessage }) {
  return (
    <AgentTurn label="Assistant answer">
      <CitedText text={m.content} />
      {m.warnings.length > 0 ? (
        <ul className="flex flex-col gap-1 border-l-2 border-warning bg-warning/10 px-3 py-2">
          {m.warnings.map((w, i) => (
            <li key={i} className={cn('flex items-start gap-1.5 text-caption text-ink')}>
              <Icon name="alert" className="mt-0.5 size-3.5 shrink-0 text-warning" />
              {w}
            </li>
          ))}
        </ul>
      ) : null}
      <ToolList tools={m.tools} />
    </AgentTurn>
  )
}
