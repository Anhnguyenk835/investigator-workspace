import { type ReactNode } from 'react'
import { Button } from '@/components/ui/Button'
import { Icon, type IconName } from '@/components/ui/Icon'
import { cn } from '@/lib/cn'

export function EmptyState({
  title,
  body,
  icon = 'database',
  actions,
  className,
}: {
  title: string
  body: ReactNode
  icon?: IconName
  actions?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-col items-start gap-3 border border-dashed border-line-subtle bg-surface px-6 py-10', className)}>
      <Icon name={icon} className="size-5 text-ink-muted" />
      <div>
        <p className="text-body font-medium text-ink">{title}</p>
        <p className="mt-1 max-w-prose text-caption text-ink-muted">{body}</p>
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </div>
  )
}

export function ErrorState({
  title = 'This could not be loaded',
  message,
  onRetry,
  className,
}: {
  title?: string
  message?: string
  onRetry?: () => void
  className?: string
}) {
  return (
    <div role="alert" className={cn('flex flex-col items-start gap-3 border border-danger bg-surface px-6 py-8', className)}>
      <Icon name="alert" className="size-5 text-danger" />
      <div>
        <p className="text-body font-medium text-ink">{title}</p>
        {message ? <p className="mt-1 max-w-prose text-caption text-ink-muted">{message}</p> : null}
      </div>
      {onRetry ? (
        <Button size="sm" variant="outline" onClick={onRetry}>
          <Icon name="refresh" /> Retry
        </Button>
      ) : null}
    </div>
  )
}
