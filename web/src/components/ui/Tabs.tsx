import { type ReactNode } from 'react'
import { cn } from '@/lib/cn'

export interface TabItem<T extends string> {
  id: T
  label: ReactNode
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
}: {
  tabs: TabItem<T>[]
  value: T
  onChange: (id: T) => void
  label: string
}) {
  return (
    <div role="tablist" aria-label={label} className="flex gap-0 overflow-x-auto overflow-y-hidden shadow-[inset_0_-1px_0_var(--color-line-subtle)]">
      {tabs.map((t) => {
        const selected = t.id === value
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={selected}
            aria-controls={`panel-${t.id}`}
            onClick={() => onChange(t.id)}
            className={cn(
              'whitespace-nowrap border-b-2 px-3 py-2.5 text-caption font-medium',
              selected ? 'border-primary text-ink' : 'border-transparent text-ink-muted hover:text-ink',
            )}
          >
            {t.label}
          </button>
        )
      })}
    </div>
  )
}
