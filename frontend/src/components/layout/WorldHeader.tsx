'use client'

/**
 * WorldHeader — the persistent navigation shell for authenticated
 * member surfaces (Your World, Explore Collectives, Discover Places,
 * Ways to Connect, inside-Collective pages, Settings, Notifications,
 * Profile).
 *
 * Sibling to PublicHeader (which serves signed-out visitors and the
 * public homepage). WorldHeader is chosen by SiteShell when the
 * visitor is authenticated, and mounted directly by WorldShell on
 * member routes that do not use SiteShell.
 *
 * Client component: needs `usePathname` for active-state, and reuses
 * NotificationBell + LogoutButton + Avatar which are all client.
 * The user profile is fetched by the parent server component and
 * passed down so this file doesn't reach for cookies.
 */

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import Container from './Container'
import LogoutButton from './LogoutButton'
import NotificationBell from './NotificationBell'
import Avatar from '@/components/ui/Avatar'
import { apiUrl } from '@/lib/api'

interface Props {
  /** Minimal user info needed by the shell. */
  user: {
    name: string | null
    role: string
  }
  /** Mirrors the backend's discovery_pillar_enabled flag. */
  discoveryOn: boolean
}

interface NavItem {
  href: string
  label: string
}

/**
 * Peer destinations in the pillar order defined by
 * docs/foundations/discovery-connection-belonging-v1.1.md.
 * Your World is always first for signed-in visitors.
 */
function peerNavItems(discoveryOn: boolean): NavItem[] {
  const items: NavItem[] = [
    { href: '/dashboard', label: 'Your World' },
    { href: '/spaces',    label: 'Explore Collectives' },
  ]
  if (discoveryOn) {
    items.push({ href: '/discover-places', label: 'Discover Places' })
    items.push({ href: '/ways-to-connect', label: 'Ways to Connect' })
  }
  return items
}

/**
 * A nav item is "active" when its href matches the pathname exactly,
 * or when a Collective-scoped page (/spaces/[slug]/...) is being
 * viewed and the item is Explore Collectives. Nested Discover-Places
 * and Ways-to-Connect subpaths (if they ever exist) also count.
 */
function isActive(pathname: string, href: string): boolean {
  if (pathname === href) return true
  if (href === '/spaces' && pathname.startsWith('/spaces/')) return true
  if (href === '/discover-places' && pathname.startsWith('/discover-places/')) return true
  if (href === '/ways-to-connect' && pathname.startsWith('/ways-to-connect/')) return true
  if (href === '/dashboard' && pathname.startsWith('/dashboard/')) return true
  return false
}

export default function WorldHeader({ user, discoveryOn }: Props) {
  const pathname = usePathname() ?? ''
  const items = peerNavItems(discoveryOn)
  const displayName = user.name ?? 'Member'

  return (
    <header
      className="sticky top-0 z-50 backdrop-blur-xl"
      style={{
        background: 'rgba(255,255,255,0.95)',
        borderBottom: '1px solid #E8E8E5',
      }}
    >
      <Container className="flex h-16 items-center justify-between gap-8">
        {/* Wordmark → Your World */}
        <Link href="/dashboard" className="group flex shrink-0 items-center gap-2.5">
          <div
            className="flex h-7 w-7 items-center justify-center rounded-lg"
            style={{ background: 'linear-gradient(135deg, #38A09E, #55B8B6)' }}
          >
            <div className="h-3 w-3 rounded-sm bg-white" style={{ opacity: 0.92 }} />
          </div>
          <span className="text-[15px] font-semibold tracking-[-0.02em] text-navy-950 transition-opacity group-hover:opacity-60">
            Fresh Collective
          </span>
        </Link>

        {/* Desktop nav — peer destinations with active state */}
        <nav aria-label="Member" className="hidden flex-1 items-center justify-center gap-8 md:flex">
          {items.map(({ href, label }) => {
            const active = isActive(pathname, href)
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? 'page' : undefined}
                className={
                  'text-[14px] transition-colors ' +
                  (active
                    ? 'font-semibold text-navy-950 border-b-2 border-teal-500 pb-0.5'
                    : 'font-medium text-navy-500 hover:text-navy-950')
                }
              >
                {label}
              </Link>
            )
          })}
        </nav>

        {/* Desktop auth cluster — notifications + profile shortcut + logout */}
        <div className="hidden shrink-0 items-center gap-3 md:flex">
          <NotificationBell initialCount={0} />
          <Link
            href="/settings/profile"
            aria-label="Your profile"
            className="flex items-center rounded-lg px-1.5 py-1 transition-colors hover:bg-slate-50"
          >
            <Avatar name={displayName} size="sm" />
          </Link>
          <LogoutButton
            className="rounded-xl border border-navy-100 px-4 py-2 text-[13px] font-medium text-navy-600 transition-all hover:border-navy-200 hover:bg-navy-50"
          />
        </div>

        {/* Mobile hamburger + drawer */}
        <WorldMobileNav
          user={user}
          items={items}
          pathname={pathname}
        />
      </Container>
    </header>
  )
}


// ---------------------------------------------------------------------------
// Mobile drawer — separate from the shared MobileNav so the world drawer
// can carry active-state, notifications, profile and logout without
// re-shaping the public MobileNav that /spaces (public) also uses.
// ---------------------------------------------------------------------------

function WorldMobileNav({
  user,
  items,
  pathname,
}: {
  user: { name: string | null; role: string }
  items: NavItem[]
  pathname: string
}) {
  const [open, setOpen] = useState(false)
  const router = useRouter()
  const [prevPath, setPrevPath] = useState(pathname)
  const displayName = user.name ?? 'Member'

  // Close drawer on route change.
  if (prevPath !== pathname) {
    setPrevPath(pathname)
    if (open) setOpen(false)
  }

  useEffect(() => {
    if (open) document.body.style.overflow = 'hidden'
    else document.body.style.overflow = ''
    return () => { document.body.style.overflow = '' }
  }, [open])

  async function handleLogout() {
    await fetch(apiUrl('/api/auth/logout'), { method: 'POST', credentials: 'include' }).catch(() => {})
    router.push('/')
    router.refresh()
  }

  return (
    <div className="md:hidden">
      <button
        onClick={() => setOpen(!open)}
        aria-label={open ? 'Close menu' : 'Open menu'}
        aria-expanded={open}
        className="flex h-10 w-10 items-center justify-center rounded-lg transition-colors"
        style={{ color: '#0C1826' }}
      >
        <svg width="20" height="14" viewBox="0 0 20 14" fill="none" aria-hidden="true">
          {open ? (
            <path d="M2 2L18 12M18 2L2 12" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
          ) : (
            <>
              <line x1="0" y1="1"  x2="20" y2="1"  stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
              <line x1="0" y1="7"  x2="20" y2="7"  stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
              <line x1="0" y1="13" x2="20" y2="13" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
            </>
          )}
        </svg>
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 top-16 z-40 bg-black/20 backdrop-blur-[2px]"
            onClick={() => setOpen(false)}
          />
          <div
            className="absolute inset-x-0 top-16 z-50 px-5 pb-8 pt-4"
            style={{
              background: '#0C1826',
              borderBottom: '1px solid rgba(255,255,255,0.07)',
              boxShadow: '0 16px 48px rgba(0,0,0,0.50)',
            }}
          >
            <nav aria-label="Member — mobile" className="mb-5 space-y-0.5">
              {items.map(({ href, label }) => {
                const active = isActive(pathname, href)
                return (
                  <Link
                    key={href}
                    href={href}
                    aria-current={active ? 'page' : undefined}
                    className="flex items-center rounded-xl px-4 py-3.5 text-[16px] transition-colors"
                    style={{
                      color: '#FFFFFF',
                      fontWeight: active ? 600 : 500,
                      background: active ? 'rgba(85, 184, 182, 0.14)' : 'transparent',
                    }}
                  >
                    {label}
                  </Link>
                )
              })}

              <Link
                href="/notifications"
                aria-current={pathname === '/notifications' ? 'page' : undefined}
                className="flex items-center rounded-xl px-4 py-3.5 text-[16px] transition-colors"
                style={{
                  color: '#FFFFFF',
                  fontWeight: pathname === '/notifications' ? 600 : 500,
                  background: pathname === '/notifications' ? 'rgba(85, 184, 182, 0.14)' : 'transparent',
                }}
              >
                Notifications
              </Link>

              <Link
                href="/settings/profile"
                aria-current={pathname.startsWith('/settings') ? 'page' : undefined}
                className="flex items-center gap-3 rounded-xl px-4 py-3.5 text-[16px] transition-colors"
                style={{
                  color: '#FFFFFF',
                  fontWeight: pathname.startsWith('/settings') ? 600 : 500,
                  background: pathname.startsWith('/settings') ? 'rgba(85, 184, 182, 0.14)' : 'transparent',
                }}
              >
                <Avatar name={displayName} size="sm" />
                <span>Your profile</span>
              </Link>
            </nav>

            <div className="flex flex-col gap-2.5 pt-5" style={{ borderTop: '1px solid rgba(255,255,255,0.07)' }}>
              <button
                onClick={handleLogout}
                className="w-full rounded-xl py-3.5 text-[15px] font-medium transition-colors"
                style={{ border: '1px solid rgba(255,255,255,0.12)', color: '#FFFFFF' }}
              >
                Log out
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
