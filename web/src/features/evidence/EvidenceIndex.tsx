import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { EvidenceRecord, InvestigationBundle } from '@/types/investigator'

interface EvidenceIndex {
  /** True once an investigation is open, so a citation that does not resolve can be flagged. */
  ready: boolean
  bundle: InvestigationBundle | undefined
  get: (id: string) => EvidenceRecord | undefined
  register: (bundle: InvestigationBundle | undefined) => void
  /** Records found outside the investigation (by the chat assistant) so their citations resolve. */
  addExtra: (records: EvidenceRecord[]) => void
}

const Ctx = createContext<EvidenceIndex>({
  ready: false,
  bundle: undefined,
  get: () => undefined,
  register: () => undefined,
  addExtra: () => undefined,
})

/**
 * Evidence belongs to the investigation that collected it. The open investigation
 * registers its bundle here so citations and the evidence drawer can resolve ids.
 */
export function EvidenceIndexProvider({ children }: { children: ReactNode }) {
  const [bundle, setBundle] = useState<InvestigationBundle | undefined>(undefined)
  const [extra, setExtra] = useState<EvidenceRecord[]>([])
  const register = useCallback((next: InvestigationBundle | undefined) => {
    setBundle(next)
    if (!next) setExtra([])
  }, [])
  const addExtra = useCallback((records: EvidenceRecord[]) => {
    if (records.length === 0) return
    setExtra((cur) => {
      const have = new Set(cur.map((r) => r.id))
      const fresh = records.filter((r) => !have.has(r.id))
      return fresh.length === 0 ? cur : [...cur, ...fresh]
    })
  }, [])
  const value = useMemo<EvidenceIndex>(() => {
    const map = new Map([...extra, ...(bundle?.evidence ?? [])].map((e) => [e.id, e]))
    return { ready: bundle !== undefined, bundle, get: (id) => map.get(id), register, addExtra }
  }, [bundle, extra, register, addExtra])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export const useEvidenceIndex = () => useContext(Ctx)

/** Makes `bundle` the evidence source while the calling page is mounted. */
// eslint-disable-next-line react-refresh/only-export-components
export function useRegisterBundle(bundle: InvestigationBundle | undefined) {
  const { register } = useEvidenceIndex()
  useEffect(() => {
    register(bundle)
    return () => register(undefined)
  }, [bundle, register])
}
