import { useSearchParams } from 'react-router-dom'
import { providerLogos } from '@/components/shared/ProviderMark'
import { useFormat } from '@/hooks/useSettings'
import { useEvidenceIndex } from '@/features/evidence/EvidenceIndex'
import { cn } from '@/lib/cn'
import { providerMeta } from '@/lib/providers'

export const EVIDENCE_PARAM = 'evidence'

export function useOpenEvidence() {
  const [params, setParams] = useSearchParams()
  return {
    openId: params.get(EVIDENCE_PARAM),
    open: (id: string) =>
      setParams(
        (p) => {
          const next = new URLSearchParams(p)
          next.set(EVIDENCE_PARAM, id)
          return next
        },
        { replace: false },
      ),
    close: () =>
      setParams(
        (p) => {
          const next = new URLSearchParams(p)
          next.delete(EVIDENCE_PARAM)
          return next
        },
        { replace: true },
      ),
  }
}

/** Inline citation. Always resolves to a stable evidence ID; unresolved IDs are flagged. */
export function EvidenceCitation({ id, className, pending = false }: { id: string; className?: string; pending?: boolean }) {
  const { open } = useOpenEvidence()
  const index = useEvidenceIndex()
  const { short } = useFormat()
  const record = index.get(id)

  // `pending`: the id may belong to a record that is still arriving (a streaming answer).
  if (pending && !record) {
    return <span className="inline-flex size-6 items-center justify-center align-middle text-overline text-ink-muted" title="Checking this citation…">…</span>
  }
  if (index.ready && !record) {
    return (
      <span className="inline-flex items-center border border-danger px-1.5 py-0.5 text-overline text-danger" title={`Record ${id} could not be found`}>
        Missing record
      </span>
    )
  }
  const label = record ? `${providerMeta[record.provider].name} · ${short(record.timestamp)}` : 'Evidence'
  return (
    <button
      type="button"
      onClick={() => open(id)}
      aria-label={record ? `Open evidence: ${label}. ${record.title}` : 'Open evidence'}
      title={record ? `${label} — ${record.title}` : 'Evidence'}
      className={cn(
        'inline-flex size-6 items-center justify-center align-middle hover:bg-primary/10',
        className,
      )}
    >
      {record ? <img src={providerLogos[record.provider]} alt="" className="size-4 object-contain" draggable={false} /> : <span className="text-overline text-ink-muted">?</span>}
    </button>
  )
}

export function CitationList({ ids, className }: { ids: string[]; className?: string }) {
  if (ids.length === 0) return <span className="text-caption text-ink-muted">No evidence</span>
  return (
    <span className={cn('inline-flex flex-wrap items-center gap-1.5', className)}>
      {ids.map((id) => (
        <EvidenceCitation key={id} id={id} />
      ))}
    </span>
  )
}
