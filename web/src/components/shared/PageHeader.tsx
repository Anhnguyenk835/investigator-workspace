import { type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Icon } from '@/components/ui/Icon'

export interface Crumb {
  label: string
  to?: string
}

function Breadcrumbs({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1 text-caption text-ink-muted">
      {crumbs.map((c, i) => (
        <span key={`${c.label}-${i}`} className="inline-flex items-center gap-1">
          {i > 0 ? <Icon name="chevronRight" className="size-3" /> : null}
          {c.to ? (
            <Link to={c.to} className="hover:text-ink hover:underline">
              {c.label}
            </Link>
          ) : (
            <span aria-current="page">{c.label}</span>
          )}
        </span>
      ))}
    </nav>
  )
}

export function PageHeader({
  title,
  description,
  actions,
  crumbs,
  meta,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  crumbs?: Crumb[]
  meta?: ReactNode
}) {
  return (
    <header className="mb-6 flex flex-col gap-3">
      {crumbs && crumbs.length > 0 ? <Breadcrumbs crumbs={crumbs} /> : null}
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 sm:flex-nowrap">
        <h1 className="min-w-0 text-title text-ink">{title}</h1>
        {actions ? <div className="flex max-w-full flex-wrap items-center gap-2 sm:shrink-0">{actions}</div> : null}
      </div>
      {description ? <div className="-mt-2 text-body text-ink-muted">{description}</div> : null}
      {meta}
    </header>
  )
}
