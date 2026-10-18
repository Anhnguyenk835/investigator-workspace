import { useState } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { GoogleMark } from '@/components/shared/GoogleMark'
import { Button, Icon } from '@/components/ui'
import { useAuth } from '@/features/auth/AuthProvider'
import { env } from '@/lib/env'

/** Why a sign-in attempt came back, in words a person can act on. Codes come from the server. */
const REASONS: Record<string, string> = {
  access_denied: 'Sign-in was cancelled.',
  not_allowed: 'This Google account is not allowed to sign in here.',
  email_not_verified: 'Google has not verified this email address.',
  expired_state: 'The sign-in took too long. Try again.',
  invalid_state: 'That sign-in link was not valid or was already used. Try again.',
  not_configured: 'Sign-in with Google is not set up on this server.',
  token_exchange_failed: 'Google did not accept the sign-in. Try again.',
}

/** Only a path on this site: never somewhere else after sign-in. */
function safeNext(value: string | null): string {
  return value && value.startsWith('/') && !value.startsWith('//') && !value.includes('\\') ? value : '/'
}

export function LoginPage() {
  const { mode, providers, startDemo, error } = useAuth()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [starting, setStarting] = useState(false)
  const next = safeNext(params.get('next'))
  const code = params.get('error')
  const reason = (code && (REASONS[code] ?? 'Sign-in failed. Try again.')) || error

  if (mode === 'user' || mode === 'demo' || mode === 'disabled') return <Navigate replace to={next} />

  const google = `${env.apiBaseUrl}/auth/google/start?next=${encodeURIComponent(next)}`

  return (
    <main className="flex min-h-dvh items-center justify-center bg-canvas px-4 py-10">
      <div className="w-full max-w-sm border border-line bg-surface p-8 shadow-sm">
        <div className="flex items-center gap-3">
          <span className="flex size-9 items-center justify-center bg-primary text-primary-fg" aria-hidden="true">
            <Icon name="search" className="size-5" />
          </span>
          <h1 className="text-title text-ink">The Investigator</h1>
        </div>
        <p className="mt-3 text-body text-ink-muted">Reconstruct what happened in a customer escalation, from the evidence.</p>

        {reason ? (
          <p role="alert" className="mt-5 flex items-start gap-2 border-l-2 border-danger bg-danger/10 px-3 py-2 text-caption text-ink">
            <Icon name="alert" className="mt-0.5 size-3.5 shrink-0 text-danger" />
            {reason}
          </p>
        ) : null}

        <div className="mt-6 flex flex-col gap-3">
          {providers.google ? (
            <a
              href={google}
              className="inline-flex h-11 items-center justify-center gap-3 border border-line bg-surface px-4 text-body font-medium text-ink hover:bg-surface-muted focus-visible:outline-2 focus-visible:outline-primary"
            >
              <GoogleMark className="size-5" /> Continue with Google
            </a>
          ) : (
            <p className="border border-line-subtle bg-surface-muted px-3 py-2 text-caption text-ink-muted">Sign-in with Google is not set up on this server.</p>
          )}
          {providers.demo ? (
            <>
              <div className="flex items-center gap-3 text-overline uppercase text-ink-muted" aria-hidden="true">
                <span className="h-px flex-1 bg-line" /> or <span className="h-px flex-1 bg-line" />
              </div>
              <Button
                variant="outline"
                size="lg"
                disabled={starting}
                onClick={async () => {
                  setStarting(true)
                  if (await startDemo()) navigate(next, { replace: true })
                  else setStarting(false)
                }}
              >
                <Icon name="play" /> Use with mock data
              </Button>
              <p className="text-caption text-ink-muted">A fictional fund-administration dataset. No account needed. The AI answers are real; the data is not.</p>
            </>
          ) : null}
        </div>
        <p className="mt-6 flex gap-4 border-t border-line-subtle pt-4 text-caption text-ink-muted">
          <Link to="/privacy" className="hover:text-ink hover:underline">
            Privacy Policy
          </Link>
          <Link to="/terms" className="hover:text-ink hover:underline">
            Terms of Service
          </Link>
        </p>
      </div>
    </main>
  )
}
