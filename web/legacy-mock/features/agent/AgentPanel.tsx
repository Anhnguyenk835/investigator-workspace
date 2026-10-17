import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Button, ConfirmDialog, Icon } from '@/components/ui'
import { useToast } from '@/components/ui/Toast'
import { cn } from '@/lib/cn'
import { mockApi, type InvestigationBundle } from '@/lib/mockApi'
import {
  newAgentConversation,
  retryAgentTurn,
  sendAgentMessage,
  useAgentConversation,
} from '@/lib/mock/agentStore'
import { useOpenEvidence } from '@/features/evidence/EvidenceCitation'
import { revealAndFlash } from '@/features/agent/highlight'
import { AgentAvatar, AssistantMessage, ToolList, UserMessage, type AgentHandlers } from '@/features/agent/AgentMessageView'
import type { AgentAction } from '@/types/agent'

const GREETING =
  "I'm ready to investigate this escalation. I can trace the timeline, check commitments, compare conflicting evidence, and help prepare a customer update. All findings will link back to their source records."

const PROMPTS = [
  'Summarize what happened',
  'Find missed commitments',
  'What caused the delay?',
  'Show conflicting evidence',
  'What should we do next?',
  'Draft a customer update',
]

type Status = 'Ready' | 'Working' | 'Needs input'

export function AgentPanel({
  bundle,
  variant,
  onCollapse,
  onNavigate,
}: {
  bundle: InvestigationBundle
  variant: 'rail' | 'drawer'
  onCollapse?: () => void
  onNavigate?: () => void
}) {
  const inv = bundle.investigation
  const toast = useToast()
  const evidence = useOpenEvidence()
  const { conversation, pending, failed } = useAgentConversation(inv.id)
  const messages = conversation.messages
  const busy = Boolean(pending)

  const [text, setText] = useState('')
  const [confirmNew, setConfirmNew] = useState(false)
  const [noteAction, setNoteAction] = useState<Extract<AgentAction, { kind: 'apply_note' }> | null>(null)
  const [noteBusy, setNoteBusy] = useState(false)
  const [unseen, setUnseen] = useState(false)
  const scroller = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  const input = useRef<HTMLTextAreaElement>(null)

  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant')
  const status: Status = busy ? 'Working' : failed || lastAssistant?.needsInput ? 'Needs input' : 'Ready'

  const scrollToEnd = useCallback(() => {
    const el = scroller.current
    if (el) el.scrollTo({ top: el.scrollHeight })
    setUnseen(false)
  }, [])

  const trackCount = messages.length + (pending?.tools.length ?? 0) + (busy ? 1 : 0) + (failed ? 1 : 0)
  useEffect(() => {
    if (stick.current) scrollToEnd()
    else setUnseen(true)
  }, [trackCount, scrollToEnd])

  const send = (value: string) => {
    if (busy || !value.trim()) return
    stick.current = true
    sendAgentMessage(inv.id, value)
    setText('')
  }

  const focusRecord = (id: string, what: string) => {
    onNavigate?.()
    window.setTimeout(() => {
      void revealAndFlash(id).then((found) => {
        if (!found) toast.info(`That ${what} is not visible`, 'A filter on the timeline may be hiding it. Clear the filters and try again.')
      })
    }, onNavigate ? 120 : 0)
  }

  const handlers: AgentHandlers = {
    busy,
    sendFollowUp: send,
    showTimeline: (id) => focusRecord(id, 'event'),
    viewFinding: (id) => focusRecord(id, 'finding'),
    viewCommitment: (id) => focusRecord(id, 'commitment'),
    isDone: (a) =>
      a.kind === 'add_action'
        ? bundle.actions.some((x) => x.id === a.action.id)
        : a.kind === 'apply_note'
          ? Boolean(inv.notes?.some((n) => n.id === a.id))
          : false,
    run: (a) => {
      switch (a.kind) {
        case 'open_evidence':
          evidence.open(a.evidenceId)
          break
        case 'show_timeline':
          focusRecord(a.timelineEventId, 'event')
          break
        case 'view_finding':
          focusRecord(a.findingId, 'finding')
          break
        case 'open_response':
          onNavigate?.()
          focusRecord('response', 'response editor')
          break
        case 'add_action':
          if (handlers.isDone(a)) {
            focusRecord(a.action.id, 'action')
            break
          }
          mockApi
            .createAction(inv.id, a.action)
            .then(() => {
              toast.success('Action added', 'It is now listed under Recommended actions as suggested.')
            })
            .catch((e: unknown) => toast.error('Could not add the action', e instanceof Error ? e.message : undefined))
          break
        case 'apply_note':
          setNoteAction(a)
          break
      }
    },
  }

  const applyNote = async () => {
    if (!noteAction) return
    setNoteBusy(true)
    try {
      await mockApi.addInvestigationNote(inv.id, noteAction.id, noteAction.noteText)
      toast.success('Note added', 'See Investigation notes at the bottom of the workspace.')
      setNoteAction(null)
    } catch (e) {
      toast.error('Could not add the note', e instanceof Error ? e.message : undefined)
    } finally {
      setNoteBusy(false)
    }
  }

  useLayoutEffect(() => {
    const el = input.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
    el.style.overflowY = el.scrollHeight > 160 ? 'auto' : 'hidden'
  }, [text])

  return (
    <section aria-label="Investigator Agent" className={cn('flex min-h-0 flex-col bg-surface', 'h-full')}>
      <header className="flex items-center gap-3 border-b border-line-subtle px-4 py-3">
        <AgentAvatar animated busy={busy} />
        <div className="min-w-0 flex-1 self-center">
          {variant === 'rail' ? <h2 className="text-body font-medium text-ink">Investigator Agent</h2> : null}
          <p className="sr-only" role="status">
            Agent status: {status}
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          disabled={busy || messages.length === 0}
          onClick={() => setConfirmNew(true)}
          aria-label="New conversation"
          title="New conversation"
        >
          <Icon name="plus" />
        </Button>
        {onCollapse ? (
          <Button variant="ghost" size="sm" onClick={onCollapse} aria-label="Close agent panel" title="Close agent panel">
            <Icon name="x" />
          </Button>
        ) : null}
      </header>

      <div className="relative min-h-0 flex-1">
        <div
          ref={scroller}
          role="log"
          aria-live="polite"
          aria-label="Conversation"
          tabIndex={0}
          onScroll={(e) => {
            const el = e.currentTarget
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
            if (stick.current) setUnseen(false)
          }}
          className="flex h-full flex-col gap-3 overflow-y-auto px-4 py-4"
        >
          <div className="flex items-start gap-2">
            <AgentAvatar />
            <article className="min-w-0 flex-1 border border-line-subtle bg-surface-muted p-3 text-caption text-ink">{GREETING}</article>
          </div>

          {messages.length === 0 && !busy ? (
            <div className="flex flex-col gap-2">
              <p className="text-overline uppercase text-ink-muted">Try asking</p>
              <div className="flex flex-wrap gap-1.5">
                {PROMPTS.map((p) => (
                  <button
                    key={p}
                    type="button"
                    disabled={busy}
                    onClick={() => send(p)}
                    className="border border-line bg-surface px-2.5 py-1 text-caption text-ink hover:border-primary/60 disabled:opacity-40"
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {messages.map((m, i) =>
            m.role === 'user' ? (
              <UserMessage key={m.id} m={m} />
            ) : (
              <AssistantMessage key={m.id} m={m} h={handlers} last={i === messages.length - 1 && !busy} />
            ),
          )}

          {pending ? (
            <div className="flex items-start gap-2">
              <AgentAvatar animated busy />
              <article className="min-w-0 flex-1 border border-line-subtle bg-surface p-3" aria-label="Agent is working">
                <p className="mb-1 text-overline uppercase text-ink-muted">Working on: {pending.text}</p>
                <ToolList tools={pending.tools} live />
              </article>
            </div>
          ) : null}

          {failed ? (
            <div role="alert" className="flex flex-col gap-2 border border-danger/30 bg-danger/10 p-3 text-caption text-ink">
              <p className="flex items-center gap-1.5 font-medium text-danger">
                <Icon name="alert" /> The agent could not respond
              </p>
              <p>{failed.error}</p>
              <div>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => retryAgentTurn(inv.id)}>
                  <Icon name="refresh" /> Retry
                </Button>
              </div>
            </div>
          ) : null}
        </div>
        {unseen ? (
          <button
            type="button"
            onClick={() => {
              stick.current = true
              scrollToEnd()
            }}
            className="absolute bottom-2 left-1/2 -translate-x-1/2 border border-line bg-surface px-3 py-1 text-caption text-ink shadow-sm hover:bg-surface-muted"
          >
            <Icon name="arrowDown" className="mr-1 inline size-3.5" /> New activity
          </button>
        ) : null}
      </div>

      <form
        className="px-4 pb-4 pt-2"
        onSubmit={(e) => {
          e.preventDefault()
          send(text)
        }}
      >
        <label htmlFor={`agent-input-${variant}`} className="sr-only">
          Ask the Investigator Agent
        </label>
        <div className="flex flex-col gap-1 rounded-[1.25rem] border border-line bg-surface py-2 pl-3 pr-2 shadow-sm focus-within:border-ink-muted/40">
          <span
            className="inline-flex max-w-full items-center gap-1.5 self-start rounded-[999px] bg-primary/10 px-2.5 py-0.5 text-caption text-info"
            title={`Investigation: ${inv.title}`}
          >
            <Icon name="investigations" className="size-3.5" />
            <span className="truncate">{inv.title}</span>
          </span>
          <div className="flex items-end gap-2">
          <textarea
            ref={input}
            id={`agent-input-${variant}`}
            rows={1}
            value={text}
            placeholder="Ask about this investigation…"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                send(text)
              }
            }}
            className="max-h-40 min-h-8 flex-1 resize-none overflow-hidden bg-transparent px-1 py-1.5 leading-5 text-body text-ink placeholder:text-ink-muted focus:outline-none"
          />
          <Button type="submit" size="sm" className="size-8 shrink-0 rounded-[999px] px-0" disabled={busy || !text.trim()} aria-label={busy ? 'Working' : 'Send message'} title="Send">
            <Icon name={busy ? 'refresh' : 'arrowUp'} className={busy ? 'animate-spin' : undefined} />
          </Button>
          </div>
        </div>
      </form>

      <ConfirmDialog
        open={confirmNew}
        tone="solid"
        title="Start a new conversation?"
        body="The current conversation for this investigation is cleared. Evidence, findings and actions are not affected."
        confirmLabel="Start new"
        onCancel={() => setConfirmNew(false)}
        onConfirm={() => {
          newAgentConversation(inv.id)
          setConfirmNew(false)
        }}
      />
      <ConfirmDialog
        open={noteAction !== null}
        tone="solid"
        title="Add this note to the investigation?"
        body={
          <div className="flex flex-col gap-2">
            <p className="whitespace-pre-wrap border-l-2 border-primary/50 bg-surface-muted px-3 py-2 text-caption">{noteAction?.noteText}</p>
            <p className="text-caption text-ink-muted">It is saved under your name. The agent never edits records without this confirmation.</p>
          </div>
        }
        confirmLabel="Add note"
        busy={noteBusy}
        onCancel={() => setNoteAction(null)}
        onConfirm={() => void applyNote()}
      />
    </section>
  )
}
