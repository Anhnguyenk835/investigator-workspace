import { useCallback, useEffect, useRef, useState } from 'react'
import { api, streamChat } from '@/api/client'
import { toChatMessage, toChatTool } from '@/api/adapt'
import { useEvidenceIndex } from '@/features/evidence/EvidenceIndex'
import type { ChatMessage, ChatTool } from '@/types/investigator'

export type ChatPhase = 'loading' | 'idle' | 'answering'

export interface ChatState {
  messages: ChatMessage[]
  /** The answer so far, while it streams in. */
  draft: string
  /** Searches the assistant has run for the answer in progress. */
  tools: ChatTool[]
  /** The answer is written; its citations are being checked against the records. */
  checking: boolean
  phase: ChatPhase
  error?: string
  /** The question that failed, so it can be sent again. */
  failedQuestion?: string
  send: (text: string) => void
  retry: () => void
}

/**
 * One conversation about an investigation, with the answer streaming in token by token.
 * `conversationId` null is a new chat: nothing exists until the first question, when `ensure`
 * makes the conversation.
 */
export function useChat(
  investigationId: string,
  conversationId: string | null,
  ensure: () => Promise<string>,
  onTurnEnd: () => void,
): ChatState {
  const { addExtra } = useEvidenceIndex()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState('')
  const [tools, setTools] = useState<ChatTool[]>([])
  const [checking, setChecking] = useState(false)
  const [phase, setPhase] = useState<ChatPhase>('loading')
  const [error, setError] = useState<string | undefined>(undefined)
  const [failedQuestion, setFailedQuestion] = useState<string | undefined>(undefined)
  const abort = useRef<AbortController | undefined>(undefined)
  // A conversation made by the first question must not reload (and wipe) the answer arriving in it.
  const made = useRef<string | null>(null)

  useEffect(() => {
    let cancelled = false
    if (made.current === conversationId && conversationId !== null) {
      made.current = null
      return
    }
    abort.current?.abort()
    setDraft('')
    setTools([])
    setChecking(false)
    setError(undefined)
    setFailedQuestion(undefined)
    if (conversationId === null) {
      setMessages([])
      setPhase('idle')
      return
    }
    setPhase('loading')
    setMessages([])
    api
      .getConversationMessages(investigationId, conversationId)
      .then((rows) => {
        if (cancelled) return
        const parsed = rows.map(toChatMessage)
        addExtra(parsed.flatMap((p) => p.evidence))
        setMessages(parsed.map((p) => p.message))
        setPhase('idle')
      })
      .catch((e: unknown) => {
        if (cancelled) return
        setError(e instanceof Error ? e.message : 'The conversation could not be loaded.')
        setPhase('idle')
      })
    return () => {
      cancelled = true
    }
  }, [investigationId, conversationId, addExtra])

  useEffect(() => () => abort.current?.abort(), [])

  const send = useCallback(
    async (raw: string) => {
      const text = raw.trim()
      if (!text || phase !== 'idle') return
      const local: ChatMessage = { id: `local-${Date.now()}`, role: 'user', content: text, citations: [], warnings: [], tools: [], createdAt: new Date().toISOString() }
      setMessages((cur) => [...cur, local])
      setDraft('')
      setTools([])
      setError(undefined)
      setFailedQuestion(undefined)
      setPhase('answering')
      const controller = new AbortController()
      abort.current = controller

      let target = conversationId
      if (target === null) {
        try {
          target = await ensure()
          made.current = target
        } catch (e) {
          setError(e instanceof Error ? e.message : 'The conversation could not be started.')
          setFailedQuestion(text)
          setMessages((cur) => cur.filter((m) => m.id !== local.id))
          setPhase('idle')
          return
        }
      }

      streamChat(
        investigationId,
        target,
        text,
        (ev) => {
          if (ev.event === 'user_message') {
            const stored = toChatMessage(ev.data).message
            setMessages((cur) => cur.map((m) => (m.id === local.id ? stored : m)))
          } else if (ev.event === 'delta') {
            setDraft((d) => d + ev.data.text)
          } else if (ev.event === 'turn_end') {
            // Text written before a search is thinking aloud, not the answer.
            if (ev.data.tool_calls) setDraft('')
          } else if (ev.event === 'checking') {
            setChecking(true)
          } else if (ev.event === 'tool') {
            setTools((t) => [...t, toChatTool(ev.data)])
          } else if (ev.event === 'done') {
            const { message, evidence } = toChatMessage(ev.data.message)
            addExtra(evidence)
            setMessages((cur) => [...cur, message])
            setDraft('')
            setTools([])
            setChecking(false)
          } else if (ev.event === 'error') {
            setError(ev.data.message)
            setFailedQuestion(text)
            setDraft('')
          }
        },
        controller.signal,
      )
        .catch((e: unknown) => {
          setError(e instanceof Error ? e.message : 'The assistant could not answer.')
          setFailedQuestion(text)
          setMessages((cur) => cur.filter((m) => m.id !== local.id))
          setDraft('')
        })
        .finally(() => {
          if (abort.current === controller) abort.current = undefined
          setChecking(false)
          setPhase('idle')
          onTurnEnd()
        })
    },
    [investigationId, conversationId, ensure, onTurnEnd, phase, addExtra],
  )

  const retry = useCallback(() => {
    if (failedQuestion) send(failedQuestion)
  }, [failedQuestion, send])

  return { messages, draft, tools, checking, phase, error, failedQuestion, send, retry }
}
