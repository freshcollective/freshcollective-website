import { cookies } from 'next/headers'
import Link from 'next/link'
import Container from '@/components/layout/Container'
import LogoutButton from '@/components/layout/LogoutButton'
import Avatar from '@/components/ui/Avatar'
import { SESSION_COOKIE } from '@/lib/session'
import { apiUrl } from '@/lib/api'
import { getContinue, getSpaceEvents, getMyMemberships, getCommunityFeed } from '@/lib/serverApi'
import { getCollectiveCoverStyle } from '@/lib/coverArt'
import type { ContinueResponse, EventSummary, SpaceMembership, PostSummary } from '@/types/platform'

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

function parseDateBlock(isoString: string) {
  const d = new Date(isoString)
  return {
    day: d.toLocaleDateString('en-GB', { day: '2-digit' }),
    month: d.toLocaleDateString('en-GB', { month: 'short' }).toUpperCase(),
    time: d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }),
  }
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
  const [user, continueData, events, memberships, communityPosts]: [
    User | null,
    ContinueResponse | null,
    EventSummary[],
    SpaceMembership[],
    PostSummary[],
  ] = await Promise.all([
    getUser(),
    getContinue(),
    getSpaceEvents('fresh-collective'),
    getMyMemberships(),
    getCommunityFeed('fresh-collective'),
  ])

  const firstName = user?.name?.split(' ')[0] ?? 'there'
  const displayName = user?.name ?? firstName
  const isCreatorOrAdmin = user?.role === 'creator' || user?.role === 'admin'

  const continueHref = continueData
    ? `/spaces/${continueData.space_slug}/pathways/${continueData.pathway_slug}/${continueData.step_slug}`
    : '/spaces/fresh-collective/pathways/real-journey/welcome'

  const nextEvent = events[0] ?? null
  const nextEventDate = nextEvent ? parseDateBlock(nextEvent.starts_at) : null
  const recentPost = communityPosts[0] ?? null
  const activeMemberships = memberships.filter((m) => m.status === 'active')

  return (
    <div className="flex min-h-screen flex-col bg-background">

      {/* ── Top navigation bar ── */}
      <header
        className="border-b border-border bg-surface py-3.5"
        style={{ borderTop: '2px solid #38A09E' }}
      >
        <Container className="flex items-center justify-between">
          <span className="font-serif text-xl text-navy-900">Fresh Collective</span>
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
            className="mb-6 overflow-hidden rounded-2xl px-8 py-10 md:px-10 md:py-12"
            style={{
              background:
                'radial-gradient(rgba(66,199,198,0.08) 1px, transparent 1px), ' +
                'radial-gradient(ellipse at 88% 25%, rgba(66,199,198,0.30), transparent 50%), ' +
                'radial-gradient(ellipse at 12% 78%, rgba(56,160,158,0.18), transparent 45%), ' +
                'linear-gradient(135deg, #071824 0%, #073B3A 50%, #0F5E5C 100%)',
              backgroundSize: '22px 22px, auto, auto, auto',
            }}
          >
            <div
              className="mb-4 h-[2px] w-8 rounded-full"
              style={{ background: 'linear-gradient(90deg, #E7C65A 0%, transparent 100%)' }}
            />
            <h1 className="font-serif text-3xl md:text-4xl" style={{ color: '#FFFFFF' }}>
              Welcome back, {firstName}.
            </h1>
            <p className="mt-2 text-[15px]" style={{ color: 'rgba(255,255,255,0.70)' }}>
              Ready to continue where you left off?
            </p>
          </div>

          {/* ── Ecosystem snapshot — bento grid ── */}
          <div className="mb-6 grid gap-4 lg:grid-cols-3">

            {/* Your Journey — featured dark card spanning 2 cols */}
            <Link
              href={continueHref}
              className="group relative overflow-hidden rounded-2xl lg:col-span-2"
              style={{
                background:
                  'radial-gradient(rgba(66,199,198,0.09) 1px, transparent 1px), ' +
                  'radial-gradient(ellipse at 80% 20%, rgba(66,199,198,0.22), transparent 45%), ' +
                  'linear-gradient(135deg, #071824 0%, #073B3A 55%, #0D4E4C 100%)',
                backgroundSize: '22px 22px, auto, auto',
              }}
            >
              <div className="p-7 pb-9">
                <div
                  className="mb-3 h-[2px] w-6 rounded-full"
                  style={{ background: '#E7C65A' }}
                />
                <p
                  className="mb-3 text-[10px] font-bold uppercase tracking-[0.18em]"
                  style={{ color: '#42C7C6' }}
                >
                  {continueData?.all_complete ? 'Journey complete' : 'Your journey'}
                </p>
                <h2
                  className="mb-2 font-serif text-2xl leading-snug transition-opacity group-hover:opacity-90"
                  style={{ color: '#FFFFFF' }}
                >
                  {continueData ? continueData.step_title : 'Begin the REAL Journey'}
                </h2>
                {continueData && (
                  <p className="mb-5 text-[13px]" style={{ color: 'rgba(255,255,255,0.55)' }}>
                    {continueData.pathway_title}
                  </p>
                )}
                <span
                  className="mt-4 inline-flex items-center gap-1.5 rounded-xl px-5 py-2.5 text-[13px] font-semibold transition-opacity group-hover:opacity-80"
                  style={{
                    background: 'rgba(66,199,198,0.18)',
                    border: '1px solid rgba(66,199,198,0.35)',
                    color: '#FFFFFF',
                  }}
                >
                  {continueData?.all_complete ? 'Review' : continueData ? 'Continue' : 'Begin'} →
                </span>
              </div>
            </Link>

            {/* Right column — Coming up + Community stacked */}
            <div className="flex flex-col gap-4">

              {/* Coming up */}
              {nextEvent && nextEventDate ? (
                <Link
                  href={`/spaces/fresh-collective/events/${nextEvent.id}`}
                  className="group flex flex-1 flex-col rounded-2xl border bg-white p-5 shadow-sm transition-all hover:-translate-y-0.5 hover:border-teal-200 hover:shadow-md"
                  style={{ borderColor: 'rgba(56,160,158,0.18)' }}
                >
                  <p className="mb-3 text-[10px] font-bold uppercase tracking-[0.14em] text-teal-600">
                    Coming up
                  </p>
                  <div className="flex flex-1 items-start gap-3">
                    <div
                      className="min-w-[44px] shrink-0 rounded-xl p-2 text-center"
                      style={{ background: 'rgba(56,160,158,0.08)' }}
                    >
                      <div className="font-serif text-xl leading-none text-navy-900">{nextEventDate.day}</div>
                      <div className="mt-0.5 text-[9px] font-bold uppercase tracking-wider" style={{ color: '#9A7A18' }}>{nextEventDate.month}</div>
                    </div>
                    <div className="min-w-0">
                      <p className="text-[13px] font-medium leading-snug text-navy-900 transition-colors group-hover:text-teal-700">
                        {nextEvent.title}
                      </p>
                      <p className="mt-0.5 text-[11px] text-slate-400">{nextEventDate.time} UTC</p>
                    </div>
                  </div>
                  <span className="mt-3 text-[12px] font-semibold text-teal-600 transition-colors group-hover:text-teal-700">
                    View details →
                  </span>
                </Link>
              ) : (
                <div
                  className="flex flex-1 flex-col rounded-2xl border p-5"
                  style={{ borderColor: 'rgba(56,160,158,0.14)', background: 'rgba(56,160,158,0.03)' }}
                >
                  <p className="mb-2 text-[10px] font-bold uppercase tracking-[0.14em] text-teal-500">
                    Coming up
                  </p>
                  <p className="flex-1 font-serif text-[15px] text-slate-400">No upcoming events yet.</p>
                  <p className="mt-2 text-[12px] text-slate-400">Check back soon.</p>
                </div>
              )}

              {/* Community */}
              {recentPost ? (
                <Link
                  href={`/spaces/fresh-collective/community/${recentPost.id}`}
                  className="group flex flex-1 flex-col rounded-2xl border bg-white p-5 shadow-sm transition-all hover:-translate-y-0.5 hover:border-teal-200 hover:shadow-md"
                  style={{ borderColor: 'rgba(56,160,158,0.18)' }}
                >
                  <p className="mb-2 text-[10px] font-bold uppercase tracking-[0.14em] text-teal-600">
                    Community
                  </p>
                  {recentPost.title ? (
                    <p className="mb-1 flex-1 font-serif text-[14px] leading-snug text-navy-900 transition-colors group-hover:text-teal-700">
                      {recentPost.title}
                    </p>
                  ) : (
                    <p className="mb-1 flex-1 line-clamp-2 text-[13px] leading-relaxed text-slate-600">
                      {recentPost.body.split('\n\n')[0]}
                    </p>
                  )}
                  <p className="text-[11px] text-slate-400">{recentPost.author.display_name}</p>
                  <span className="mt-3 text-[12px] font-semibold text-teal-600 transition-colors group-hover:text-teal-700">
                    Join the conversation →
                  </span>
                </Link>
              ) : (
                <Link
                  href="/spaces/fresh-collective/community"
                  className="group flex flex-1 flex-col rounded-2xl border p-5 transition-all hover:-translate-y-0.5 hover:shadow-sm"
                  style={{ borderColor: 'rgba(56,160,158,0.18)', background: 'rgba(234,248,247,0.55)' }}
                >
                  <p className="mb-2 text-[10px] font-bold uppercase tracking-[0.14em] text-teal-600">
                    Community
                  </p>
                  <p className="flex-1 font-serif text-[15px] text-navy-700">
                    The conversation begins with you.
                  </p>
                  <span className="mt-3 text-[12px] font-semibold text-teal-600 transition-colors group-hover:text-teal-700">
                    Open community →
                  </span>
                </Link>
              )}
            </div>
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

          {/* Fallback if no memberships */}
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

          {/* ── Creator Studio — browser-window card ── */}
          {isCreatorOrAdmin && (
            <section className="mb-4">
              <Link
                href="/creator-studio"
                className="group block overflow-hidden rounded-2xl border border-border bg-white shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md"
              >
                {/* Browser chrome dots */}
                <div
                  className="flex items-center gap-1.5 border-b border-border px-4 py-2.5"
                  style={{ background: '#F8FAFA' }}
                >
                  <span className="h-2.5 w-2.5 rounded-full bg-red-400" />
                  <span className="h-2.5 w-2.5 rounded-full bg-yellow-400" />
                  <span className="h-2.5 w-2.5 rounded-full bg-green-400" />
                  <span className="ml-3 text-[11px] text-slate-400">creator-studio</span>
                </div>
                {/* Card content */}
                <div className="px-6 py-5">
                  <div
                    className="mb-4 h-[2px] w-6 rounded-full"
                    style={{ background: 'linear-gradient(90deg, #38A09E, transparent)' }}
                  />
                  <p className="mb-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-teal-600">
                    Creator
                  </p>
                  <p className="font-serif text-xl text-navy-900 transition-colors group-hover:text-teal-700">
                    Creator Studio
                  </p>
                  <p className="mt-1 text-[13px] text-slate-400">
                    Manage your collective, pathways, and gatherings.
                  </p>
                  <span className="mt-4 inline-flex text-[13px] font-semibold text-teal-600 transition-colors group-hover:text-teal-700">
                    Open Studio →
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
