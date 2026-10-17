import { type ReactNode, useId, cloneElement, isValidElement, type ReactElement } from 'react'
import { Label } from '@/components/ui/Label'

export function Field({
  label,
  hint,
  error,
  required,
  children,
}: {
  label: string
  hint?: ReactNode
  error?: string
  required?: boolean
  children: ReactElement<{ id?: string; 'aria-describedby'?: string; 'aria-invalid'?: boolean }>
}) {
  const id = useId()
  const hintId = `${id}-hint`
  const errId = `${id}-err`
  const describedBy = [hint ? hintId : null, error ? errId : null].filter(Boolean).join(' ') || undefined
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>
        {label}
        {required ? <span className="text-danger"> *</span> : null}
      </Label>
      {isValidElement(children)
        ? cloneElement(children, { id, 'aria-describedby': describedBy, 'aria-invalid': error ? true : undefined })
        : children}
      {hint ? (
        <p id={hintId} className="text-caption text-ink-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errId} role="alert" className="text-caption text-danger">
          {error}
        </p>
      ) : null}
    </div>
  )
}
