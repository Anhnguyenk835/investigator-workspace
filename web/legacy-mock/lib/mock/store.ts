import {
  seedActions,
  seedCommitments,
  seedContradictions,
  seedFindings,
  seedGaps,
  seedInvestigations,
  seedTimeline,
} from '@/data/mockInvestigations'
import { isSupported, seedActivity, seedConnectors, seedSyncJobs } from '@/data/mockConnectors'
import { readJson, removeKey, writeJson } from '@/lib/storage'
import type { ActivityEvent, ActivityKind, MockState } from '@/types/investigator'

const STORAGE_KEY = 'investigator.demo.state'
const SCHEMA_VERSION = 1

export const CURRENT_USER = 'Alex Morgan'

export const RUN_STAGES = [
  'Identifying relevant records',
  'Searching connected sources',
  'Reconstructing timeline',
  'Checking commitments',
  'Reviewing gaps and conflicts',
  'Preparing findings',
] as const

export const SYNC_STAGES = [
  'Connecting',
  'Fetching records',
  'Indexing',
  'Verifying access',
  'Completed',
] as const

const TICK_MS = 900

export const clone = <T>(value: T): T => structuredClone(value)

export function createSeedState(): MockState {
  return dropUnsupported(clone({
    schemaVersion: SCHEMA_VERSION,
    investigations: seedInvestigations,
    findings: seedFindings,
    timeline: seedTimeline,
    commitments: seedCommitments,
    gaps: seedGaps,
    contradictions: seedContradictions,
    actions: seedActions,
    drafts: [],
    connectors: seedConnectors,
    syncJobs: seedSyncJobs,
    activity: seedActivity,
    settings: {
      workspaceName: 'Demo workspace',
      timezone: 'UTC',
      simulateApiFailure: false,
    },
  }))
}

const COLLECTIONS = [
  'investigations',
  'findings',
  'timeline',
  'commitments',
  'gaps',
  'contradictions',
  'actions',
  'drafts',
  'connectors',
  'syncJobs',
  'activity',
] as const

function isValidState(value: unknown): value is MockState {
  if (typeof value !== 'object' || value === null) return false
  const v = value as Record<string, unknown>
  if (v.schemaVersion !== SCHEMA_VERSION) return false
  if (!COLLECTIONS.every((k) => Array.isArray(v[k]))) return false
  const s = v.settings as Record<string, unknown> | undefined
  return (
    typeof s === 'object' &&
    s !== null &&
    typeof s.workspaceName === 'string' &&
    typeof s.timezone === 'string' &&
    typeof s.simulateApiFailure === 'boolean'
  )
}

/** Providers that are only "coming soon" carry no connection, coverage or history. Idempotent, so stored state is cleaned too. */
function dropUnsupported(s: MockState): MockState {
  for (const c of s.connectors) {
    if (!isSupported(c.provider)) {
      c.status = 'not_connected'
      c.accountLabel = undefined
      c.workspaceLabel = undefined
      c.errorMessage = undefined
      c.lastSuccessfulSyncAt = undefined
      c.indexedRecordCount = 0
    }
  }
  s.syncJobs = s.syncJobs.filter((j) => isSupported(j.connectorId))
  s.activity = s.activity.filter((a) => a.relatedType !== 'connector' || !a.relatedId || isSupported(a.relatedId as never))
  for (const i of s.investigations) {
    i.selectedProviders = i.selectedProviders.filter(isSupported)
    i.coverage = i.coverage.filter((c) => isSupported(c.provider))
  }
  return s
}

function load(): MockState {
  const stored = readJson(STORAGE_KEY)
  if (stored !== undefined && !isValidState(stored)) removeKey(STORAGE_KEY)
  return dropUnsupported(isValidState(stored) ? stored : createSeedState())
}

let state: MockState = load()
const listeners = new Set<() => void>()
let timer: ReturnType<typeof setInterval> | undefined
let tickHandler: (s: MockState) => void = () => {}

export const getState = (): MockState => state

export function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function hasActiveJobs(s: MockState): boolean {
  return (
    s.investigations.some((i) => i.job !== undefined) ||
    s.syncJobs.some((j) => j.status === 'running' || j.status === 'queued')
  )
}

function commit(): void {
  writeJson(STORAGE_KEY, state)
  listeners.forEach((l) => l())
  ensureTicker()
}

/** The single entry point for changing mock state. Persists and notifies subscribers. */
export function mutate<T>(fn: (draft: MockState) => T): T {
  const result = fn(state)
  commit()
  return result
}

export function replaceState(next: MockState): void {
  state = next
  commit()
}

/** One shared scheduler advances every simulated job; no per-page timers. */
export function registerTickHandler(handler: (s: MockState) => void): void {
  tickHandler = handler
}

function ensureTicker(): void {
  if (hasActiveJobs(state)) {
    if (timer === undefined) {
      timer = setInterval(() => {
        tickHandler(state)
        commit()
      }, TICK_MS)
    }
  } else if (timer !== undefined) {
    clearInterval(timer)
    timer = undefined
  }
}

export function resumeJobs(): void {
  ensureTicker()
}

export function nowIso(): string {
  return new Date().toISOString()
}

export function newId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`
}

export function logActivity(
  s: MockState,
  event: Omit<ActivityEvent, 'id' | 'at' | 'actor' | 'outcome'> & {
    kind: ActivityKind
    actor?: string
    outcome?: ActivityEvent['outcome']
  },
): void {
  s.activity.push({
    ...event,
    id: newId('act'),
    at: nowIso(),
    actor: event.actor ?? CURRENT_USER,
    outcome: event.outcome ?? 'success',
  })
  if (s.activity.length > 400) s.activity.splice(0, s.activity.length - 400)
}
