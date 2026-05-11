import { cookies } from 'next/headers'
import Link from 'next/link'
import Container from '@/components/layout/Container'
import LogoutButton from '@/components/layout/LogoutButton'
import { SESSION_COOKIE } from '@/lib/session'
import { apiUrl } from '@/lib/api'
import { getContinue, getSpaceEvents } from '@/lib/serverApi'
import type { ContinueResponse, EventSummary } from '@/types/platform'

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

function formatEventDateShort(isoString: string): string {
  const d = new Date(isoString)
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

export default async function DashboardPage() {
  const [user, continueData, events]: [User | null, ContinueResponse | null, EventSummary[]] =
    await Promise.all([getUser(), getContinue(), getSpaceEvents('fresh-collective')])

  const firstName = user?.name?.split(' ')[0] ?? 'there'
  const continueHref = continueData
    ? `/spaces/${continueData.space_slug}/pathways/${continueData.pathway_slug}/${continueData.step_slug}`
    : '/spaces/fresh-collective/pathways/real-journey/welcome'

  const nextEvent = events[0] ?? null

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header
        className="border-b border-border bg-surface py-4"
        style={{ borderTop: '2px solid var(--color-gold-500)' }}
      >
        <Container className="flex items-center justify-between">
          <span className="font-serif text-xl tracking-wide text-navy-900">Fresh Collective</span>
          <div className="flex items-center gap-3">
            <Link
              href="/settings"
              className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-slate-600 transition-colors hover:border-slate-300 hover:text-navy-700"
            >
              Settings
            </Link>
            <LogoutButton className="rounded-lg border border-navy-300 px-4 py-2 text-sm font-medium text-navy-700 transition-colors hover:border-navy-500 hover:bg-navy-50" />
          </div>
        </Container>
      </header>

      <main className="flex-1 py-12">
        <Container>

          {/* Greeting */}
          <div className="mb-10">
            <div className="mb-4 h-px w-6 bg-gold-500" />
            <h1 className="font-serif text-4xl text-navy-900">Welcome back, {firstName}.</h1>
          </div>

          {/* Primary CTA — Enter the Space */}
          <section className="mb-10">
            <Link
              href="/spaces/fresh-collective"
              className="group block rounded-xl border border-teal-200 bg-teal-50/50 px-7 py-6 transition-shadow hover:shadow-[var(--fc-shadow-card)]"
              style={{ borderLeft: '3px solid var(--color-teal-500)' }}
            >
              <p className="mb-0.5 text-xs font-medium uppercase tracking-widest text-teal-600">
                Your space
              </p>
              <p className="font-serif text-2xl text-navy-900 group-hover:text-teal-700 transition-colors">
                Fresh Collective
              </p>
              <p className="mt-1 text-sm text-slate-400">
                {continueData && !continueData.all_complete
                  ? `Continue: ${continueData.step_title}`
                  : 'Your home for guided learning and reflection.'}
              </p>
              <p className="mt-3 text-sm font-medium text-teal-600 group-hover:underline">
                Enter space →
              </p>
            </Link>
          </section>

          {/* Two-column: Continue step + Next event */}
          <div className="grid gap-5 sm:grid-cols-2">

            {/* Continue step */}
            <Link
              href={continueHref}
              className="group flex flex-col rounded-xl border border-border bg-surface p-5 transition-shadow hover:shadow-[var(--fc-shadow-card)]"
            >
              <p className="mb-1 text-xs font-medium uppercase tracking-widest text-gold-600">
                {continueData?.all_complete ? 'Journey complete' : 'Next step'}
              </p>
              <p className="flex-1 font-serif text-base text-navy-900 group-hover:text-teal-700 transition-colors leading-snug">
                {continueData ? continueData.step_title : 'Begin the REAL Journey'}
              </p>
              {continueData && !continueData.all_complete && (
                <p className="mt-2 text-xs text-slate-400">{continueData.pathway_title}</p>
              )}
              <p className="mt-3 text-xs text-teal-600 group-hover:underline">
                {continueData?.all_complete ? 'Review' : 'Go →'}
              </p>
            </Link>

            {/* Next event */}
            {nextEvent ? (
              <Link
                href="/spaces/fresh-collective/events"
                className="group flex flex-col rounded-xl border border-border bg-surface p-5 transition-shadow hover:shadow-[var(--fc-shadow-card)]"
              >
                <p className="mb-1 text-xs font-medium uppercase tracking-widest text-gold-600">
                  Coming up
                </p>
                <p className="flex-1 font-serif text-base text-navy-900 group-hover:text-teal-700 transition-colors leading-snug">
                  {nextEvent.title}
                </p>
                <p className="mt-2 text-xs text-slate-400">
                  {formatEventDateShort(nextEvent.starts_at)}
                </p>
                <p className="mt-3 text-xs text-teal-600 group-hover:underline">View details →</p>
              </Link>
            ) : (
              <div className="flex flex-col rounded-xl border border-border bg-surface p-5">
                <p className="mb-1 text-xs font-medium uppercase tracking-widest text-gold-600">
                  Coming up
                </p>
                <p className="flex-1 text-sm text-slate-400">
                  No upcoming events yet. Check back soon.
                </p>
              </div>
            )}
          </div>

        </Container>
      </main>
    </div>
  )
}
