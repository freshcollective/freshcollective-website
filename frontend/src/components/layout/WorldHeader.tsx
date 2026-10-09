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
 * Breakpoint note: the horizontal bar appears at ``min-[1152px]``, not
 * at ``lg``.
 *
 * It used to appear at ``lg`` (1024px), which is narrower than the row
 * actually needs, and the failure was not graceful. The brand lockup
 * and the auth cluster are both ``shrink-0``, so the nav is the only
 * item that can give — but its links are ``whitespace-nowrap``, so when
 * the nav box shrinks below its contents the links overflow it rather
 * than shrinking, and nothing clips them. Being ``justify-center``, the
 * spill is symmetric: "Your World" lands on the wordmark and "Creator
 * Studio" on the notification bell. Measured in Chromium, 14.1px over
 * each side at 1024px.
 *
 * 1152px is ``max-w-6xl`` — the width at which Container stops growing.
 * Choosing it means the bar only exists where the row's geometry is
 * fixed (content box 1072px, nav box 702px, nav needs 634px), so there
 * is no width-dependent squeeze left: above the breakpoint nothing
 * moves, and below it the drawer has room for everything.
 *
 * The nav keeps ``gap-4`` at every width. It previously took
 * ``xl:gap-8``, which added 80px to what the nav needed (five gaps)
 * while the Container's own ``xl:gap-8`` took another 32px off the nav
 * box — leaving the 1280px-and-up band 9.9px from overlapping too.
 *
 * All three visibility switches below share this one threshold. They
 * have to: moving the nav without the auth cluster would show the
 * destinations while the bell, avatar and logout vanished.
 *
 * Nothing is hidden from anyone at any width: below the breakpoint the
 * whole nav is in the drawer, Creator Studio included.
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
import { canAccessCreatorStudio } from '@/lib/creatorStudioAccess'
import { isNavItemActive, memberNavItems } from '@/lib/memberNavItems'
import type { NavItem } from '@/lib/memberNavItems'
import { BrandLockup } from '@/components/brand/FreshCollectiveBrand'

interface Props {
  /** Minimal user info needed by the shell. */
  user: {
    name: string | null
    role: string
  }
  /** Mirrors the backend's discovery_pillar_enabled flag. */
  discoveryOn: boolean
  waysToConnectOn: boolean
}

export default function WorldHeader({ user, discoveryOn, waysToConnectOn }: Props) {
  const pathname = usePathname() ?? ''
  // ``canAccessCreatorStudio`` is the same rule the /creator-studio and
  // /creator layout guards use — the doorway appears exactly for the
  // accounts that can walk through it.
  const items = memberNavItems({
    discoveryOn,
    waysToConnectOn,
    creatorStudioOn: canAccessCreatorStudio(user),
  })
  const displayName = user.name ?? 'Member'

  return (
    <header
      className="sticky top-0 z-50 backdrop-blur-xl"
      style={{
        background: 'rgba(255,255,255,0.95)',
        borderBottom: '1px solid #E8E8E5',
      }}
    >
      <Container className="flex h-16 items-center justify-between gap-4 xl:gap-8">
        {/* Brand → Your World */}
        <BrandLockup tone="light" href="/dashboard" />

        {/* Desktop nav — peer destinations with active state */}
        <nav
          aria-label="Member"
          className="hidden min-w-0 flex-1 items-center justify-center gap-4 min-[1152px]:flex"
        >
          {items.map(({ href, label }) => {
            const active = isNavItemActive(pathname, href)
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? 'page' : undefined}
                className={
                  'whitespace-nowrap text-[14px] transition-colors ' +
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
        <div className="hidden shrink-0 items-center gap-3 min-[1152px]:flex">
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
    <div className="min-[1152px]:hidden">
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
                const active = isNavItemActive(pathname, href)
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
