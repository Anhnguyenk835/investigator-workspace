import { type TextareaHTMLAttributes, forwardRef } from 'react'
import { cn } from '@/lib/cn'

export type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement>

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  function Textarea({ className, rows = 4, ...props }, ref) {
    return (
      <textarea
        ref={ref}
        rows={rows}
        className={cn(
          'w-full border border-line bg-surface px-3 py-2 text-body text-ink focus:border-ink-muted/40 focus:outline-none focus-visible:outline-none placeholder:text-ink-muted disabled:cursor-not-allowed disabled:opacity-40',
          className,
        )}
        {...props}
      />
    )
  },
)
