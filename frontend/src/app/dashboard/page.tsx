import { cookies } from 'next/headers'
import Link from 'next/link'
import Container from '@/components/layout/Container'
import LogoutButton from '@/components/layout/LogoutButton'
import Avatar from '@/components/ui/Avatar'
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

function formatEventDate(isoString: string): string {
  const d = new Date(isoString)
  return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
}

export default async function DashboardPage() {
  const [user, continueData, events]: [User | null, ContinueResponse | null, EventSummary[]] =
    await Promise.all([getUser(), getContinue(), getSpaceEvents('fresh-collective')])

  const firstName = user?.name?.split(' ')[0] ?? 'there'
  const displayName = user?.name ?? firstName
  const continueHref = continueData
    ? `/spaces/${continueData.space_slug}/pathways/${continueData.pathway_slug}/${continueData.step_slug}`
    : '/spaces/fresh-collective/pathways/real-journey/welcome'

  const nextEvent = events[0] ?? null

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header
        className="border-b border-border bg-surface py-3.5"
        style={{ borderTop: '2px solid var(--color-gold-500)' }}
      >
        <Container className="flex items-center justify-between">
          <span className="font-serif text-lg text-navy-900">Fresh Collective</span>
          <div className="flex items-center gap-2">
            <Link
              href="/settings"
              className="rounded-lg px-3 py-2 text-sm text-slate-500 transition-colors hover:text-navy-700"
            >
              Settings
            </Link>
            <Link
              href="/settings/profile"
              className="ml-1 flex items-center gap-2 rounded-lg px-2 py-1.5 transition-colors hover:bg-slate-50"
              aria-label="Your profile"
            >
              <Avatar name={displayName} size="sm" />
            </Link>
          </div>
        </Container>
      </header>

      <main className="flex-1 py-12">
        <Container>

          {/* Greeting */}
          <div className="mb-10">
            <div className="mb-3 h-px w-6 bg-gold-500" />
            <h1 className="font-serif text-3xl text-navy-900 md:text-4xl">
              Welcome back, {firstName}.
            </h1>
            <p className="mt-2 text-sm text-slate-400">
              Ready to continue where you left off?
            </p>
          </div>

          {/* Primary CTA — Enter the Space */}
          <section className="mb-8">
            <Link
              href="/spaces/fresh-collective"
              className="group block rounded-xl border border-teal-200 bg-teal-50/40 px-7 py-6 transition-all hover:border-teal-300 hover:shadow-[var(--fc-shadow-card)]"
              style={{ borderLeft: '3px solid var(--color-teal-500)' }}
            >
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="mb-0.5 text-xs font-semibold uppercase tracking-widest text-teal-600">
                    Your space
                  </p>
                  <p className="font-serif text-2xl text-navy-900 group-hover:text-teal-700 transition-colors">
                    Fresh Collective
                  </p>
                  <p className="mt-1 text-sm text-slate-400">
                    {continueData && !continueData.all_complete
                      ? `Next: ${continueData.step_title}`
                      : 'Your home for guided learning and reflection.'}
                  </p>
                </div>
                <span className="shrink-0 text-teal-500 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true">
                  →
                </span>
              </div>
            </Link>
          </section>

          {/* Two-column: Continue + Next event */}
          <div className="grid gap-4 sm:grid-cols-2">

            {/* Continue step */}
            <Link
              href={continueHref}
              className="group flex flex-col rounded-xl border border-border bg-surface p-5 transition-all hover:border-slate-200 hover:shadow-[var(--fc-shadow-card)]"
            >
              <p className="mb-1.5 text-xs font-semibold uppercase tracking-widest text-gold-600">
                {continueData?.all_complete ? 'Journey complete' : 'Next step'}
              </p>
              <p className="flex-1 font-serif text-base leading-snug text-navy-900 group-hover:text-teal-700 transition-colors">
                {continueData ? continueData.step_title : 'Begin the REAL Journey'}
              </p>
              {continueData && !continueData.all_complete && (
                <p className="mt-2 text-xs text-slate-400">{continueData.pathway_title}</p>
              )}
              <p className="mt-3 text-xs font-medium text-teal-600">
                {continueData?.all_complete ? 'Review →' : 'Continue →'}
              </p>
            </Link>

            {/* Next event */}
            {nextEvent ? (
              <Link
                href={`/spaces/fresh-collective/events/${nextEvent.id}`}
                className="group flex flex-col rounded-xl border border-border bg-surface p-5 transition-all hover:border-slate-200 hover:shadow-[var(--fc-shadow-card)]"
              >
                <p className="mb-1.5 text-xs font-semibold uppercase tracking-widest text-gold-600">
                  Coming up
                </p>
                <p className="flex-1 font-serif text-base leading-snug text-navy-900 group-hover:text-teal-700 transition-colors">
                  {nextEvent.title}
                </p>
                <p className="mt-2 text-xs text-slate-400">{formatEventDate(nextEvent.starts_at)}</p>
                <p className="mt-3 text-xs font-medium text-teal-600">View details →</p>
              </Link>
            ) : (
              <div className="flex flex-col rounded-xl border border-border bg-surface p-5">
                <p className="mb-1.5 text-xs font-semibold uppercase tracking-widest text-gold-600">
                  Coming up
                </p>
                <p className="flex-1 font-serif text-base text-slate-400">
                  No upcoming events yet.
                </p>
                <p className="mt-3 text-xs text-slate-300">Check back soon.</p>
              </div>
            )}

          </div>

          {/* Explore collectives */}
          <section className="mt-4">
            <Link
              href="/dashboard/explore"
              className="group block rounded-xl border border-border bg-surface px-7 py-5 transition-all hover:border-teal-200 hover:shadow-[var(--fc-shadow-card)]"
            >
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="mb-0.5 text-xs font-semibold uppercase tracking-widest text-teal-600">
                    Discover
                  </p>
                  <p className="font-serif text-xl text-navy-900 transition-colors group-hover:text-teal-700">
                    Explore collectives
                  </p>
                  <p className="mt-1 text-sm text-slate-400">
                    Find other guided collectives, pathways, and communities you may want to join.
                  </p>
                </div>
                <span className="shrink-0 rounded-lg border border-teal-200 px-4 py-1.5 text-[13px] font-medium text-teal-700 transition-colors group-hover:bg-teal-50">
                  Browse collectives →
                </span>
              </div>
            </Link>
          </section>

          {/* Creator Studio — visible to creators/admins */}
          {(user?.role === 'creator' || user?.role === 'admin') && (
            <section className="mt-4">
              <Link
                href="/creator-studio"
                className="group block rounded-xl border border-border bg-surface px-7 py-5 transition-all hover:border-teal-200 hover:shadow-[var(--fc-shadow-card)]"
              >
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <p className="mb-0.5 text-xs font-semibold uppercase tracking-widest text-teal-600">
                      Creator
                    </p>
                    <p className="font-serif text-xl text-navy-900 transition-colors group-hover:text-teal-700">
                      Creator Studio
                    </p>
                    <p className="mt-1 text-sm text-slate-400">
                      Manage your collective, pathways, and gatherings.
                    </p>
                  </div>
                  <span
                    className="shrink-0 text-teal-500 opacity-0 transition-opacity group-hover:opacity-100"
                    aria-hidden="true"
                  >
                    →
                  </span>
                </div>
              </Link>
            </section>
          )}

          {/* Logout — tucked away at bottom */}
          <div className="mt-12 border-t border-border pt-6 flex justify-end">
            <LogoutButton className="text-xs text-slate-400 hover:text-slate-600 transition-colors" />
          </div>

        </Container>
      </main>
    </div>
  )
}
