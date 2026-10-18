import { toConnectors } from '@/api/adapt'
import { api } from '@/api/client'
import { Icon } from '@/components/ui'
import { useApiQuery } from '@/hooks/useApiQuery'
import { providerMeta } from '@/lib/providers'
import type { InvestigationBundle, SourceProvider } from '@/types/investigator'

/**
 * Sources that were not connected when the investigation ran but are now. The run keeps what it
 * could search at the time; the copilot sees the live connection, the findings do not.
 */
export function NewSourcesNotice({ b }: { b: InvestigationBundle }) {
  const connectors = useApiQuery(async () => toConnectors(await api.listIntegrations()), [])
  const connected = new Set<SourceProvider>((connectors.data ?? []).filter((c) => c.status === 'connected').map((c) => c.provider))
  const added = b.investigation.coverage.filter((c) => c.status === 'not_connected' && connected.has(c.provider)).map((c) => providerMeta[c.provider].name)
  if (added.length === 0) return null
  return (
    <p role="note" className="flex items-start gap-2 border border-info/40 bg-info/10 px-4 py-3 text-body text-ink">
      <Icon name="info" className="mt-0.5 shrink-0 text-info" />
      <span>
        <span className="font-medium">{added.join(', ')}</span> {added.length === 1 ? 'was' : 'were'} not connected when this investigation ran, and {added.length === 1 ? 'is' : 'are'} now. Use Run again to include {added.length === 1 ? 'it' : 'them'} in the findings. The copilot can already search {added.length === 1 ? 'it' : 'them'}.
      </span>
    </p>
  )
}
