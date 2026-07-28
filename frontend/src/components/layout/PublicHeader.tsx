import Link from 'next/link'
import { cookies } from 'next/headers'
import Container from './Container'
import LogoutButton from './LogoutButton'
import MobileNav from './MobileNav'
import NotificationBell from './NotificationBell'
import { SESSION_COOKIE } from '@/lib/session'
import { apiUrl } from '@/lib/api'
import { isDiscoveryPillarEnabled } from '@/lib/featureFlags'

interface MeResponse {
  id: string
  email: string
  name: string | null
  role: string
}

async function getCurrentUser(): Promise<MeResponse | null> {
  const cookieStore = await cookies()
  const session = cookieStore.get(SESSION_COOKIE)
  if (!session) return null
  try {
    const res = await fetch(apiUrl('/api/auth/me'), {
      headers: { Cookie: `${SESSION_COOKIE}=${session.value}` },
      cache: 'no-store',
    })
    if (!res.ok) return null
    return res.json() as Promise<MeResponse>
  } catch {
    return null
  }
}

// Peer destinations that live in the centre nav. Order is
// significant: it matches the pillar order defined in
// docs/foundations/discovery-connection-belonging-v1.1.md.
// "Your World" only appears for signed-in visitors; the other three
// are visible to everyone once the flag is on.
function peerNavItems(user: MeResponse | null, discoveryOn: boolean): Array<{ href: string; label: string }> {
  const items: Array<{ href: string; label: string }> = []
  if (user && discoveryOn) items.push({ href: '/dashboard', label: 'Your World' })
  items.push({ href: '/spaces', label: 'Explore Collectives' })
  if (discoveryOn) {
    items.push({ href: '/discover-places', label: 'Discover Places' })
    items.push({ href: '/ways-to-connect', label: 'Ways to Connect' })
  }
  return items
}

export default async function PublicHeader({ overlay = false }: { overlay?: boolean }) {
  const user = await getCurrentUser()
  const discoveryOn = isDiscoveryPillarEnabled()
  const centreNav   = peerNavItems(user, discoveryOn)
  // "Your World" only remains as a right-side auth-cluster shortcut
  // while Discovery is off; once the pillar is on it lives in the
  // centre nav as a peer destination.
  const showYourWorldOnRight = !discoveryOn && !!user

  if (overlay) {
    return (
      <header
        className="absolute top-0 left-0 right-0 z-50 py-5"
        style={{ background: 'transparent' }}
      >
        <Container className="flex h-14 items-center justify-between gap-8">

          <Link href="/" className="group flex shrink-0 items-center gap-2.5">
            <div
              className="flex h-7 w-7 items-center justify-center rounded-lg"
              style={{ background: 'linear-gradient(135deg, #38A09E, #55B8B6)', opacity: 0.90 }}
            >
              <div className="h-3 w-3 rounded-sm bg-white" style={{ opacity: 0.92 }} />
            </div>
            <span
              className="text-[15px] font-semibold tracking-[-0.02em] transition-opacity group-hover:opacity-60"
              style={{ color: '#FFFFFF' }}
            >
              Fresh Collective
            </span>
          </Link>

          <nav aria-label="Main" className="hidden flex-1 items-center justify-center gap-8 md:flex">
            {centreNav.map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                className="text-[14px] font-medium transition-opacity hover:opacity-100"
                style={{ color: '#FFFFFF' }}
              >
                {label}
              </Link>
            ))}
          </nav>

          <div className="hidden shrink-0 items-center gap-4 md:flex">
            {user ? (
              <>
                {showYourWorldOnRight && (
                  <Link href="/dashboard" className="text-[14px] font-medium transition-opacity hover:opacity-100" style={{ color: '#FFFFFF' }}>
                    Your World
                  </Link>
                )}
                <LogoutButton className="rounded-xl border border-white/20 px-4 py-2 text-[13px] font-medium text-white transition-all hover:border-white/35" />
              </>
            ) : (
              <>
                <Link href="/login" className="text-[14px] font-medium transition-opacity hover:opacity-100" style={{ color: '#FFFFFF' }}>
                  Log in
                </Link>
                <Link
                  href="/signup"
                  className="rounded-xl px-5 py-2 text-[13px] font-semibold text-white transition-all hover:opacity-90"
                  style={{
                    border: '1px solid rgba(255,255,255,0.22)',
                    background: 'rgba(255,255,255,0.10)',
                    backdropFilter: 'blur(8px)',
                  }}
                >
                  Join
                </Link>
              </>
            )}
          </div>

          <MobileNav isLoggedIn={!!user} discoveryOn={discoveryOn} dark />

        </Container>
      </header>
    )
  }

  return (
    <header
      className="sticky top-0 z-50 backdrop-blur-xl"
      style={{
        background: 'rgba(255,255,255,0.95)',
        borderBottom: '1px solid #E8E8E5',
      }}
    >
      <Container className="flex h-16 items-center justify-between gap-8">

        {/* Wordmark */}
        <Link href="/" className="group flex shrink-0 items-center gap-2.5">
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

        {/* Nav — desktop */}
        <nav aria-label="Main" className="hidden flex-1 items-center justify-center gap-8 md:flex">
          {centreNav.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className="text-[14px] font-medium text-navy-500 transition-colors hover:text-navy-950"
            >
              {label}
            </Link>
          ))}
        </nav>

        {/* Auth — desktop */}
        <div className="hidden shrink-0 items-center gap-3 md:flex">
          {user ? (
            <>
              <NotificationBell initialCount={0} />
              {showYourWorldOnRight && (
                <Link
                  href="/dashboard"
                  className="text-[14px] font-medium text-navy-500 transition-colors hover:text-navy-950"
                >
                  Your World
                </Link>
              )}
              <LogoutButton
                className="rounded-xl border border-navy-100 px-4 py-2 text-[13px] font-medium text-navy-600 transition-all hover:border-navy-200 hover:bg-navy-50"
              />
            </>
          ) : (
            <>
              <Link
                href="/login"
                className="text-[14px] font-medium text-navy-500 transition-colors hover:text-navy-950"
              >
                Log in
              </Link>
              <Link
                href="/signup"
                className="rounded-xl px-5 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
                style={{
                  background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                  boxShadow: '0 2px 12px rgba(56,160,158,0.30)',
                }}
              >
                Join
              </Link>
            </>
          )}
        </div>

        {/* Mobile nav — hamburger defaults to dark (navy) for light header */}
        <MobileNav isLoggedIn={!!user} discoveryOn={discoveryOn} />

      </Container>
    </header>
  )
}
