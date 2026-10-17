import { type HTMLAttributes, type TdHTMLAttributes, type ThHTMLAttributes } from 'react'
import { cn } from '@/lib/cn'
import { Icon } from '@/components/ui/Icon'

export function TableWrap({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('overflow-x-auto border border-line bg-surface', className)} {...props} />
}

export function Table({ className, ...props }: HTMLAttributes<HTMLTableElement>) {
  return <table className={cn('w-full border-collapse text-left text-caption', className)} {...props} />
}

export function Th({ className, ...props }: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      scope="col"
      className={cn('whitespace-nowrap border-b border-line bg-surface-muted px-4 py-2.5 text-overline uppercase text-ink-muted', className)}
      {...props}
    />
  )
}

export function Td({ className, ...props }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn('border-b border-line-subtle px-4 py-3 align-top text-ink', className)} {...props} />
}

export type SortDir = 'asc' | 'desc'

export function SortTh({
  label,
  active,
  dir,
  onSort,
  className,
}: {
  label: string
  active: boolean
  dir: SortDir
  onSort: () => void
  className?: string
}) {
  return (
    <th
      scope="col"
      aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
      className={cn('whitespace-nowrap border-b border-line bg-surface-muted p-0 text-overline uppercase text-ink-muted', className)}
    >
      <button type="button" onClick={onSort} className="flex w-full items-center gap-1 px-4 py-2.5 text-left uppercase hover:text-ink">
        {label}
        <Icon name={active && dir === 'desc' ? 'arrowDown' : 'arrowUp'} className={cn('size-3', active ? 'text-ink' : 'opacity-30')} />
      </button>
    </th>
  )
}
