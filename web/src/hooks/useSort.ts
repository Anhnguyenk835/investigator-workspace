import { useMemo, useState } from 'react'
import type { SortDir } from '@/components/ui'

export function useSort<T, K extends string>(
  rows: T[],
  accessors: Record<K, (row: T) => string | number>,
  initial: { key: K; dir: SortDir },
) {
  const [sort, setSort] = useState(initial)
  const sorted = useMemo(() => {
    const get = accessors[sort.key]
    const mult = sort.dir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const x = get(a)
      const y = get(b)
      if (typeof x === 'number' && typeof y === 'number') return (x - y) * mult
      return String(x).localeCompare(String(y)) * mult
    })
    // accessors are static per call site
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, sort])
  const toggle = (key: K) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' }))
  return { sorted, sort, toggle }
}
