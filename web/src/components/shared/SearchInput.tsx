import { Icon } from '@/components/ui/Icon'
import { Input } from '@/components/ui/Input'
import { cn } from '@/lib/cn'

export function SearchInput({
  value,
  onChange,
  placeholder,
  label,
  className,
}: {
  value: string
  onChange: (v: string) => void
  placeholder: string
  label: string
  className?: string
}) {
  return (
    <div className={cn('relative', className)}>
      <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
      <Input
        type="search"
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="pl-9"
      />
    </div>
  )
}
