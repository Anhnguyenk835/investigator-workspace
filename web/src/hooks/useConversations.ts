import { useCallback, useEffect, useState } from 'react'
import { api } from '@/api/client'
import { toConversation } from '@/api/adapt'
import { readJson, writeJson } from '@/lib/storage'
import type { Conversation } from '@/types/investigator'

const key = (investigationId: string) => `investigator.conversation.${investigationId}`

export interface Conversations {
  list: Conversation[]
  loading: boolean
  error?: string
  /** The open conversation; null is a new chat that does not exist until its first question. */
  selected: string | null
  select: (id: string) => void
  startNew: () => void
  /** Makes the conversation a new chat needs, selects it and returns its id. */
  create: () => Promise<string>
  rename: (id: string, title: string) => Promise<void>
  remove: (id: string) => Promise<boolean>
  refresh: () => Promise<void>
}

/** The conversations about one investigation, and which one is open (remembered per investigation). */
export function useConversations(investigationId: string): Conversations {
  const [list, setList] = useState<Conversation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | undefined>(undefined)
  const [selected, setSelected] = useState<string | null>(null)

  const choose = useCallback(
    (id: string | null) => {
      setSelected(id)
      writeJson(key(investigationId), id)
    },
    [investigationId],
  )

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(undefined)
    setSelected(null)
    api
      .listConversations(investigationId)
      .then((rows) => {
        if (cancelled) return
        const found = rows.map(toConversation)
        setList(found)
        const remembered = readJson(key(investigationId))
        const open = typeof remembered === 'string' && found.some((c) => c.id === remembered) ? remembered : (found[0]?.id ?? null)
        setSelected(open)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'The conversations could not be loaded.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [investigationId])

  const refresh = useCallback(async () => {
    try {
      setList((await api.listConversations(investigationId)).map(toConversation))
    } catch {
      // The list is a convenience; the open conversation keeps working.
    }
  }, [investigationId])

  const create = useCallback(async () => {
    const made = toConversation(await api.createConversation(investigationId))
    setList((cur) => [made, ...cur])
    choose(made.id)
    return made.id
  }, [investigationId, choose])

  const rename = useCallback(
    async (id: string, title: string) => {
      const next = toConversation(await api.renameConversation(investigationId, id, title))
      setList((cur) => cur.map((c) => (c.id === id ? next : c)))
    },
    [investigationId],
  )

  const remove = useCallback(
    async (id: string) => {
      try {
        await api.deleteConversation(investigationId, id)
      } catch (e) {
        setError(e instanceof Error ? e.message : 'The conversation could not be deleted.')
        return false
      }
      setList((cur) => {
        const rest = cur.filter((c) => c.id !== id)
        if (selected === id) choose(rest[0]?.id ?? null)
        return rest
      })
      return true
    },
    [investigationId, selected, choose],
  )

  return { list, loading, error, selected, select: choose, startNew: () => choose(null), create, rename, remove, refresh }
}
