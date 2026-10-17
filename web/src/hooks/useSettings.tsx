import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { formatDate, formatDateTime, formatStamp, shortDate } from '@/lib/format'
import { readJson, writeJson } from '@/lib/storage'
import type { TimestampPrecision, WorkspaceSettings } from '@/types/investigator'

const TIMEZONE_KEY = 'investigator.timezone'

function initialTimezone(): string {
  const saved = readJson(TIMEZONE_KEY)
  if (typeof saved === 'string' && saved) return saved
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

interface SettingsValue extends WorkspaceSettings {
  setTimezone: (timezone: string) => void
}

const SettingsContext = createContext<SettingsValue | null>(null)

/** Display preferences kept in this browser. Nothing here is sent to the server. */
export function SettingsProvider({ children }: { children: ReactNode }) {
  const [timezone, setZone] = useState(initialTimezone)
  const setTimezone = useCallback((next: string) => {
    setZone(next)
    writeJson(TIMEZONE_KEY, next)
  }, [])
  const value = useMemo(() => ({ timezone, setTimezone }), [timezone, setTimezone])
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useSettings(): SettingsValue {
  const ctx = useContext(SettingsContext)
  if (!ctx) throw new Error('useSettings must be used inside SettingsProvider')
  return ctx
}

/** Date formatters bound to the chosen timezone. */
// eslint-disable-next-line react-refresh/only-export-components
export function useFormat() {
  const { timezone } = useSettings()
  return useMemo(
    () => ({
      timezone,
      dateTime: (iso?: string) => formatDateTime(iso, timezone),
      date: (iso?: string) => formatDate(iso, timezone),
      short: (iso?: string) => shortDate(iso, timezone),
      stamp: (iso: string | undefined, precision: TimestampPrecision) => formatStamp(iso, precision, timezone),
    }),
    [timezone],
  )
}
