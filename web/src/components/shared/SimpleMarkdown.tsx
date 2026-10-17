import { Fragment, type ReactNode } from 'react'

/** **bold** and `code` inside one line. Nothing else is interpreted, and nothing is injected as HTML. */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/).map((part, i) => {
    if (/^\*\*[^*]+\*\*$/.test(part)) return <strong key={i} className="font-medium text-ink">{part.slice(2, -2)}</strong>
    if (/^`[^`]+`$/.test(part)) return <code key={i} className="bg-surface-muted px-1 font-mono text-[0.85em]">{part.slice(1, -1)}</code>
    return <Fragment key={i}>{part}</Fragment>
  })
}

interface Item {
  depth: number
  text: string
}

type Block = { kind: 'heading'; text: string } | { kind: 'para'; text: string } | { kind: 'list'; items: Item[] } | { kind: 'rule' }

function parse(source: string): Block[] {
  const blocks: Block[] = []
  for (const raw of source.split('\n')) {
    const line = raw.replace(/\s+$/, '')
    if (!line.trim()) continue
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
      blocks.push({ kind: 'rule' })
      continue
    }
    const heading = /^#{1,6}\s+(.*)$/.exec(line)
    if (heading?.[1]) {
      blocks.push({ kind: 'heading', text: heading[1].replace(/[*:]+$/g, '') })
      continue
    }
    const bullet = /^(\s*)[-*]\s+(.*)$/.exec(line)
    if (bullet) {
      const item = { depth: Math.min(Math.floor((bullet[1] ?? '').length / 2), 2), text: bullet[2] ?? '' }
      const last = blocks[blocks.length - 1]
      if (last?.kind === 'list') last.items.push(item)
      else blocks.push({ kind: 'list', items: [item] })
      continue
    }
    const last = blocks[blocks.length - 1]
    // A wrapped line of a list item or paragraph continues it.
    if (last?.kind === 'para') last.text += ` ${line.trim()}`
    else if (last?.kind === 'list' && last.items.length > 0 && /^\s+\S/.test(line)) last.items[last.items.length - 1]!.text += ` ${line.trim()}`
    else blocks.push({ kind: 'para', text: line.trim() })
  }
  return blocks
}

/** The small amount of markdown a model writes (headings, bullets, bold, rules), laid out compactly. */
export function SimpleMarkdown({ source }: { source: string }) {
  return (
    <div className="flex flex-col gap-2 text-caption text-ink-muted">
      {parse(source).map((b, i) => {
        if (b.kind === 'rule') return <hr key={i} className="border-line-subtle" />
        if (b.kind === 'heading') return <h4 key={i} className="mt-1 text-caption font-medium text-ink">{inline(b.text)}</h4>
        if (b.kind === 'para') return <p key={i}>{inline(b.text)}</p>
        return (
          <ul key={i} className="flex flex-col gap-1">
            {b.items.map((it, j) => (
              <li key={j} className="flex gap-2" style={{ paddingLeft: `${it.depth * 0.9}rem` }}>
                <span aria-hidden="true" className="mt-[0.45rem] size-1 shrink-0 bg-ink-muted/70" />
                <span className="min-w-0">{inline(it.text)}</span>
              </li>
            ))}
          </ul>
        )
      })}
    </div>
  )
}
