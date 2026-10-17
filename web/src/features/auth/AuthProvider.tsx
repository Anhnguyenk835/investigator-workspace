import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '@/api/client'
import { UNAUTHORIZED_EVENT } from '@/api/http'
import type { MeDto } from '@/api/dto'

export type AuthMode = 'loading' | 'anonymous' | 'user' | 'demo' | 'disabled'

export interface AuthUser {
  id: string
  email?: string
  name?: string
  picture?: string
}

export interface Auth {
  mode: AuthMode
  user?: AuthUser
  /** Which ways in this server offers. */
  providers: { google: boolean; demo: boolean }
  /** The visitor is in the demo: stored fictional data, nothing connected. */
  isDemo: boolean
  /** A label for who did what (their email, or a demo name). Empty with no sign-in. */
  actor: string
  error?: string
  startDemo: () => Promise<boolean>
  signOut: () => Promise<void>
}

const NONE = { google: false, demo: false }
const AuthContext = createContext<Auth | null>(null)

function fromMe(me: MeDto): Pick<Auth, 'mode' | 'user' | 'providers'> {
  return {
    mode: me.mode,
    providers: me.providers,
    user: me.user
      ? {
          id: me.user.id,
          email: me.user.email ?? undefined,
          name: me.user.name ?? undefined,
          picture: me.user.picture ?? undefined,
        }
      : undefined,
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<Pick<Auth, 'mode' | 'user' | 'providers'>>({ mode: 'loading', providers: NONE })
  const [error, setError] = useState<string | undefined>(undefined)

  useEffect(() => {
    let cancelled = false
    api
      .me()
      .then((me) => {
        if (!cancelled) setState(fromMe(me))
      })
      .catch((e: unknown) => {
        if (cancelled) return
        setError(e instanceof Error ? e.message : 'The server could not be reached.')
        setState({ mode: 'anonymous', providers: NONE })
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Any request the server answers with 401 means the session is gone: back to sign-in.
  useEffect(() => {
    const gone = () => setState((s) => (s.mode === 'disabled' ? s : { mode: 'anonymous', providers: s.providers }))
    window.addEventListener(UNAUTHORIZED_EVENT, gone)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, gone)
  }, [])

  const startDemo = useCallback(async () => {
    setError(undefined)
    try {
      setState(fromMe(await api.startDemo()))
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The demo could not be started.')
      return false
    }
  }, [])

  const signOut = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      setState((s) => ({ mode: 'anonymous', providers: s.providers }))
    }
  }, [])

  const value = useMemo<Auth>(
    () => ({
      ...state,
      isDemo: state.mode === 'demo',
      actor: state.user?.email ?? state.user?.name ?? '',
      error,
      startDemo,
      signOut,
    }),
    [state, error, startDemo, signOut],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): Auth {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
