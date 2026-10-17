import { cn } from '@/lib/cn'

export function Progress({ value, max, label, className }: { value: number; max: number; label: string; className?: string }) {
  const pct = Math.max(0, Math.min(100, Math.round((value / max) * 100)))
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
      className={cn('h-1.5 w-full bg-surface-muted', className)}
    >
      <div className="h-full bg-primary transition-[width] duration-500" style={{ width: `${pct}%` }} />
    </div>
  )
}
