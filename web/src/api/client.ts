import { ApiError, errorFrom, request, UNAUTHORIZED_EVENT } from '@/api/http'
import { readSse } from '@/api/stream'
import { env } from '@/lib/env'
import type {
  AnnotationDto,
  CustomerDto,
  DirectoryDto,
  PersonDto,
  ProjectDto,
  SuggestionsDto,
  ChatMessageDto,
  MeDto,
  ConversationDto,
  ChatStreamEvent,
  CreateInvestigationDto,
  IntegrationDto,
  InvestigationDto,
  ResumeValueDto,
} from '@/api/dto'

export const api = {
  me: () => request<MeDto>('GET', '/auth/me'),
  startDemo: () => request<MeDto>('POST', '/auth/demo'),
  logout: () => request<void>('POST', '/auth/logout'),

  listIntegrations: () => request<IntegrationDto[]>('GET', '/integrations'),
  /** Returns the provider's consent URL; the caller navigates the browser to it. */
  authorizeIntegration: (provider: string) =>
    request<{ authorization_url: string }>('POST', `/integrations/${encodeURIComponent(provider)}/authorize`),
  disconnectIntegration: (provider: string) =>
    request<void>('DELETE', `/integrations/${encodeURIComponent(provider)}`),

  listInvestigations: () => request<InvestigationDto[]>('GET', '/investigations'),
  getInvestigation: (id: string) => request<InvestigationDto>('GET', `/investigations/${encodeURIComponent(id)}`),
  createInvestigation: (body: CreateInvestigationDto) => request<InvestigationDto>('POST', '/investigations', body),
  resumeInvestigation: (id: string, value: ResumeValueDto) =>
    request<InvestigationDto>('POST', `/investigations/${encodeURIComponent(id)}/resume`, { value }),

  getDirectory: () => request<DirectoryDto>('GET', '/directory'),
  saveDirectoryEntry: <T extends CustomerDto | ProjectDto | PersonDto>(collection: 'customers' | 'projects' | 'people', body: Omit<T, 'id'>, id?: string) =>
    id ? request<T>('PUT', `/directory/${collection}/${encodeURIComponent(id)}`, body) : request<T>('POST', `/directory/${collection}`, body),
  deleteDirectoryEntry: (collection: 'customers' | 'projects' | 'people', id: string) =>
    request<void>('DELETE', `/directory/${collection}/${encodeURIComponent(id)}`),
  getSuggestions: (source: string) => request<SuggestionsDto>('GET', `/directory/suggestions/${encodeURIComponent(source)}`),

  setOwner: (id: string, owner: string | null) => request<InvestigationDto>('PATCH', `/investigations/${encodeURIComponent(id)}`, { owner }),
  rerun: (id: string) => request<InvestigationDto>('POST', `/investigations/${encodeURIComponent(id)}/rerun`),
  listAnnotations: (id: string) => request<AnnotationDto[]>('GET', `/investigations/${encodeURIComponent(id)}/annotations`),
  addAnnotation: (id: string, body: { target_id: string; kind: 'note' | 'reviewed' | 'disputed'; text: string }) =>
    request<AnnotationDto>('POST', `/investigations/${encodeURIComponent(id)}/annotations`, body),
  deleteAnnotation: (id: string, annotationId: string) =>
    request<void>('DELETE', `/investigations/${encodeURIComponent(id)}/annotations/${encodeURIComponent(annotationId)}`),

  getChat: async (id: string) =>
    (await request<{ messages: ChatMessageDto[] }>('GET', `/investigations/${encodeURIComponent(id)}/chat`)).messages,
  clearChat: (id: string) => request<void>('DELETE', `/investigations/${encodeURIComponent(id)}/chat`),

  listConversations: async (id: string) =>
    (await request<{ conversations: ConversationDto[] }>('GET', `/investigations/${encodeURIComponent(id)}/conversations`)).conversations,
  createConversation: (id: string) => request<ConversationDto>('POST', `/investigations/${encodeURIComponent(id)}/conversations`),
  renameConversation: (id: string, conversationId: string, title: string) =>
    request<ConversationDto>('PATCH', `/investigations/${encodeURIComponent(id)}/conversations/${encodeURIComponent(conversationId)}`, { title }),
  deleteConversation: (id: string, conversationId: string) =>
    request<void>('DELETE', `/investigations/${encodeURIComponent(id)}/conversations/${encodeURIComponent(conversationId)}`),
  getConversationMessages: async (id: string, conversationId: string) =>
    (
      await request<{ messages: ChatMessageDto[] }>(
        'GET',
        `/investigations/${encodeURIComponent(id)}/conversations/${encodeURIComponent(conversationId)}/messages`,
      )
    ).messages,
}

/** URL of the live progress stream of a run (used with EventSource). */
export const eventsUrl = (id: string): string => `${env.apiBaseUrl}/investigations/${encodeURIComponent(id)}/events`

/**
 * Sends one chat message and reports the answer as it streams in. Resolves when the
 * stream ends; rejects with an ApiError if the request was refused before streaming.
 */
export async function streamChat(
  id: string,
  conversationId: string,
  message: string,
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response
  try {
    res = await fetch(`${env.apiBaseUrl}/investigations/${encodeURIComponent(id)}/conversations/${encodeURIComponent(conversationId)}/chat`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
      signal,
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') return
    throw new ApiError(0, 'Cannot reach the Investigator API. Check that the backend is running.')
  }
  if (res.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  if (!res.ok) throw await errorFrom(res)
  try {
    for await (const m of readSse(res)) onEvent({ event: m.event, data: m.data } as ChatStreamEvent)
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') return
    throw new ApiError(0, 'The connection was lost while the answer was streaming.')
  }
}

/** Where a report can be downloaded: Markdown, printable HTML, or the raw JSON. */
export const exportUrl = (id: string, format: 'md' | 'html' | 'json'): string =>
  `${env.apiBaseUrl}/investigations/${encodeURIComponent(id)}/export?format=${format}`
