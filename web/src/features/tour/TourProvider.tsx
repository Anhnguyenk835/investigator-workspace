import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { useAuth } from '@/features/auth/AuthProvider'
import { TourOverlay } from '@/features/tour/TourOverlay'
import { pageOf, TOURS, type TourId, type Variant } from '@/features/tour/tours'
import { readJson, removeKey, writeJson } from '@/lib/storage'

/** Bump the version to show updated guides to people who have seen the old ones. */
const KEY = (variant: Variant, id: TourId) => `investigator.tour.v2.${variant}.${id}`
export const NAV_EVENT = 'tour:nav'
const PAGES = Object.keys(TOURS) as TourId[]

interface TourApi {
  /** Whether a guide is on screen. */
  running: boolean
  /** The open page has its own guide. */
  hasGuide: boolean
  /** Show the guide of the page that is open (the introduction on a page without one). */
  startHere: () => void
  /** Show the introduction. */
  startIntro: () => void
  /** Show every page guide again, the next time each page is opened. */
  resetPages: () => void
}

const TourContext = createContext<TourApi | null>(null)

function seen(variant: Variant, id: TourId): boolean {
  const v = readJson(KEY(variant, id))
  return typeof v === 'object' && v !== null && 'status' in v
}

function remember(variant: Variant, id: TourId, status: 'done' | 'skipped') {
  writeJson(KEY(variant, id), { status, at: new Date().toISOString() })
}

export function TourProvider({ children }: { children: ReactNode }) {
  const { mode } = useAuth()
  const location = useLocation()
  const variant: Variant | undefined = mode === 'demo' ? 'demo' : mode === 'user' || mode === 'disabled' ? 'user' : undefined
  const [run, setRun] = useState<{ id: TourId; index: number } | null>(null)
  const direction = useRef<1 | -1>(1)
  const steps = run ? TOURS[run.id] : []
  const step = run ? steps[run.index] : undefined
  const page = pageOf(location.pathname)

  const close = useCallback(
    (status: 'done' | 'skipped') => {
      if (variant && run) remember(variant, run.id, status)
      window.dispatchEvent(new CustomEvent(NAV_EVENT, { detail: false }))
      setRun(null)
    },
    [variant, run],
  )

  const go = useCallback(
    (to: number) => {
      if (!run) return
      if (to >= TOURS[run.id].length) return close('done')
      if (to < 0) return
      direction.current = to >= run.index ? 1 : -1
      setRun({ id: run.id, index: to })
    },
    [run, close],
  )

  // The first time somebody is in the app, the introduction; after it, a page's guide the
  // first time that page is opened. Only one guide at a time, and never over a running one.
  useEffect(() => {
    if (!variant || run) return
    const next: TourId | undefined = !seen(variant, 'intro') ? 'intro' : page && !seen(variant, page) ? page : undefined
    if (!next) return
    const t = window.setTimeout(() => setRun({ id: next, index: 0 }), 700)
    return () => window.clearTimeout(t)
  }, [variant, run, page, location.pathname])

  useEffect(() => {
    window.dispatchEvent(new CustomEvent(NAV_EVENT, { detail: Boolean(step?.nav) }))
  }, [step?.id, step?.nav])

  const api = useMemo<TourApi>(
    () => ({
      running: run !== null,
      hasGuide: page !== undefined,
      startHere: () => setRun({ id: page ?? 'intro', index: 0 }),
      startIntro: () => setRun({ id: 'intro', index: 0 }),
      resetPages: () => {
        if (!variant) return
        for (const id of PAGES) if (id !== 'intro') removeKey(KEY(variant, id))
      },
    }),
    [run, page, variant],
  )

  return (
    <TourContext.Provider value={api}>
      {children}
      {step && run && variant ? (
        <TourOverlay
          key={`${run.id}.${step.id}`}
          step={step}
          variant={variant}
          index={run.index}
          total={steps.length}
          onBack={() => go(run.index - 1)}
          onNext={() => go(run.index + 1)}
          onSkip={() => close('skipped')}
          onMissing={() => go(run.index + direction.current)}
        />
      ) : null}
    </TourContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useTour(): TourApi {
  const ctx = useContext(TourContext)
  if (!ctx) throw new Error('useTour must be used inside TourProvider')
  return ctx
}
