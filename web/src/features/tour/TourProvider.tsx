import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '@/features/auth/AuthProvider'
import { TourOverlay } from '@/features/tour/TourOverlay'
import { TOURS, type TourId } from '@/features/tour/tours'
import { readJson, writeJson } from '@/lib/storage'

/** Bump the version to show an updated tour to people who finished the old one. */
const KEY = (id: TourId) => `investigator.tour.v1.${id}`
export const NAV_EVENT = 'tour:nav'

interface TourApi {
  /** Whether a tour is on screen. */
  running: boolean
  /** Start the tour for the current mode from its first step. */
  start: () => void
}

const TourContext = createContext<TourApi | null>(null)

function seen(id: TourId): boolean {
  const v = readJson(KEY(id))
  return typeof v === 'object' && v !== null && 'status' in v
}

function remember(id: TourId, status: 'done' | 'skipped') {
  writeJson(KEY(id), { status, at: new Date().toISOString() })
}

export function TourProvider({ children }: { children: ReactNode }) {
  const { mode } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const id: TourId | undefined = mode === 'demo' ? 'demo' : mode === 'user' || mode === 'disabled' ? 'user' : undefined
  const [index, setIndex] = useState<number | null>(null)
  const direction = useRef<1 | -1>(1)
  const autoStarted = useRef(false)
  const steps = id ? TOURS[id] : []
  const step = index !== null ? steps[index] : undefined

  const close = useCallback(
    (status: 'done' | 'skipped') => {
      if (id) remember(id, status)
      window.dispatchEvent(new CustomEvent(NAV_EVENT, { detail: false }))
      setIndex(null)
    },
    [id],
  )

  const go = useCallback(
    (to: number) => {
      if (!id) return
      if (to >= TOURS[id].length) return close('done')
      if (to < 0) return
      direction.current = to >= (index ?? 0) ? 1 : -1
      setIndex(to)
    },
    [id, index, close],
  )

  // First visit: start once, on the page people land on after signing in.
  useEffect(() => {
    if (!id || autoStarted.current || location.pathname !== '/investigations') return
    autoStarted.current = true
    if (seen(id)) return
    const t = window.setTimeout(() => setIndex(0), 600)
    return () => window.clearTimeout(t)
  }, [id, location.pathname])

  // A step lives on one page; go there when the person is elsewhere.
  useEffect(() => {
    if (step?.route && location.pathname !== step.route) navigate(step.route)
    window.dispatchEvent(new CustomEvent(NAV_EVENT, { detail: Boolean(step?.nav) }))
    // Only a change of step moves the page; the person may go elsewhere while a step is open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step?.id])

  const api = useMemo<TourApi>(() => ({ running: index !== null, start: () => setIndex(0) }), [index])

  return (
    <TourContext.Provider value={api}>
      {children}
      {step && index !== null ? (
        <TourOverlay
          key={step.id}
          step={step}
          index={index}
          total={steps.length}
          onBack={() => go(index - 1)}
          onNext={() => go(index + 1)}
          onSkip={() => close('skipped')}
          onMissing={() => go(index + direction.current)}
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
