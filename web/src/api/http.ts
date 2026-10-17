import { env } from '@/lib/env'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** FastAPI sends `detail` as text, or as a list of validation errors. */
function detailOf(body: unknown): string | undefined {
  if (typeof body !== 'object' || body === null || !('detail' in body)) return undefined
  const detail = (body as { detail: unknown }).detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((d) => (typeof d === 'object' && d !== null && 'msg' in d ? String((d as { msg: unknown }).msg) : ''))
      .filter(Boolean)
    return messages.length > 0 ? messages.join('; ') : undefined
  }
  return undefined
}

/** The error for a non-success response, with the API's own explanation when it gave one. */
export async function errorFrom(res: Response): Promise<ApiError> {
  let parsed: unknown
  try {
    parsed = await res.json()
  } catch {
    parsed = undefined
  }
  return new ApiError(res.status, detailOf(parsed) ?? `The request failed (HTTP ${res.status}).`)
}

/** Raised on the window when the server says the session is gone, so the app can return to sign-in. */
export const UNAUTHORIZED_EVENT = 'investigator:unauthorized'

export async function request<T>(method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE', path: string, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${env.apiBaseUrl}${path}`, {
      method,
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'Cannot reach the Investigator API. Check that the backend is running.')
  }
  if (res.status === 401 && !path.startsWith('/auth/')) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  if (!res.ok) throw await errorFrom(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}
