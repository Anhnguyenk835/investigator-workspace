import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Button, Icon, type IconName } from '@/components/ui'
import { useAuth } from '@/features/auth/AuthProvider'
import { EvidenceDrawerHost } from '@/features/evidence/EvidenceDrawer'
import { NAV_EVENT, useTour } from '@/features/tour'
import { cn } from '@/lib/cn'

interface NavItem {
  to: string
  label: string
  icon: IconName
  end?: boolean
}

const NAV: NavItem[] = [
  { to: '/investigations', label: 'Investigations', icon: 'investigations' },
  { to: '/settings/connectors', label: 'Connectors', icon: 'plug' },
  { to: '/settings/directory', label: 'Directory', icon: 'user' },
  { to: '/settings', label: 'Settings', icon: 'gear', end: true },
]

function Brand() {
  return (
    <Link to="/investigations" className="flex items-center gap-2.5">
      <span aria-hidden="true" className="flex size-8 items-center justify-center bg-primary text-primary-fg">
        <Icon name="search" className="size-4" />
      </span>
      <span className="text-body font-medium tracking-tight text-ink">The Investigator</span>
    </Link>
  )
}

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Primary" className="flex flex-col gap-0.5 px-3">
      {NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          onClick={onNavigate}
          data-tour={`nav-${item.label.toLowerCase()}`}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-3 border-l-2 px-3 py-2.5 text-caption font-medium',
              isActive
                ? 'border-primary bg-primary/10 text-ink'
                : 'border-transparent text-ink-muted hover:bg-surface-muted hover:text-ink',
            )
          }
        >
          <Icon name={item.icon} />
          {item.label}
        </NavLink>
      ))}
    </nav>
  )
}

function initials(text: string): string {
  const parts = text.split(/[\s@.]+/).filter(Boolean)
  return ((parts[0]?.[0] ?? '?') + (parts[1]?.[0] ?? '')).toUpperCase()
}

/** Who is signed in, and the way out. In the demo, the way to a real account. */
function AccountBlock() {
  const { mode, user, isDemo, signOut } = useAuth()
  const navigate = useNavigate()
  if (mode === 'disabled' || mode === 'loading' || mode === 'anonymous') return null
  const label = isDemo ? 'Demo visitor' : (user?.name ?? user?.email ?? 'Signed in')
  return (
    <div className="flex items-center gap-3">
      {user?.picture && !isDemo ? (
        <img src={user.picture} alt="" referrerPolicy="no-referrer" className="size-8 shrink-0 rounded-full border border-line" />
      ) : (
        <span aria-hidden="true" className="flex size-8 shrink-0 items-center justify-center rounded-full border border-line bg-surface-muted text-caption font-medium text-ink">
          {isDemo ? <Icon name="user" className="size-4" /> : initials(label)}
        </span>
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate text-caption font-medium text-ink">{label}</p>
        {!isDemo && user?.email && user.email !== label ? <p className="truncate text-overline text-ink-muted">{user.email}</p> : null}
        {isDemo ? <p className="text-overline text-ink-muted">Mock data</p> : null}
      </div>
      <Button
        variant="ghost"
        size="sm"
        title={isDemo ? 'Leave the demo' : 'Sign out'}
        aria-label={isDemo ? 'Leave the demo' : 'Sign out'}
        onClick={async () => {
          await signOut()
          navigate('/login', { replace: true })
        }}
      >
        <Icon name="external" className="size-4 rotate-180" />
      </Button>
    </div>
  )
}

function SidebarFooter() {
  const tour = useTour()
  return (
    <div className="mt-auto flex flex-col gap-3 border-t border-line-subtle px-4 py-4">
      <AccountBlock />
      <button type="button" className="w-fit text-caption text-ink-muted hover:text-ink hover:underline" onClick={tour.start}>
        Take the tour
      </button>
      <Link to="/system" className="text-caption text-ink-muted hover:text-ink hover:underline">
        Design system
      </Link>
    </div>
  )
}

/** Says, on every page, that nothing here is real and how to get to the real thing. */
function DemoStrip() {
  const { isDemo, signOut } = useAuth()
  const navigate = useNavigate()
  if (!isDemo) return null
  return (
    <div role="note" className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-warning/30 bg-warning/10 px-4 py-2 text-caption text-ink sm:px-8">
      <Icon name="info" className="size-3.5 shrink-0 text-warning" />
      <span className="font-medium">Demo workspace</span>
      <span className="text-ink-muted">Fictional data. The AI answers are real. Your work here is deleted after 24 hours.</span>
      <button
        type="button"
        className="ml-auto font-medium text-info hover:underline"
        onClick={async () => {
          await signOut()
          navigate('/login', { replace: true })
        }}
      >
        Sign in with Google
      </button>
    </div>
  )
}

export function AppShell() {
  const [navOpen, setNavOpen] = useState(false)
  const location = useLocation()

  useEffect(() => {
    setNavOpen(false)
  }, [location.pathname])

  // The guided tour opens the drawer when it points into the sidebar on a small screen.
  useEffect(() => {
    const onNav = (e: Event) => setNavOpen((e as CustomEvent<boolean>).detail === true && window.innerWidth < 1024)
    window.addEventListener(NAV_EVENT, onNav)
    return () => window.removeEventListener(NAV_EVENT, onNav)
  }, [])

  useEffect(() => {
    if (!navOpen) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setNavOpen(false)
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [navOpen])

  return (
    <div className="flex min-h-dvh">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-[80] focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>

      <aside className="sticky top-0 hidden h-dvh w-58 shrink-0 flex-col border-r border-line bg-surface lg:flex">
        <div className="flex h-16 items-center border-b border-line-subtle px-5">
          <Brand />
        </div>
        <div className="py-4">
          <NavList />
        </div>
        <SidebarFooter />
      </aside>

      {navOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-ink/40" onClick={() => setNavOpen(false)} aria-hidden="true" />
          <aside className="relative flex h-full w-64 max-w-[85vw] flex-col border-r border-line bg-surface" aria-label="Navigation">
            <div className="flex h-16 items-center justify-between border-b border-line-subtle px-5">
              <Brand />
              <Button variant="ghost" size="sm" aria-label="Close navigation" onClick={() => setNavOpen(false)}>
                <Icon name="x" />
              </Button>
            </div>
            <div className="py-4">
              <NavList onNavigate={() => setNavOpen(false)} />
            </div>
            <SidebarFooter />
          </aside>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-surface px-4 lg:hidden">
          <Button variant="ghost" size="sm" aria-label="Open navigation" aria-expanded={navOpen} onClick={() => setNavOpen(true)}>
            <Icon name="menu" />
          </Button>
          <span className="truncate text-caption text-ink-muted">The Investigator</span>
        </header>
        <DemoStrip />
        <main id="main" className="min-w-0 flex-1 px-4 py-6 sm:px-8 sm:py-8">
          <div className="mx-auto w-full max-w-[1280px]">
            <Outlet />
          </div>
        </main>
      </div>
      <EvidenceDrawerHost />
    </div>
  )
}
