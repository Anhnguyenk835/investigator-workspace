import { useCallback, useState } from 'react'
import { useToast } from '@/components/ui/Toast'

/** Runs a mock-API mutation, reports failures honestly, and exposes a busy flag. */
export function useRunAction() {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const run = useCallback(
    async <T,>(fn: () => Promise<T>, success?: string): Promise<T | undefined> => {
      setBusy(true)
      try {
        const result = await fn()
        if (success) toast.success(success)
        return result
      } catch (e) {
        toast.error('That did not work', e instanceof Error ? e.message : undefined)
        return undefined
      } finally {
        setBusy(false)
      }
    },
    [toast],
  )
  return { run, busy }
}
