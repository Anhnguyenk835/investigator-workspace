import { type ReactNode, useEffect, useId, useRef } from 'react'
import { createPortal } from 'react-dom'
import { cn } from '@/lib/cn'
import { Button } from '@/components/ui/Button'
import { Icon } from '@/components/ui/Icon'

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

interface OverlayProps {
  open: boolean
  onClose: () => void
  title: string
  description?: string
  children: ReactNode
  footer?: ReactNode
  variant: 'dialog' | 'drawer'
  width?: string
}

/** Modal surface with focus management, Escape to close and scroll lock. */
function Overlay({ open, onClose, title, description, children, footer, variant, width }: OverlayProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const closeRef = useRef(onClose)
  closeRef.current = onClose

  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    const panel = panelRef.current
    const first = panel?.querySelector<HTMLElement>('[data-autofocus]') ?? panel?.querySelector<HTMLElement>(FOCUSABLE)
    first?.focus()
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        closeRef.current()
        return
      }
      if (e.key !== 'Tab' || !panel) return
      const items = [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)]
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
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
      previous?.focus?.()
    }
  }, [open])

  if (!open) return null

  return createPortal(
    <div className={cn('fixed inset-0 z-50 flex', variant === 'dialog' ? 'items-center justify-center p-4' : 'justify-end')}>
      <div className="absolute inset-0 bg-ink/40" onClick={onClose} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={cn(
          'relative flex max-h-full flex-col border border-line bg-surface shadow-lg',
          variant === 'dialog' ? 'w-full max-w-lg' : 'h-full w-full sm:border-y-0 sm:border-r-0',
          variant === 'drawer' && (width ?? 'sm:max-w-xl'),
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-line-subtle px-5 py-4">
          <div className="min-w-0">
            <h2 id={titleId} className="text-heading text-ink">
              {title}
            </h2>
            {description ? <p className="mt-1 text-caption text-ink-muted">{description}</p> : null}
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
            <Icon name="x" />
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer ? <div className="flex flex-wrap justify-end gap-2 border-t border-line-subtle px-5 py-3">{footer}</div> : null}
      </div>
    </div>,
    document.body,
  )
}

export type DialogProps = Omit<OverlayProps, 'variant' | 'width'>
export const Dialog = (props: DialogProps) => <Overlay {...props} variant="dialog" />
export const Drawer = (props: Omit<OverlayProps, 'variant'>) => <Overlay {...props} variant="drawer" />

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  tone = 'danger',
  busy,
  onConfirm,
  onCancel,
}: {
  open: boolean
  title: string
  body: ReactNode
  confirmLabel: string
  tone?: 'danger' | 'solid'
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <Dialog
      open={open}
      onClose={onCancel}
      title={title}
      footer={
        <>
          <Button variant="outline" onClick={onCancel} data-autofocus>
            Cancel
          </Button>
          <Button variant={tone} onClick={onConfirm} disabled={busy}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="text-body text-ink">{body}</div>
    </Dialog>
  )
}
