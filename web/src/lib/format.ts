import type { TimestampPrecision } from '@/types/investigator'

export function formatDateTime(iso: string | undefined, timeZone: string): string {
  if (!iso) return 'Unknown'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 'Unknown'
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZone,
    timeZoneName: 'short',
  }).format(d)
}

export function formatDate(iso: string | undefined, timeZone: string): string {
  if (!iso) return 'Unknown'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 'Unknown'
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    // Date-only values are stored at 00:00 UTC; never shift them across a day boundary.
    timeZone,
  }).format(d)
}

export function formatStamp(
  iso: string | undefined,
  precision: TimestampPrecision,
  timeZone: string,
): string {
  if (precision === 'unknown') return 'Time unknown'
  if (precision === 'date_only') return `${formatDate(iso, 'UTC')} (date only)`
  return formatDateTime(iso, timeZone)
}

export function shortDate(iso: string | undefined, timeZone: string): string {
  if (!iso) return 'Unknown'
  return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', timeZone }).format(
    new Date(iso),
  )
}

export function formatDuration(startIso: string, endIso: string | undefined): string {
  if (!endIso) return '—'
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime()
  if (!Number.isFinite(ms) || ms < 0) return '—'
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return `${m}m ${String(s % 60).padStart(2, '0')}s`
}

export function relativeTime(iso: string | undefined, now = Date.now()): string {
  if (!iso) return 'Never'
  const diff = now - new Date(iso).getTime()
  if (!Number.isFinite(diff)) return 'Unknown'
  const min = Math.round(diff / 60000)
  if (min < 1) return 'Just now'
  if (min < 60) return `${min} min ago`
  const hr = Math.round(min / 60)
  if (hr < 24) return `${hr} hr ago`
  const day = Math.round(hr / 24)
  if (day < 30) return `${day} d ago`
  return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).format(
    new Date(iso),
  )
}

export function formatCount(n: number): string {
  return new Intl.NumberFormat('en-US').format(n)
}

export const TIMEZONES = [
  'UTC',
  'America/New_York',
  'America/Chicago',
  'America/Los_Angeles',
  'Europe/London',
  'Europe/Berlin',
  'Asia/Ho_Chi_Minh',
  'Asia/Singapore',
  'Australia/Sydney',
] as const
