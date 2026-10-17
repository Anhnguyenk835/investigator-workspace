import { useEffect, useRef, useState } from 'react'
import { Icon } from '@/components/ui'
import { cn } from '@/lib/cn'
import { relativeTime } from '@/lib/format'
import type { Conversation } from '@/types/investigator'

interface Props {
  conversations: Conversation[]
  selected: string | null
  busy: boolean
  error?: string
  onSelect: (id: string) => void
  onNew: () => void
  onRename: (id: string, title: string) => Promise<void>
  onDelete: (id: string) => void
  onClose: () => void
}

/** The conversations about this investigation, newest first, as a drop-down under the panel header. */
export function ConversationList({ conversations, selected, busy, error, onSelect, onNew, onRename, onDelete, onClose }: Props) {
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [saveError, setSaveError] = useState<string | undefined>(undefined)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && editing === null) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [editing, onClose])

  useEffect(() => {
    if (editing) input.current?.select()
  }, [editing])

  const save = async (id: string) => {
    const title = draft.trim()
    if (!title) return setEditing(null)
    try {
      await onRename(id, title)
      setEditing(null)
      setSaveError(undefined)
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'The title could not be saved.')
    }
  }

  return (
    <>
      <div className="fixed inset-0 z-10" aria-hidden="true" onClick={onClose} />
      <div role="dialog" aria-label="Conversations" className="absolute inset-x-0 top-full z-20 flex max-h-[26rem] flex-col border-b border-line bg-surface shadow-lg">
        <button type="button" disabled={busy} onClick={onNew} className="flex items-center gap-2 border-b border-line-subtle px-4 py-2.5 text-left text-body text-ink hover:bg-surface-muted disabled:opacity-40">
          <Icon name="plus" className="size-4" /> New chat
        </button>
        <ul className="min-h-0 flex-1 overflow-y-auto py-1">
          {conversations.length === 0 ? <li className="px-4 py-3 text-caption text-ink-muted">No conversations yet. Ask a question to start one.</li> : null}
          {conversations.map((c) => (
            <li key={c.id} className={cn('group flex items-center gap-1 px-2', c.id === selected && 'bg-primary/10')}>
              {editing === c.id ? (
                <input
                  ref={input}
                  value={draft}
                  maxLength={120}
                  aria-label="Conversation title"
                  className="m-1 min-w-0 flex-1 rounded-[4px] border border-line bg-surface px-2 py-1 text-body text-ink focus:border-primary/60 focus:outline-none"
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void save(c.id)
                    if (e.key === 'Escape') setEditing(null)
                  }}
                  onBlur={() => void save(c.id)}
                />
              ) : (
                <button type="button" onClick={() => onSelect(c.id)} aria-current={c.id === selected ? 'true' : undefined} className="min-w-0 flex-1 px-2 py-2 text-left">
                  <span className="block truncate text-body text-ink">{c.title}</span>
                  <span className="block text-overline text-ink-muted">
                    {relativeTime(c.updatedAt)} · {c.messageCount} {c.messageCount === 1 ? 'message' : 'messages'}
                  </span>
                </button>
              )}
              {editing === c.id ? null : (
                <span className="flex shrink-0 opacity-0 focus-within:opacity-100 group-hover:opacity-100">
                  <button
                    type="button"
                    title="Rename"
                    aria-label={`Rename ${c.title}`}
                    className="p-1.5 text-ink-muted hover:text-ink"
                    onClick={() => {
                      setDraft(c.title)
                      setEditing(c.id)
                    }}
                  >
                    <Icon name="edit" className="size-4" />
                  </button>
                  <button type="button" title="Delete" aria-label={`Delete ${c.title}`} disabled={busy && c.id === selected} className="p-1.5 text-ink-muted hover:text-danger disabled:opacity-40" onClick={() => onDelete(c.id)}>
                    <Icon name="trash" className="size-4" />
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
        {error || saveError ? <p role="alert" className="border-t border-line-subtle px-4 py-2 text-caption text-danger">{saveError ?? error}</p> : null}
      </div>
    </>
  )
}
