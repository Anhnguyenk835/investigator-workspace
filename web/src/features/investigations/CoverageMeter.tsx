import { coverageRatio } from '@/lib/coverage'
import { cn } from '@/lib/cn'
import type { SourceCoverage } from '@/types/investigator'

/** Text plus segments, so coverage never depends on color alone. */
export function CoverageMeter({ coverage }: { coverage: SourceCoverage[] }) {
  if (coverage.length === 0) return <span className="text-caption text-ink-muted">Not searched yet</span>
  const { searched, total } = coverageRatio(coverage)
  const complete = searched === total && coverage.every((c) => c.status !== 'partial')
  return (
    <div className="flex flex-col gap-1" title={complete ? 'All selected sources searched' : 'Some sources were not fully searched'}>
      <span className="whitespace-nowrap text-caption text-ink">
        {searched} of {total} sources searched
      </span>
      <span className="flex gap-0.5" aria-hidden="true">
        {coverage.map((c) => (
          <span
            key={c.provider}
            className={cn(
              'h-1.5 w-4',
              c.status === 'searched' || c.status === 'no_matches' ? 'bg-success' : c.status === 'partial' ? 'bg-warning' : 'bg-line-subtle',
            )}
          />
        ))}
      </span>
    </div>
  )
}
