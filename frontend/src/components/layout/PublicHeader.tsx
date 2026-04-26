import Link from 'next/link'
import { cookies } from 'next/headers'
import Container from './Container'
import LogoutButton from './LogoutButton'
import MobileNav from './MobileNav'
import { SESSION_COOKIE } from '@/lib/session'
import { apiUrl } from '@/lib/api'

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

export default async function PublicHeader() {
  const user = await getCurrentUser()

  return (
    <header
      className="sticky top-0 z-50 backdrop-blur-xl"
      style={{
        background: 'rgba(8,15,30,0.85)',
        borderBottom: '1px solid rgba(255,255,255,0.07)',
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
          <span className="text-[15px] font-semibold tracking-[-0.02em] text-white transition-opacity group-hover:opacity-60">
            Fresh Collective
          </span>
        </Link>

        {/* Nav — desktop */}
        <nav aria-label="Main" className="hidden flex-1 items-center justify-center gap-8 md:flex">
          {[
            { href: '/about',        label: 'About' },
            { href: '/real-journey', label: 'REAL Journey' },
            { href: '/membership',   label: 'Membership' },
          ].map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className="text-[14px] font-medium transition-colors"
              style={{ color: 'rgba(255,255,255,0.62)' }}
            >
              {label}
            </Link>
          ))}
        </nav>

        {/* Auth — desktop */}
        <div className="hidden shrink-0 items-center gap-3 md:flex">
          {user ? (
            <>
              <Link
                href="/dashboard"
                className="text-[14px] font-medium transition-colors"
                style={{ color: 'rgba(255,255,255,0.62)' }}
              >
                Dashboard
              </Link>
              <LogoutButton
                className="rounded-xl px-4 py-2 text-[13px] font-medium transition-all"
                style={{
                  border: '1px solid rgba(255,255,255,0.12)',
                  background: 'rgba(255,255,255,0.06)',
                  color: 'rgba(255,255,255,0.72)',
                }}
              />
            </>
          ) : (
            <>
              <Link
                href="/login"
                className="text-[14px] font-medium transition-colors"
                style={{ color: 'rgba(255,255,255,0.62)' }}
              >
                Log in
              </Link>
              <Link
                href="/signup"
                className="rounded-xl px-5 py-2 text-[13px] font-semibold text-white transition-all"
                style={{
                  background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                  boxShadow: '0 2px 12px rgba(56,160,158,0.35)',
                }}
              >
                Join
              </Link>
            </>
          )}
        </div>

        {/* Mobile nav */}
        <MobileNav isLoggedIn={!!user} dark />

      </Container>
    </header>
  )
}
