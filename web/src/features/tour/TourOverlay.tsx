import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Button } from '@/components/ui'
import type { Placement, TourStep } from '@/features/tour/tours'

const GAP = 12
const MARGIN = 12
const PAD = 4
const WAIT_MS = 3000

interface Box {
  top: number
  left: number
  width: number
  height: number
}

/** The first match that is actually on screen (the sidebar exists twice: pinned and drawer). */
function visible(selector: string): HTMLElement | null {
  for (const el of document.querySelectorAll<HTMLElement>(selector)) {
    const r = el.getBoundingClientRect()
    if (r.width > 0 && r.height > 0) return el
  }
  return null
}

function boxOf(el: HTMLElement): Box {
  const r = el.getBoundingClientRect()
  return { top: r.top - PAD, left: r.left - PAD, width: r.width + PAD * 2, height: r.height + PAD * 2 }
}

/** Follows the element a step points at: waits for it, scrolls it into view, tracks its box. */
function useTarget(selector: string | undefined, onMissing: () => void, optional: boolean) {
  const [box, setBox] = useState<Box | null>(null)
  const [missing, setMissing] = useState(false)
  const missed = useRef(onMissing)
  useEffect(() => {
    missed.current = onMissing
  })

  useEffect(() => {
    if (!selector) return
    let el: HTMLElement | null = null
    let observer: ResizeObserver | undefined
    const update = () => el && setBox(boxOf(el))
    const attach = (found: HTMLElement) => {
      el = found
      found.scrollIntoView({ block: 'center', inline: 'nearest' })
      update()
      observer = new ResizeObserver(update)
      observer.observe(found)
      window.addEventListener('scroll', update, true)
      window.addEventListener('resize', update)
    }
    const first = visible(selector)
    let poll: number | undefined
    let giveUp: number | undefined
    if (first) attach(first)
    else {
      poll = window.setInterval(() => {
        const found = visible(selector)
        if (!found) return
        window.clearInterval(poll)
        window.clearTimeout(giveUp)
        attach(found)
      }, 100)
      giveUp = window.setTimeout(() => {
        window.clearInterval(poll)
        if (optional) missed.current()
        else setMissing(true)
      }, WAIT_MS)
    }
    return () => {
      window.clearInterval(poll)
      window.clearTimeout(giveUp)
      observer?.disconnect()
      window.removeEventListener('scroll', update, true)
      window.removeEventListener('resize', update)
    }
  }, [selector, optional])

  return { box, missing }
}

function place(box: Box, card: { width: number; height: number }, want: Placement) {
  const vw = window.innerWidth
  const vh = window.innerHeight
  const room = {
    right: vw - (box.left + box.width) - GAP - MARGIN,
    left: box.left - GAP - MARGIN,
    bottom: vh - (box.top + box.height) - GAP - MARGIN,
    top: box.top - GAP - MARGIN,
  }
  const need = { right: card.width, left: card.width, bottom: card.height, top: card.height }
  const opposite: Record<Placement, Placement> = { right: 'left', left: 'right', bottom: 'top', top: 'bottom' }
  const order: Placement[] = [want, opposite[want], 'bottom', 'top', 'right', 'left']
  const side = order.find((p) => room[p] >= need[p]) ?? 'bottom'
  let top: number
  let left: number
  if (side === 'right' || side === 'left') {
    top = box.top + box.height / 2 - card.height / 2
    left = side === 'right' ? box.left + box.width + GAP : box.left - GAP - card.width
  } else {
    left = box.left + box.width / 2 - card.width / 2
    top = side === 'bottom' ? box.top + box.height + GAP : box.top - GAP - card.height
  }
  return {
    top: Math.min(Math.max(top, MARGIN), Math.max(vh - card.height - MARGIN, MARGIN)),
    left: Math.min(Math.max(left, MARGIN), Math.max(vw - card.width - MARGIN, MARGIN)),
  }
}

interface Props {
  step: TourStep
  index: number
  total: number
  onBack: () => void
  onNext: () => void
  onSkip: () => void
  onMissing: () => void
}

export function TourOverlay({ step, index, total, onBack, onNext, onSkip, onMissing }: Props) {
  const { box, missing } = useTarget(step.target, onMissing, Boolean(step.optional))
  const cardRef = useRef<HTMLDivElement>(null)
  const nextRef = useRef<HTMLButtonElement>(null)
  const [size, setSize] = useState({ width: 360, height: 200 })
  const [, tick] = useState(0)
  const waiting = Boolean(step.target) && !box && !missing
  const spotlight = box && !missing
  const last = index === total - 1

  useLayoutEffect(() => {
    const el = cardRef.current
    if (el) setSize({ width: el.offsetWidth, height: el.offsetHeight })
  }, [step.id, box?.top, box?.left])

  useEffect(() => {
    const onResize = () => tick((n) => n + 1)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  // Focus the card, give it back on close.
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    return () => previous?.focus?.()
  }, [])
  useEffect(() => {
    if (!waiting) nextRef.current?.focus()
  }, [waiting, step.id])

  const next = () => {
    if (step.clickOnNext && step.target) visible(step.target)?.click()
    onNext()
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        onSkip()
      } else if (e.key === 'ArrowRight') next()
      else if (e.key === 'ArrowLeft' && index > 0) onBack()
      else if (e.key === 'Tab') {
        const items = [...(cardRef.current?.querySelectorAll<HTMLElement>('button:not([disabled])') ?? [])]
        if (items.length === 0) return
        const firstEl = items[0]
        const lastEl = items[items.length - 1]
        if (e.shiftKey && document.activeElement === firstEl) {
          e.preventDefault()
          lastEl.focus()
        } else if (!e.shiftKey && document.activeElement === lastEl) {
          e.preventDefault()
          firstEl.focus()
        }
      }
    }
    document.addEventListener('keydown', onKey, true)
    return () => document.removeEventListener('keydown', onKey, true)
  })

  // On a narrow screen the card spans the width, above or below what it points at.
  const narrow = window.innerWidth < 640
  let style: React.CSSProperties
  if (spotlight && box) {
    if (narrow) {
      const below = box.top + box.height / 2 < window.innerHeight / 2
      style = { left: MARGIN, right: MARGIN, ...(below ? { bottom: MARGIN } : { top: MARGIN }) }
    } else {
      style = place(box, size, step.placement ?? 'bottom')
    }
  } else {
    style = { top: '50%', left: '50%', transform: 'translate(-50%, -50%)' }
  }

  return createPortal(
    <div className="fixed inset-0 z-[100]">
      {spotlight && box ? (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed outline-2 outline-primary transition-[top,left,width,height] duration-200 motion-reduce:transition-none"
          style={{ ...box, boxShadow: '0 0 0 9999px color-mix(in srgb, var(--color-ink) 55%, transparent)' }}
        />
      ) : (
        <div aria-hidden="true" className="absolute inset-0 bg-ink/55" />
      )}
      {/* The page behind is inert while a step is open: Next does the navigating. */}
      <div className="absolute inset-0" aria-hidden="true" />
      <div
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        aria-describedby="tour-body"
        style={style}
        className={`fixed flex w-[min(22.5rem,calc(100vw-1.5rem))] flex-col gap-3 border border-line bg-surface p-4 shadow-lg ${narrow && spotlight ? 'w-auto' : ''}`}
      >
        <p className="text-overline uppercase text-ink-muted">
          Step {index + 1} of {total}
        </p>
        <div className="flex flex-col gap-1">
          <h2 id="tour-title" className="text-body font-medium text-ink">
            {step.title}
          </h2>
          <p id="tour-body" className="text-caption text-ink-muted">
            {waiting ? 'Loading…' : step.body}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={onSkip}>
            Skip tour
          </Button>
          <span className="flex-1" />
          {index > 0 ? (
            <Button variant="outline" size="sm" onClick={onBack}>
              Back
            </Button>
          ) : null}
          <Button ref={nextRef} size="sm" onClick={next} disabled={waiting}>
            {last ? 'Done' : 'Next'}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
