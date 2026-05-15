import { cookies } from 'next/headers'
import Link from 'next/link'
import Container from '@/components/layout/Container'
import LogoutButton from '@/components/layout/LogoutButton'
import Avatar from '@/components/ui/Avatar'
import { SESSION_COOKIE } from '@/lib/session'
import { apiUrl } from '@/lib/api'
import { getContinue, getSpaceEvents, getMyMemberships } from '@/lib/serverApi'
import { getCollectiveCoverStyle } from '@/lib/coverArt'
import type { ContinueResponse, EventSummary, SpaceMembership } from '@/types/platform'

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

function CollectiveTile({ membership }: { membership: SpaceMembership }) {
  const cs = getCollectiveCoverStyle(membership.space_slug)
  return (
    <Link
      href={`/spaces/${membership.space_slug}`}
      className="group block overflow-hidden rounded-2xl shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-lg"
    >
      <div
        className="relative px-6 py-8"
        style={{
          background: cs.background,
          backgroundSize: cs.backgroundSize ?? 'auto',
        }}
      >
        <div className="flex items-end justify-between gap-3">
          <div>
            <p
              className="mb-1 text-[9px] font-bold uppercase tracking-[0.20em]"
              style={{ color: cs.labelColor }}
            >
              Collective
            </p>
            <p
              className="font-serif text-xl leading-snug transition-opacity group-hover:opacity-90"
              style={{ color: cs.titleColor }}
            >
              {membership.space_name}
            </p>
          </div>
          <span
            className="shrink-0 rounded-lg border px-3 py-1.5 text-[12px] font-semibold opacity-0 transition-all group-hover:opacity-100"
            style={{
              color: cs.isDark ? '#FFFFFF' : '#073B3A',
              borderColor: cs.isDark ? 'rgba(255,255,255,0.35)' : 'rgba(56,160,158,0.40)',
              background: cs.isDark ? 'rgba(255,255,255,0.12)' : 'rgba(56,160,158,0.10)',
            }}
          >
            Enter →
          </span>
        </div>
      </div>
    </Link>
  )
}

export default async function DashboardPage() {
  const [user, continueData, events, memberships]: [
    User | null,
    ContinueResponse | null,
    EventSummary[],
    SpaceMembership[],
  ] = await Promise.all([
    getUser(),
    getContinue(),
    getSpaceEvents('fresh-collective'),
    getMyMemberships(),
  ])

  const firstName = user?.name?.split(' ')[0] ?? 'there'
  const displayName = user?.name ?? firstName
  const isCreatorOrAdmin = user?.role === 'creator' || user?.role === 'admin'

  const continueHref = continueData
    ? `/spaces/${continueData.space_slug}/pathways/${continueData.pathway_slug}/${continueData.step_slug}`
    : '/spaces/fresh-collective/pathways/real-journey/welcome'

  const nextEvent = events[0] ?? null

  const activeMemberships = memberships.filter((m) => m.status === 'active')

  return (
    <div className="flex min-h-screen flex-col bg-background">

      {/* ── Top navigation bar ── */}
      <header
        className="border-b border-border bg-surface py-3.5"
        style={{ borderTop: '2px solid #38A09E' }}
      >
        <Container className="flex items-center justify-between">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/brand/fresh-collective-logo-teal-gold-white.png"
            alt="Fresh Collective"
            style={{ height: '30px', width: 'auto' }}
          />
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
              background:
                'radial-gradient(rgba(56,160,158,0.10) 1px, transparent 1px), ' +
                'radial-gradient(circle at 88% 25%, rgba(66,199,198,0.18), transparent 38%), ' +
                'linear-gradient(135deg, #F2FBFA 0%, #EAF8F7 50%, #FAFAF8 100%)',
              backgroundSize: '22px 22px, 100% 100%, 100% 100%',
              border: '1px solid rgba(56,160,158,0.15)',
            }}
          >
            <div className="mb-4 h-[2px] w-8 rounded-full bg-teal-400" />
            <h1 className="font-serif text-3xl text-navy-900 md:text-4xl">
              Welcome back, {firstName}.
            </h1>
            <p className="mt-2 text-[15px] text-slate-600">
              Ready to continue where you left off?
            </p>
          </div>

          {/* ── Two-column: Continue + Coming up ── */}
          <div className="mb-6 grid gap-4 sm:grid-cols-2">

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
              <p className="mt-3 text-[12px] font-semibold" style={{ color: '#38A09E' }}>
                {continueData?.all_complete ? 'Review →' : 'Continue →'}
              </p>
            </Link>

            {/* Coming up */}
            {nextEvent ? (
              <Link
                href={`/spaces/fresh-collective/events/${nextEvent.id}`}
                className="group flex flex-col rounded-2xl border bg-white p-5 transition-all hover:-translate-y-0.5 hover:shadow-md"
                style={{ borderColor: 'rgba(56,160,158,0.20)', borderLeft: '3px solid #55B8B6' }}
              >
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-teal-600">
                  Coming up
                </p>
                <p className="flex-1 font-serif text-[17px] leading-snug text-navy-900 transition-colors group-hover:text-teal-700">
                  {nextEvent.title}
                </p>
                <p className="mt-1.5 text-[12px] text-slate-400">
                  {formatEventDate(nextEvent.starts_at)}
                </p>
                <p className="mt-3 text-[12px] font-semibold text-teal-600">View details →</p>
              </Link>
            ) : (
              <div
                className="flex flex-col rounded-2xl border bg-white p-5"
                style={{ borderColor: 'rgba(56,160,158,0.15)', borderLeft: '3px solid rgba(56,160,158,0.30)' }}
              >
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-teal-500">
                  Coming up
                </p>
                <p className="flex-1 font-serif text-[17px] text-slate-400">No upcoming events yet.</p>
                <p className="mt-3 text-[12px] text-slate-400">Check back soon.</p>
              </div>
            )}
          </div>

          {/* ── My collectives ── */}
          {activeMemberships.length > 0 && (
            <section className="mb-6">
              <div className="mb-3 flex items-baseline justify-between">
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">
                  My collectives
                </p>
                <Link href="/dashboard/explore" className="text-xs text-teal-600 hover:underline">
                  Explore more →
                </Link>
              </div>
              <div className={[
                'grid gap-4',
                activeMemberships.length === 1 ? '' : 'sm:grid-cols-2',
              ].join(' ')}>
                {activeMemberships.map((m) => (
                  <CollectiveTile key={m.space_id} membership={m} />
                ))}
              </div>
            </section>
          )}

          {/* Fallback if no memberships fetched yet */}
          {activeMemberships.length === 0 && (
            <section className="mb-6">
              {(() => {
                const cs = getCollectiveCoverStyle('fresh-collective')
                return (
                  <Link
                    href="/spaces/fresh-collective"
                    className="group block overflow-hidden rounded-2xl shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-xl"
                  >
                    <div
                      className="relative px-7 py-10 md:py-12"
                      style={{
                        background: cs.background,
                        backgroundSize: cs.backgroundSize ?? 'auto',
                      }}
                    >
                      <div className="flex items-end justify-between gap-4">
                        <div>
                          <p
                            className="mb-1 text-[9px] font-bold uppercase tracking-[0.20em]"
                            style={{ color: cs.labelColor }}
                          >
                            Your collective
                          </p>
                          <p
                            className="font-serif text-2xl transition-opacity group-hover:opacity-90"
                            style={{ color: cs.titleColor }}
                          >
                            Fresh Collective
                          </p>
                        </div>
                        <span
                          className="shrink-0 rounded-lg border px-4 py-2 text-[13px] font-semibold opacity-0 transition-all group-hover:opacity-100"
                          style={{
                            color: cs.isDark ? '#FFFFFF' : '#073B3A',
                            borderColor: cs.isDark ? 'rgba(255,255,255,0.35)' : 'rgba(56,160,158,0.40)',
                            background: cs.isDark ? 'rgba(255,255,255,0.12)' : 'rgba(56,160,158,0.10)',
                          }}
                        >
                          Enter →
                        </span>
                      </div>
                    </div>
                  </Link>
                )
              })()}
            </section>
          )}

          {/* ── Explore collectives ── */}
          <section className="mb-4">
            <Link
              href="/dashboard/explore"
              className="group block overflow-hidden rounded-2xl border transition-all hover:-translate-y-0.5 hover:shadow-md"
              style={{
                background:
                  'radial-gradient(circle at 20% 60%, rgba(66,199,198,0.12), transparent 35%), ' +
                  'linear-gradient(135deg, #EAF8F7 0%, #F5FCFB 100%)',
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
                      Find other guided collectives, pathways, and communities to join.
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
          {isCreatorOrAdmin && (
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
