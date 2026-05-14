import Link from 'next/link'
import Container from './Container'
import { getSession } from '@/lib/auth/session'
import { logout } from '@/lib/auth/actions'

export default async function PublicHeader({ overlay = false }: { overlay?: boolean }) {
  const session = await getSession()

  if (overlay) {
    return (
      <header className="absolute top-0 left-0 right-0 z-50 py-6">
        <Container className="flex items-center justify-between">
          <Link
            href="/"
            className="font-serif text-xl tracking-wide text-white/90 transition-colors hover:text-white"
          >
            Fresh Collective
          </Link>

          <nav aria-label="Main navigation" className="hidden items-center gap-8 md:flex">
            <Link href="/about" className="text-sm text-white/60 transition-colors hover:text-white">About</Link>
            <Link href="/real-journey" className="text-sm text-white/60 transition-colors hover:text-white">REAL Journey</Link>
            <Link href="/membership" className="text-sm text-white/60 transition-colors hover:text-white">Membership</Link>
          </nav>

          <div className="flex items-center gap-4">
            {session ? (
              <>
                <Link href="/dashboard" className="hidden text-sm text-white/60 transition-colors hover:text-white md:block">Dashboard</Link>
                <form action={logout}>
                  <button type="submit" className="inline-flex items-center justify-center rounded-lg border border-white/30 px-4 py-2 text-sm font-medium text-white/80 transition-colors duration-200 hover:border-white/60 hover:text-white">
                    Log out
                  </button>
                </form>
              </>
            ) : (
              <>
                <Link href="/login" className="hidden text-sm text-white/60 transition-colors hover:text-white md:block">Log in</Link>
                <Link href="/signup" className="inline-flex items-center justify-center rounded-lg border border-white/30 bg-white/10 px-4 py-2 text-sm font-medium text-white backdrop-blur-sm transition-colors duration-200 hover:bg-white/20">
                  Join
                </Link>
              </>
            )}
          </div>
        </Container>
      </header>
    )
  }

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
          <Link href="/about" className="text-sm text-[#4A5568] transition-colors hover:text-navy-900">About</Link>
          <Link href="/real-journey" className="text-sm text-[#4A5568] transition-colors hover:text-navy-900">REAL Journey</Link>
          <Link href="/membership" className="text-sm text-[#4A5568] transition-colors hover:text-navy-900">Membership</Link>
        </nav>

        <div className="flex items-center gap-4">
          {session ? (
            <>
              <Link href="/dashboard" className="hidden text-sm text-[#4A5568] transition-colors hover:text-navy-900 md:block">Dashboard</Link>
              <form action={logout}>
                <button type="submit" className="inline-flex items-center justify-center rounded-lg border border-navy-300 px-4 py-2 text-sm font-medium text-navy-700 transition-colors duration-200 hover:border-navy-500 hover:bg-navy-50">
                  Log out
                </button>
              </form>
            </>
          ) : (
            <>
              <Link href="/login" className="hidden text-sm text-[#4A5568] transition-colors hover:text-navy-900 md:block">Log in</Link>
              <Link href="/signup" className="inline-flex items-center justify-center rounded-lg border border-transparent bg-teal-500 px-4 py-2 text-sm font-medium text-white transition-colors duration-200 hover:bg-teal-700">
                Join
              </Link>
            </>
          )}
        </div>
      </Container>
    </header>
  )
}
