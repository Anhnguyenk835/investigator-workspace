import { type InputHTMLAttributes, type ReactNode, forwardRef, useId } from 'react'
import { cn } from '@/lib/cn'

export type CheckboxProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> & {
  label: ReactNode
  description?: ReactNode
  type?: 'checkbox' | 'radio'
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
  { label, description, className, id, type = 'checkbox', ...props },
  ref,
) {
  const autoId = useId()
  const inputId = id ?? autoId
  return (
    <div className={cn('flex items-start gap-3', className)}>
      <input
        ref={ref}
        id={inputId}
        type={type}
        className="mt-0.5 size-4 shrink-0 accent-primary disabled:cursor-not-allowed disabled:opacity-40"
        {...props}
      />
      <label htmlFor={inputId} className="min-w-0 cursor-pointer text-body text-ink">
        {label}
        {description ? <span className="block text-caption text-ink-muted">{description}</span> : null}
      </label>
    </div>
  )
})
