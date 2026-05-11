import { cookies } from 'next/headers'
import Link from 'next/link'
import Container from '@/components/layout/Container'
import LogoutButton from '@/components/layout/LogoutButton'
import { SESSION_COOKIE } from '@/lib/session'
import { apiUrl } from '@/lib/api'
import { getSpace } from '@/lib/serverApi'
import PathwayCard from '@/components/spaces/PathwayCard'
import type { PathwaySummary } from '@/types/platform'

interface User {
  id: string
  email: string
  name: string | null
  role: string
}

async function getUser(): Promise<User | null> {
  const cookieStore = await cookies()
  const session = cookieStore.get(SESSION_COOKIE)
  if (!session) return null
  try {
    const res = await fetch(apiUrl('/api/auth/me'), {
      headers: { Cookie: `${SESSION_COOKIE}=${session.value}` },
      cache: 'no-store',
    })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

export default async function DashboardPage() {
  const [user, space] = await Promise.all([
    getUser(),
    getSpace('fresh-collective'),
  ])

  const firstName = user?.name?.split(' ')[0] ?? 'there'
  const pathways: PathwaySummary[] = space?.pathways ?? []
  const realJourney = pathways.find((p) => p.slug === 'real-journey')

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header
        className="border-b border-border bg-surface py-4"
        style={{ borderTop: '2px solid var(--color-gold-500)' }}
      >
        <Container className="flex items-center justify-between">
          <span className="font-serif text-xl tracking-wide text-navy-900">Fresh Collective</span>
          <div className="flex items-center gap-4">
            <span className="hidden text-sm text-[#4A5568] md:block">{user?.email}</span>
            <LogoutButton className="rounded-lg border border-navy-300 px-4 py-2 text-sm font-medium text-navy-700 transition-colors hover:border-navy-500 hover:bg-navy-50" />
          </div>
        </Container>
      </header>

      <main className="flex-1 py-12">
        <Container>
          <div className="mb-10">
            <div className="mb-4 h-px w-6 bg-gold-500" />
            <h1 className="mb-3 font-serif text-4xl text-navy-900">Welcome back, {firstName}.</h1>
            <Link
              href="/spaces/fresh-collective"
              className="inline-block rounded-full bg-teal-500 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-teal-600"
            >
              Enter Fresh Collective →
            </Link>
          </div>

          {realJourney && (
            <section className="mb-10">
              <div className="mb-4 text-xs font-medium uppercase tracking-widest text-gold-700">
                Your Foundation
              </div>
              <div className="max-w-sm">
                <PathwayCard pathway={realJourney} spaceSlug="fresh-collective" />
              </div>
            </section>
          )}

          <section>
            <div className="mb-4 text-xs font-medium uppercase tracking-widest text-gold-700">
              Also Inside
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              {[
                { label: 'Community', desc: 'Connect with the women in your space.', href: '/spaces/fresh-collective/community' },
                { label: 'Events', desc: 'Live calls, workshops, and gatherings.', href: '/spaces/fresh-collective/events' },
              ].map(({ label, desc, href }) => (
                <Link
                  key={label}
                  href={href}
                  className="rounded-xl border border-border bg-surface p-5 transition-shadow hover:shadow-[var(--fc-shadow-card)]"
                >
                  <h3 className="mb-1 font-serif text-lg text-navy-900">{label}</h3>
                  <p className="text-sm text-slate-500">{desc}</p>
                </Link>
              ))}
            </div>
          </section>
        </Container>
      </main>
    </div>
  )
}
