import type { ReactNode } from 'react'
import { Icon } from '@/components/ui'
import { AgentOrb } from '@/features/agent/AgentOrb'
import { ProviderName } from '@/components/shared/ProviderMark'
import { EvidenceCitation } from '@/features/evidence/EvidenceCitation'
import { cn } from '@/lib/cn'
import type { ChatMessage, ChatTool } from '@/types/investigator'

/** `[E:a]`, or several ids in one bracket: `[E:a, E:b]` or `[E:a, b]`. */
const MARKER = /(\[E:[^\]]+\])/g

/** The record ids a marker names, or undefined when the text is not a marker. */
function idsIn(part: string): string[] | undefined {
  const m = /^\[(E:[^\]]+)\]$/.exec(part)
  if (!m?.[1]) return undefined
  const ids = m[1].split(',').map((p) => p.trim().replace(/^E:/, ''))
  return ids.every((p) => /^\S+$/.test(p)) ? ids : undefined
}

/** One line of an answer: **bold**, *italic* and citation chips. */
function Inline({ text, pending }: { text: string; pending: boolean }) {
  return (
    <>
      {text.split(/(\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/).map((chunk, i) => {
        const bold = /^\*\*([^*]+)\*\*$/.exec(chunk)
        const italic = bold ? null : /^\*([^*\s][^*]*)\*$/.exec(chunk)
        const body = bold?.[1] ?? italic?.[1] ?? chunk
        const parts = body.split(MARKER).map((part, j) => {
          const ids = idsIn(part)
          return ids ? ids.map((id) => <EvidenceCitation key={`${j}-${id}`} id={id} pending={pending} />) : <span key={j}>{part}</span>
        })
        if (bold)
          return (
            <strong key={i} className="font-medium">
              {parts}
            </strong>
          )
        if (italic) return <em key={i}>{parts}</em>
        return <span key={i}>{parts}</span>
      })}
    </>
  )
}

const BULLET = /^\s*[*-]\s+/
const NUMBERED = /^\s*\d+[.)]\s+/
const HEADING = /^\s*#{1,6}\s+/

type BlockKind = 'p' | 'ul' | 'ol' | 'h'

function kindOf(line: string): BlockKind {
  if (HEADING.test(line)) return 'h'
  if (BULLET.test(line)) return 'ul'
  if (NUMBERED.test(line)) return 'ol'
  return 'p'
}

/**
 * An answer with the little formatting models use (headings, bold, italic, bullet and numbered
 * lists) and each complete `[E:id]` marker shown as a citation chip. An unfinished marker at the
 * end of a stream is held back.
 */
export function CitedText({ text, streaming = false }: { text: string; streaming?: boolean }) {
  const visible = streaming ? text.replace(/\[E:[^\]]*$/, '') : text
  const blocks: { kind: BlockKind; lines: string[] }[] = []
  for (const line of visible.split('\n')) {
    if (line.trim() === '') {
      blocks.push({ kind: 'p', lines: [] })
      continue
    }
    const kind = kindOf(line)
    const last = blocks[blocks.length - 1]
    if (last && last.lines.length > 0 && last.kind === kind && kind !== 'h') last.lines.push(line)
    else blocks.push({ kind, lines: [line] })
  }
  return (
    <div className="flex flex-col gap-2 break-words text-body text-ink">
      {blocks
        .filter((b) => b.lines.length > 0)
        .map((b, i) => {
          if (b.kind === 'h')
            return (
              <p key={i} className="mt-1 font-medium text-ink">
                <Inline text={b.lines[0]?.replace(HEADING, '') ?? ''} pending={streaming} />
              </p>
            )
          if (b.kind === 'ul' || b.kind === 'ol') {
            const Tag = b.kind
            return (
              <Tag key={i} className={cn('flex flex-col gap-1 pl-5', b.kind === 'ul' ? 'list-disc' : 'list-decimal')}>
                {b.lines.map((l, j) => (
                  <li key={j}>
                    <Inline text={l.replace(b.kind === 'ul' ? BULLET : NUMBERED, '')} pending={streaming} />
                  </li>
                ))}
              </Tag>
            )
          }
          return (
            <p key={i} className="whitespace-pre-wrap">
              <Inline text={b.lines.join('\n')} pending={streaming} />
            </p>
          )
        })}
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
