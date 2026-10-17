import { useParams } from 'react-router-dom'
import { isSupported, providerMeta } from '@/data/mockConnectors'
import type { SourceProvider } from '@/types/investigator'

export function useProviderParam(): SourceProvider | undefined {
  const { provider = '' } = useParams()
  return provider in providerMeta && isSupported(provider as SourceProvider) ? (provider as SourceProvider) : undefined
}
