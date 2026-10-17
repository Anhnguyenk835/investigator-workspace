import type { CoverageStatus, SourceCoverage } from '@/types/investigator'

/** A source whose search ran far enough to say something about its records. */
export const isSearched = (status: CoverageStatus): boolean => status === 'searched' || status === 'partial' || status === 'no_matches'

export function coverageRatio(coverage: SourceCoverage[]): { searched: number; total: number } {
  return { searched: coverage.filter((c) => isSearched(c.status)).length, total: coverage.length }
}
