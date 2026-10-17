import { useCallback, useEffect, useRef, useState } from 'react'
import type { AsyncStatus } from '@/types'

export interface QueryResult<T> {
  data: T | undefined
  status: AsyncStatus
  error: string | undefined
  /** Refetch without showing the loading state (after a change, or to check progress). */
  refresh: () => void
  reload: () => void
}

interface QueryOptions<T> {
  /** Milliseconds to wait before refetching after each response; return false to stop. */
  pollMs?: (data: T) => number | false
}

/**
 * Loads data from the API. A background refetch that fails keeps what is on screen
 * and the next poll tries again; only the first load shows an error state.
 */
export function useApiQuery<T>(
  fetcher: () => Promise<T>,
  deps: readonly unknown[],
  options: QueryOptions<T> = {},
): QueryResult<T> {
  const [data, setData] = useState<T | undefined>(undefined)
  const [status, setStatus] = useState<AsyncStatus>('loading')
  const [error, setError] = useState<string | undefined>(undefined)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  const optionsRef = useRef(options)
  optionsRef.current = options
  const requestId = useRef(0)
  const hasData = useRef(false)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const run = useCallback(async (initial: boolean) => {
    clearTimeout(timer.current)
    const id = ++requestId.current
    if (initial) {
      setStatus('loading')
      setError(undefined)
    }
    let next: number | false = false
    try {
      const result = await fetcherRef.current()
      if (id !== requestId.current) return
      hasData.current = true
      setData(result)
      setError(undefined)
      setStatus('success')
      next = optionsRef.current.pollMs?.(result) ?? false
    } catch (e) {
      if (id !== requestId.current) return
      if (initial || !hasData.current) {
        setError(e instanceof Error ? e.message : 'Something went wrong.')
        setStatus('error')
        return
      }
      next = optionsRef.current.pollMs ? 5000 : false // keep the screen, try again later
    }
    if (next !== false) timer.current = setTimeout(() => void run(false), next)
  }, [])

  useEffect(() => {
    hasData.current = false
    void run(true)
    return () => {
      requestId.current += 1
      clearTimeout(timer.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run, ...deps])

  const reload = useCallback(() => void run(true), [run])
  const refresh = useCallback(() => void run(false), [run])

  return { data, status, error, reload, refresh }
}
