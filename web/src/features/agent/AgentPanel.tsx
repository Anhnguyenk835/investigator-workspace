import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Button, ConfirmDialog, Icon } from '@/components/ui'
import { AgentOrb } from '@/features/agent/AgentOrb'
import { AgentTurn, AssistantMessage, CitedText, ToolList, UserMessage } from '@/features/agent/ChatMessageView'
import { ConversationList } from '@/features/agent/ConversationList'
import { useChat } from '@/hooks/useChat'
import { useConversations } from '@/hooks/useConversations'
import type { Investigation } from '@/types/investigator'

/** The small square icon buttons in the header. */
const ICON_BUTTON = 'size-7! min-w-0! p-0!'

const PROMPTS = ['Summarize what happened', 'What was promised, and by when?', 'What is still unknown?', 'Which findings are not verified?']

/** Whether a question can be asked now, and if not, why. */
function blockedReason(inv: Investigation): string | undefined {
  if (inv.status === 'queued' || inv.status === 'investigating') return 'The investigation is still running. Ask again when it has finished.'
  return undefined
}

export function AgentPanel({ inv, variant, onCollapse }: { inv: Investigation; variant: 'rail' | 'drawer'; onCollapse?: () => void }) {
  const convs = useConversations(inv.id)
  const chat = useChat(inv.id, convs.selected, convs.create, convs.refresh)
  const [listOpen, setListOpen] = useState(false)
  const [text, setText] = useState('')
  // The conversation waiting for a yes before it is deleted.
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  const field = useRef<HTMLTextAreaElement>(null)
  const answering = chat.phase === 'answering'
  const openTitle = convs.list.find((c) => c.id === convs.selected)?.title ?? 'New chat'
  const reason = blockedReason(inv)
  const disabled = answering || chat.phase === 'loading' || Boolean(reason)

  // Follow the answer as it grows, unless the person scrolled up to read.
  // The box grows with what is typed, up to its max height, then scrolls (as in ChatGPT).
  useLayoutEffect(() => {
    const el = field.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }, [text])

  useEffect(() => {
    const el = scroller.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [chat.messages, chat.draft, chat.tools, chat.error])

  const submit = (value: string) => {
    if (disabled || !value.trim()) return
    stick.current = true
    chat.send(value)
    setText('')
  }

  return (
    <section aria-label="Investigator Agent" className="flex h-full min-h-0 flex-col bg-surface">
      <div className="relative">
        <header className="flex items-center gap-2 border-b border-line-subtle py-3 pl-4 pr-2">
          <AgentOrb animated={answering} busy={answering} className="size-8" />
          <div className="min-w-0 flex-1">
            <h2 className="text-body font-medium text-ink">Investigator Agent</h2>
            <p className="truncate text-caption text-ink-muted" title={openTitle}>
              {openTitle}
            </p>
            <span className="sr-only" role="status">
              {answering ? 'Answering' : chat.phase === 'loading' || convs.loading ? 'Loading' : 'Ready'}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-0.5">
          <Button variant="ghost" size="sm" className={ICON_BUTTON} title="New chat" aria-label="New chat" disabled={answering || convs.selected === null} onClick={() => convs.startNew()}>
            <Icon name="plus" className="size-4" />
          </Button>
          <Button variant="ghost" size="sm" className={ICON_BUTTON} title="Conversations" aria-label="Conversations" aria-expanded={listOpen} aria-haspopup="dialog" onClick={() => setListOpen((v) => !v)}>
            <Icon name="menu" className="size-4" />
          </Button>
          <Button variant="ghost" size="sm" className={ICON_BUTTON} title="Delete this conversation" aria-label="Delete this conversation" disabled={answering || convs.selected === null} onClick={() => setConfirmDelete(convs.selected)}>
            <Icon name="trash" className="size-4" />
          </Button>
          {onCollapse ? (
            <Button variant="ghost" size="sm" className={ICON_BUTTON} title="Collapse" aria-label="Collapse the agent panel" onClick={onCollapse}>
              <Icon name="x" className="size-4" />
            </Button>
          ) : null}
          </div>
        </header>
        {listOpen ? (
          <ConversationList
            conversations={convs.list}
            selected={convs.selected}
            busy={answering}
            error={convs.error}
            onSelect={(id) => {
              if (!answering) convs.select(id)
              setListOpen(false)
            }}
            onNew={() => {
              convs.startNew()
              setListOpen(false)
            }}
            onRename={convs.rename}
            onDelete={(id) => setConfirmDelete(id)}
            onClose={() => setListOpen(false)}
          />
        ) : null}
      </div>

      <div
        ref={scroller}
        className="min-h-0 flex-1 overflow-y-auto px-4 py-4"
        onScroll={(e) => {
          const el = e.currentTarget
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48
        }}
      >
        <div className="flex flex-col gap-3" aria-live="polite">

          {chat.phase === 'idle' && chat.messages.length === 0 && !chat.error ? (
            <div className="flex flex-wrap gap-1.5">
              {PROMPTS.map((p) => (
                <button key={p} type="button" disabled={disabled} onClick={() => submit(p)} className="border border-line bg-surface px-2.5 py-1 text-caption text-ink hover:border-primary/60 disabled:opacity-40">
                  {p}
                </button>
              ))}
            </div>
          ) : null}

          {chat.messages.map((m) => (m.role === 'user' ? <UserMessage key={m.id} m={m} /> : <AssistantMessage key={m.id} m={m} />))}

          {answering ? (
            <AgentTurn label="Assistant is answering" animated>
              {chat.draft ? <CitedText text={chat.draft} streaming={!chat.checking} /> : <p className="text-caption text-ink-muted">{chat.tools.length > 0 ? 'Reading what was found…' : 'Thinking…'}</p>}
              <ToolList tools={chat.tools} live />
              {chat.checking ? <p className="text-caption text-ink-muted">Checking that each cited record says what the sentence says…</p> : null}
            </AgentTurn>
          ) : null}

          {chat.error ? (
            <div role="alert" className="flex flex-col gap-2 border border-danger/40 bg-danger/10 p-3 text-caption text-ink">
              <p className="flex items-center gap-1.5 font-medium text-danger">
                <Icon name="alert" /> The assistant could not answer
              </p>
              <p>{chat.error}</p>
              {chat.failedQuestion ? (
                <div>
                  <Button size="sm" variant="outline" disabled={disabled} onClick={chat.retry}>
                    <Icon name="refresh" /> Try again
                  </Button>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>

      <form
        className="px-4 pb-4 pt-3"
        onSubmit={(e) => {
          e.preventDefault()
          submit(text)
        }}
      >
        {reason ? <p className="mb-2 text-caption text-ink-muted">{reason}</p> : null}
        <label htmlFor={`agent-input-${variant}`} className="sr-only">
          Ask the Investigator Agent
        </label>
        <div className="relative flex flex-col rounded-[0.75rem] border border-line bg-surface pb-2 pl-4 pr-1 pt-2.5 shadow-sm focus-within:border-primary/60 focus-within:ring-2 focus-within:ring-primary/20">
          {/* Which investigation this conversation is about. It follows the page and cannot be removed. */}
          <div className="flex pr-3">
            <span
              className="inline-flex max-w-full items-center gap-1.5 rounded-[4px] border border-line bg-surface-muted px-2 py-0.5 text-caption text-ink"
              title={inv.problemStatement}
              aria-label={`Context: investigation ${inv.title}`}
            >
              <Icon name="investigations" className="size-3.5 shrink-0 text-ink-muted" />
              <span className="shrink-0 text-ink-muted">Investigation</span>
              <span className="truncate">{inv.title}</span>
            </span>
          </div>
          <textarea
            id={`agent-input-${variant}`}
            ref={field}
            rows={1}
            value={text}
            disabled={Boolean(reason) || chat.phase === 'loading'}
            placeholder={chat.phase === 'loading' ? 'Loading the conversation…' : 'Ask about this investigation…'}
            maxLength={4000}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                submit(text)
              }
            }}
            className="max-h-48 min-h-[4.5rem] w-full resize-none overflow-y-auto bg-transparent py-1.5 pr-12 text-body text-ink placeholder:text-ink-muted focus:outline-none disabled:opacity-50"
          />
          <Button type="submit" size="sm" className="absolute bottom-3 right-6 size-[30px]! min-w-0! rounded-full p-0!" disabled={disabled || !text.trim()} aria-label={answering ? 'Answering' : 'Send message'} title="Send (Enter)">
            <Icon name={answering ? 'refresh' : 'arrowUp'} className={answering ? 'animate-spin' : undefined} />
          </Button>
        </div>
      </form>

      <ConfirmDialog
        open={confirmDelete !== null}
        tone="solid"
        title="Delete this conversation?"
        body="Its messages are deleted. The investigation, its evidence and findings, and your other conversations are not affected."
        confirmLabel="Delete"
        onCancel={() => setConfirmDelete(null)}
        onConfirm={async () => {
          if (confirmDelete && (await convs.remove(confirmDelete))) setConfirmDelete(null)
        }}
      />
    </section>
  )
}
