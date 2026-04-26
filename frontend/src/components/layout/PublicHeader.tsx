import Link from 'next/link'
import { cookies } from 'next/headers'
import Container from './Container'
import LogoutButton from './LogoutButton'
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
      className="border-b border-border bg-surface py-5"
      style={{ borderTop: '2px solid var(--color-gold-500)' }}
    >
      <Container className="flex items-center justify-between">
        <Link
          href="/"
          className="font-serif text-xl tracking-wide text-navy-900 transition-colors hover:text-navy-700"
        >
          Fresh Collective
        </Link>

        <nav aria-label="Main navigation" className="hidden items-center gap-8 md:flex">
          <Link href="/about" className="text-sm text-[#4A5568] transition-colors hover:text-navy-900">
            About
          </Link>
          <Link href="/real-journey" className="text-sm text-[#4A5568] transition-colors hover:text-navy-900">
            REAL Journey
          </Link>
          <Link href="/membership" className="text-sm text-[#4A5568] transition-colors hover:text-navy-900">
            Membership
          </Link>
        </nav>

        <div className="flex items-center gap-4">
          {user ? (
            <>
              <Link
                href="/dashboard"
                className="hidden text-sm text-[#4A5568] transition-colors hover:text-navy-900 md:block"
              >
                Dashboard
              </Link>
              <LogoutButton className="inline-flex items-center justify-center rounded-lg border border-navy-300 px-4 py-2 text-sm font-medium text-navy-700 transition-colors duration-200 hover:border-navy-500 hover:bg-navy-50" />
            </>
          ) : (
            <>
              <Link
                href="/login"
                className="hidden text-sm text-[#4A5568] transition-colors hover:text-navy-900 md:block"
              >
                Log in
              </Link>
              <Link
                href="/signup"
                className="inline-flex items-center justify-center rounded-lg border border-transparent bg-teal-500 px-4 py-2 text-sm font-medium text-white transition-colors duration-200 hover:bg-teal-700"
              >
                Join
              </Link>
            </>
          )}
        </div>
      </Container>
    </header>
  )
}
