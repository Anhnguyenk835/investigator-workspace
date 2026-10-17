import { type LabelHTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

export function Label({
  className,
  ...props
}: LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn('block text-overline uppercase text-ink-muted', className)}
      {...props}
    />
  )
}
