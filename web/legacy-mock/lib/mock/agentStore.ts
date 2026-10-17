import { useSyncExternalStore } from 'react'
import { mockAgent } from '@/lib/mockAgent'
import { newId, nowIso } from '@/lib/mock/store'
import { readJson, removeKey, writeJson } from '@/lib/storage'
import type { AgentConversation, AgentMessage, AgentToolActivity } from '@/types/agent'

const KEY = 'investigator.demo.agent'
const MAX_MESSAGES = 60

export interface PendingTurn {
  text: string
  tools: AgentToolActivity[]
}
export interface FailedTurn {
  text: string
  error: string
}
interface Snapshot {
  conversations: Record<string, AgentConversation>
  pending: Record<string, PendingTurn | undefined>
  failed: Record<string, FailedTurn | undefined>
}

function isMessage(m: unknown): m is AgentMessage {
  if (typeof m !== 'object' || m === null) return false
  const x = m as Record<string, unknown>
  return (
    typeof x.id === 'string' &&
    (x.role === 'user' || x.role === 'assistant') &&
    typeof x.content === 'string' &&
    typeof x.createdAt === 'string' &&
    Array.isArray(x.evidenceIds)
  )
}

function loadConversations(): Record<string, AgentConversation> {
  const raw = readJson(KEY)
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    if (raw !== undefined) removeKey(KEY)
    return {}
  }
  const out: Record<string, AgentConversation> = {}
  for (const [invId, value] of Object.entries(raw)) {
    const v = value as Partial<AgentConversation> | null
    if (v && typeof v.id === 'string' && Array.isArray(v.messages) && v.messages.every(isMessage)) {
      out[invId] = { id: v.id, investigationId: invId, messages: v.messages, updatedAt: typeof v.updatedAt === 'string' ? v.updatedAt : nowIso() }
    }
  }
  return out
}

let snap: Snapshot = { conversations: loadConversations(), pending: {}, failed: {} }
const listeners = new Set<() => void>()

function set(next: Partial<Snapshot>, persist = false): void {
  snap = { ...snap, ...next }
  if (persist) writeJson(KEY, snap.conversations)
  listeners.forEach((l) => l())
}

const subscribe = (l: () => void) => {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

const EMPTY: AgentConversation['messages'] = []

function conversationFor(invId: string): AgentConversation {
  return snap.conversations[invId] ?? { id: `conv-${invId}-1`, investigationId: invId, messages: EMPTY, updatedAt: '' }
}

function append(invId: string, ...msgs: AgentMessage[]): void {
  const cur = conversationFor(invId)
  const messages = [...cur.messages, ...msgs].slice(-MAX_MESSAGES)
  set({ conversations: { ...snap.conversations, [invId]: { ...cur, messages, updatedAt: nowIso() } } }, true)
}

async function runTurn(invId: string, text: string): Promise<void> {
  set({ pending: { ...snap.pending, [invId]: { text, tools: [] } }, failed: { ...snap.failed, [invId]: undefined } })
  try {
    const { message } = await mockAgent.sendMessage(
      { investigationId: invId, message: text, conversationId: conversationFor(invId).id },
      (tool) => {
        const p = snap.pending[invId]
        if (p) set({ pending: { ...snap.pending, [invId]: { ...p, tools: [...p.tools, tool] } } })
      },
    )
    append(invId, message)
  } catch (e) {
    set({ failed: { ...snap.failed, [invId]: { text, error: e instanceof Error ? e.message : 'The agent could not respond.' } } })
  } finally {
    set({ pending: { ...snap.pending, [invId]: undefined } })
  }
}

/** Sends a user message. Ignored while a turn is already running for this investigation. */
export function sendAgentMessage(invId: string, text: string): void {
  const clean = text.trim()
  if (!clean || snap.pending[invId]) return
  append(invId, { id: newId('msg'), role: 'user', content: clean, createdAt: nowIso(), evidenceIds: [] })
  void runTurn(invId, clean)
}

export function retryAgentTurn(invId: string): void {
  const f = snap.failed[invId]
  if (!f || snap.pending[invId]) return
  void runTurn(invId, f.text)
}

/** Starts a fresh conversation for this investigation. */
export function newAgentConversation(invId: string): void {
  if (snap.pending[invId]) return
  const cur = conversationFor(invId)
  const n = Number(cur.id.split('-').pop()) || 1
  set(
    {
      conversations: { ...snap.conversations, [invId]: { id: `conv-${invId}-${n + 1}`, investigationId: invId, messages: [], updatedAt: nowIso() } },
      failed: { ...snap.failed, [invId]: undefined },
    },
    true,
  )
}

export function clearAgentConversations(): void {
  removeKey(KEY)
  set({ conversations: {}, failed: {} })
}

export function useAgentConversation(invId: string) {
  const s = useSyncExternalStore(subscribe, () => snap)
  return { conversation: s.conversations[invId] ?? conversationFor(invId), pending: s.pending[invId], failed: s.failed[invId] }
}
