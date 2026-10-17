import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { Skeleton } from '@/components/ui'
import { useAuth } from '@/features/auth/AuthProvider'

/** Everything behind it needs a session (an account or the demo); anyone else goes to sign-in. */
export function RequireAuth() {
  const { mode } = useAuth()
  const location = useLocation()
  if (mode === 'loading') {
    return (
      <div className="flex min-h-dvh items-center justify-center" role="status" aria-label="Loading">
        <Skeleton className="h-8 w-48" />
      </div>
    )
  }
  if (mode === 'anonymous') {
    const next = `${location.pathname}${location.search}`
    return <Navigate replace to={next === '/' ? '/login' : `/login?next=${encodeURIComponent(next)}`} />
  }
  return <Outlet />
}
