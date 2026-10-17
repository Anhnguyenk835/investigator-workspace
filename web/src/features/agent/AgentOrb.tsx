import { Icon } from '@/components/ui/Icon'
import { cn } from '@/lib/cn'

/** Round, softly moving agent mark. Static unless `animated`; `busy` speeds it up. */
export function AgentOrb({ className, animated = false, busy = false }: { className?: string; animated?: boolean; busy?: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={cn('agent-orb size-8', className)}
      data-animated={animated ? '' : undefined}
      data-busy={busy ? '' : undefined}
    >
      <i />
      <i />
      <i />
      <Icon name="search" className="absolute left-1/2 top-1/2 z-10 size-[44%] -translate-x-1/2 -translate-y-1/2 text-white drop-shadow-sm" strokeWidth={2} />
    </span>
  )
}
