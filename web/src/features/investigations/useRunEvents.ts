import { useEffect, useRef, useState } from 'react'
import { eventsUrl } from '@/api/client'
import type { SourceProvider } from '@/types/investigator'
import { PROVIDER_FOR_SOURCE } from '@/lib/providers'

export interface LogEntry {
  id: number
  kind: 'step' | 'tool' | 'error'
  label: string
  /** Short facts about the step, such as record counts. */
  detail?: string
  provider?: SourceProvider
  at?: string
}

const KINDS = ['run', 'step', 'tool', 'status', 'error', 'done'] as const

/** Steps worth refreshing the page for: their results were saved when they finished. */
const SAVED_AFTER = new Set([
  'retrieve_evidence',
  'normalize_dedupe',
  'assess_evidence',
  'analyze_evidence',
  'synthesize_findings',
  'validate_claims',
  'recommend_actions',
])

const COUNT_LABELS: [string, string][] = [
  ['records', 'records'],
  ['timeline_events', 'timeline events'],
  ['commitments', 'commitments'],
  ['blockers', 'blockers'],
  ['contradictions', 'contradictions'],
  ['gaps', 'gaps'],
  ['findings', 'findings'],
  ['actions', 'actions'],
]

function describe(data: Record<string, unknown>): string | undefined {
  const parts: string[] = []
  const queries = data.queries
  if (Array.isArray(queries) && queries.length > 0) parts.push(`queries: ${queries.map(String).join(', ')}`)
  for (const [key, label] of COUNT_LABELS) {
    const n = data[key]
    if (typeof n === 'number') parts.push(`${n} ${label}`)
  }
  return parts.length > 0 ? parts.join(' · ') : undefined
}

/** What a finished search says, in plain words. Coverage statuses come from the backend. */
export function toolDetail(data: Record<string, unknown>): string {
  const status = String(data.status ?? '')
  const records = Number(data.records ?? 0)
  const fresh = Number(data.new_records ?? 0)
  if (['searched', 'partial', 'no_matches', 'cached'].includes(status)) {
    const found = records === 0 ? 'no matching records' : `${records} ${records === 1 ? 'record' : 'records'}${fresh > 0 ? `, ${fresh} new` : ''}`
    return status === 'partial' ? `${found} (not fully searched)` : status === 'cached' ? `${found} (already searched)` : found
  }
  return status.replaceAll('_', ' ') || 'finished'
}

export interface RunLog {
  entries: LogEntry[]
  /** The stream reached its end for this run. */
  ended: boolean
}

/**
 * Follows a run's progress over Server-Sent Events while `active`. Each run replaces the
 * previous log. `onSaved` is called when the server has saved new partial results, so the
 * page can show them without waiting for the run to finish.
 */
export function useRunEvents(id: string, active: boolean, onSaved: () => void): RunLog {
  const [log, setLog] = useState<RunLog>({ entries: [], ended: false })
  const saved = useRef(onSaved)
  saved.current = onSaved

  useEffect(() => {
    if (!active) return
    const source = new EventSource(eventsUrl(id))
    const onEvent = (kind: (typeof KINDS)[number]) => (e: MessageEvent<string>) => {
      let data: Record<string, unknown>
      try {
        data = JSON.parse(e.data) as Record<string, unknown>
      } catch {
        return
      }
      const eventId = Number(e.lastEventId) || 0
      if (kind === 'run') {
        setLog({ entries: [], ended: false }) // a new run: forget the previous one
        return
      }
      if (kind === 'step') {
        const node = String(data.node ?? '')
        setLog((cur) => ({
          ...cur,
          entries: [...cur.entries, { id: eventId, kind: 'step', label: String(data.label ?? node), detail: describe(data), at: String(data.at ?? '') }],
        }))
        if (SAVED_AFTER.has(node)) saved.current()
      } else if (kind === 'tool') {
        const provider = PROVIDER_FOR_SOURCE[String(data.source ?? '')]
        setLog((cur) => ({
          ...cur,
          entries: [...cur.entries, { id: eventId, kind: 'tool', label: 'Searched', provider, detail: toolDetail(data), at: String(data.at ?? '') }],
        }))
      } else if (kind === 'error') {
        setLog((cur) => ({ ...cur, entries: [...cur.entries, { id: eventId, kind: 'error', label: String(data.message ?? 'The run failed') }] }))
      } else if (kind === 'done' || kind === 'status') {
        saved.current()
      }
    }
    const listeners = KINDS.map((k) => [k, onEvent(k)] as const)
    for (const [k, fn] of listeners) source.addEventListener(k, fn as EventListener)
    // The server closes the stream with `end` once everything has been sent.
    const onEnd = () => {
      source.close()
      setLog((cur) => ({ ...cur, ended: true }))
      saved.current()
    }
    source.addEventListener('end', onEnd)
    return () => {
      for (const [k, fn] of listeners) source.removeEventListener(k, fn as EventListener)
      source.removeEventListener('end', onEnd)
      source.close()
    }
  }, [id, active])

  return log
}
