import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { Icon } from '@/components/ui/Icon'

type ToastTone = 'success' | 'danger' | 'info'
interface ToastItem {
  id: number
  tone: ToastTone
  title: string
  detail?: string
}

interface ToastApi {
  success: (title: string, detail?: string) => void
  error: (title: string, detail?: string) => void
  info: (title: string, detail?: string) => void
}

const ToastContext = createContext<ToastApi | null>(null)

const toneClass: Record<ToastTone, string> = {
  success: 'border-success',
  danger: 'border-danger',
  info: 'border-info',
}

/** Toasts report the outcome of an operation that has already been applied to mock state. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const nextId = useRef(1)

  const push = useCallback((tone: ToastTone, title: string, detail?: string) => {
    const id = nextId.current++
    setItems((cur) => [...cur.slice(-3), { id, tone, title, detail }])
    window.setTimeout(() => setItems((cur) => cur.filter((t) => t.id !== id)), tone === 'danger' ? 7000 : 4000)
  }, [])

  const api = useMemo<ToastApi>(
    () => ({
      success: (t, d) => push('success', t, d),
      error: (t, d) => push('danger', t, d),
      info: (t, d) => push('info', t, d),
    }),
    [push],
  )

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        className="pointer-events-none fixed bottom-4 right-4 z-[70] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2"
        role="status"
        aria-live="polite"
      >
        {items.map((t) => (
          <div
            key={t.id}
            className={cn('pointer-events-auto flex gap-3 border border-l-2 bg-surface px-4 py-3 shadow-lg', toneClass[t.tone])}
          >
            <Icon name={t.tone === 'danger' ? 'alert' : t.tone === 'success' ? 'check' : 'info'} className="mt-0.5 size-4 shrink-0" />
            <div className="min-w-0">
              <p className="text-caption font-medium text-ink">{t.title}</p>
              {t.detail ? <p className="text-caption text-ink-muted">{t.detail}</p> : null}
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast(): ToastApi {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used inside ToastProvider')
  return ctx
}
