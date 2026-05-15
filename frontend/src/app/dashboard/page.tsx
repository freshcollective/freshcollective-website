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

      {/* ── Top navigation bar ── */}
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

      <main className="flex-1 py-10">
        <Container>

          {/* ── Welcome hero ── */}
          <div
            className="mb-6 overflow-hidden rounded-2xl px-8 py-8 md:px-10 md:py-9"
            style={{
              background: 'linear-gradient(135deg, #EAF7F7 0%, #F0FBFA 55%, #FAFAF8 100%)',
              border: '1px solid rgba(56,160,158,0.18)',
            }}
          >
            <div
              className="mb-4 h-[2px] w-8"
              style={{ background: 'linear-gradient(90deg, #38A09E 0%, transparent 100%)' }}
            />
            <h1 className="font-serif text-3xl text-navy-900 md:text-4xl">
              Welcome back, {firstName}.
            </h1>
            <p className="mt-2 text-[15px] text-slate-600">
              Ready to continue where you left off?
            </p>
          </div>

          {/* ── Your space (featured collective card — the one deep-teal element) ── */}
          <section className="mb-4">
            <Link
              href="/spaces/fresh-collective"
              className="group block overflow-hidden rounded-2xl transition-all hover:-translate-y-0.5 hover:shadow-xl"
              style={{
                background: 'linear-gradient(135deg, #073B3A 0%, #0d4f4d 50%, #062F35 100%)',
              }}
            >
              <div className="px-7 py-6">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <p
                      className="mb-0.5 text-[10px] font-semibold uppercase tracking-[0.16em]"
                      style={{ color: 'rgba(255,255,255,0.60)' }}
                    >
                      Your space
                    </p>
                    <p className="font-serif text-2xl text-white transition-opacity group-hover:opacity-90">
                      Fresh Collective
                    </p>
                    <p
                      className="mt-1.5 text-[14px] leading-snug"
                      style={{ color: 'rgba(255,255,255,0.75)' }}
                    >
                      {continueData && !continueData.all_complete
                        ? `Next: ${continueData.step_title}`
                        : 'Your home for guided learning and reflection.'}
                    </p>
                  </div>
                  <span
                    className="shrink-0 rounded-lg border px-4 py-2 text-[13px] font-semibold text-white opacity-0 transition-all group-hover:opacity-100"
                    style={{ borderColor: 'rgba(255,255,255,0.35)', background: 'rgba(255,255,255,0.12)' }}
                  >
                    Enter →
                  </span>
                </div>
              </div>
            </Link>
          </section>

          {/* ── Two-column: Continue + Coming up ── */}
          <div className="mb-4 grid gap-4 sm:grid-cols-2">

            {/* Continue step */}
            <Link
              href={continueHref}
              className="group flex flex-col rounded-2xl border bg-white p-5 transition-all hover:-translate-y-0.5 hover:shadow-md"
              style={{ borderColor: 'rgba(56,160,158,0.20)', borderLeft: '3px solid #38A09E' }}
            >
              <p
                className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em]"
                style={{ color: '#38A09E' }}
              >
                {continueData?.all_complete ? 'Journey complete' : 'Next step'}
              </p>
              <p className="flex-1 font-serif text-[17px] leading-snug text-navy-900 transition-colors group-hover:text-teal-700">
                {continueData ? continueData.step_title : 'Begin the REAL Journey'}
              </p>
              {continueData && !continueData.all_complete && (
                <p className="mt-1.5 text-[12px] text-slate-400">{continueData.pathway_title}</p>
              )}
              <p
                className="mt-3 text-[12px] font-semibold"
                style={{ color: '#38A09E' }}
              >
                {continueData?.all_complete ? 'Review →' : 'Continue →'}
              </p>
            </Link>

            {/* Coming up */}
            {nextEvent ? (
              <Link
                href={`/spaces/fresh-collective/events/${nextEvent.id}`}
                className="group flex flex-col rounded-2xl border bg-white p-5 transition-all hover:-translate-y-0.5 hover:shadow-md"
                style={{ borderColor: 'rgba(166,126,30,0.20)', borderLeft: '3px solid var(--color-gold-400)' }}
              >
                <p
                  className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em]"
                  style={{ color: 'var(--color-gold-500)' }}
                >
                  Coming up
                </p>
                <p className="flex-1 font-serif text-[17px] leading-snug text-navy-900 transition-colors group-hover:text-teal-700">
                  {nextEvent.title}
                </p>
                <p className="mt-1.5 text-[12px] text-slate-400">
                  {formatEventDate(nextEvent.starts_at)}
                </p>
                <p
                  className="mt-3 text-[12px] font-semibold"
                  style={{ color: 'var(--color-gold-500)' }}
                >
                  View details →
                </p>
              </Link>
            ) : (
              <div
                className="flex flex-col rounded-2xl border bg-white p-5"
                style={{ borderColor: 'rgba(166,126,30,0.15)', borderLeft: '3px solid rgba(166,126,30,0.25)' }}
              >
                <p
                  className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em]"
                  style={{ color: 'var(--color-gold-500)' }}
                >
                  Coming up
                </p>
                <p className="flex-1 font-serif text-[17px] text-slate-400">
                  No upcoming events yet.
                </p>
                <p className="mt-3 text-[12px] text-slate-400">Check back soon.</p>
              </div>
            )}
          </div>

          {/* ── Explore collectives ── */}
          <section className="mb-4">
            <Link
              href="/dashboard/explore"
              className="group block overflow-hidden rounded-2xl border transition-all hover:-translate-y-0.5 hover:shadow-md"
              style={{
                background: 'linear-gradient(135deg, #EAF7F7 0%, #F0FBFA 100%)',
                borderColor: 'rgba(56,160,158,0.25)',
              }}
            >
              <div className="px-7 py-5">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <p className="mb-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-teal-600">
                      Discover
                    </p>
                    <p className="font-serif text-xl text-navy-900 transition-colors group-hover:text-teal-700">
                      Explore collectives
                    </p>
                    <p className="mt-1 text-[13px] text-slate-500">
                      Find other guided collectives, pathways, and communities you may want to join.
                    </p>
                  </div>
                  <span
                    className="shrink-0 rounded-lg px-4 py-1.5 text-[12px] font-semibold text-white transition-opacity group-hover:opacity-90"
                    style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
                  >
                    Browse →
                  </span>
                </div>
              </div>
            </Link>
          </section>

          {/* ── Creator Studio ── */}
          {(user?.role === 'creator' || user?.role === 'admin') && (
            <section className="mb-4">
              <Link
                href="/creator-studio"
                className="group block overflow-hidden rounded-2xl border border-border bg-white transition-all hover:-translate-y-0.5 hover:border-teal-200 hover:shadow-md"
              >
                <div className="h-[2px]" style={{ background: 'linear-gradient(90deg, #38A09E 0%, transparent 60%)' }} />
                <div className="flex items-center justify-between gap-4 px-7 py-5">
                  <div>
                    <p className="mb-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-teal-600">
                      Creator
                    </p>
                    <p className="font-serif text-xl text-navy-900 transition-colors group-hover:text-teal-700">
                      Creator Studio
                    </p>
                    <p className="mt-1 text-[13px] text-slate-400">
                      Manage your collective, pathways, and gatherings.
                    </p>
                  </div>
                  <span className="shrink-0 text-teal-500 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true">
                    →
                  </span>
                </div>
              </Link>
            </section>
          )}

          {/* Logout */}
          <div className="mt-10 border-t border-border pt-6 flex justify-end">
            <LogoutButton className="text-xs text-slate-400 hover:text-slate-600 transition-colors" />
          </div>

        </Container>
      </main>
    </div>
  )
}
