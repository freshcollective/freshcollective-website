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

const CARD_BORDER = '1px solid rgba(0,0,0,0.07)'
const CARD_SHADOW = '0 1px 3px rgba(0,0,0,0.04), 0 4px 16px rgba(0,0,0,0.05)'

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
    <div className="flex min-h-screen flex-col" style={{ background: '#FAFAF8' }}>

      {/* ── Top navigation ── */}
      <header className="border-b border-slate-100 bg-white py-3.5" style={{ borderTop: '2px solid #38A09E' }}>
        <Container className="flex items-center justify-between">
          <span className="font-serif text-xl text-navy-900">Fresh Collective</span>
          <div className="flex items-center gap-3">
            <Link
              href="/settings"
              className="text-sm text-slate-500 transition-colors hover:text-navy-700"
            >
              Settings
            </Link>
            <Link
              href="/settings/profile"
              className="flex items-center rounded-lg px-1.5 py-1 transition-colors hover:bg-slate-50"
              aria-label="Your profile"
            >
              <Avatar name={displayName} size="sm" />
            </Link>
            <LogoutButton className="text-sm text-slate-400 transition-colors hover:text-slate-600" />
          </div>
        </Container>
      </header>

      <main className="flex-1 py-10">
        <Container>

          {/* ── Welcome ── */}
          <div className="mb-10 flex items-start justify-between gap-6">
            <div>
              <div
                className="mb-3 h-[2px] w-5"
                style={{ background: 'linear-gradient(90deg, #E7C65A 0%, transparent 100%)' }}
              />
              <h1 className="font-serif text-3xl text-navy-900 md:text-4xl">
                Welcome back, {firstName}.
              </h1>
              <p className="mt-2 text-[14px] text-slate-500">
                Ready to continue where you left off?
              </p>
            </div>
            <div className="hidden shrink-0 flex-col items-end gap-1 sm:flex">
              <Avatar name={displayName} size="md" />
              {isCreatorOrAdmin && (
                <span
                  className="rounded-full px-2 py-0.5 text-[10px] font-medium"
                  style={{ background: 'rgba(56,160,158,0.10)', color: '#2E8584' }}
                >
                  Creator
                </span>
              )}
            </div>
          </div>

          {/* ══════════════════════════════════════════════════
              LAYER 1 — YOUR SPACES
          ══════════════════════════════════════════════════ */}
          <section className="mb-12">
            <h2 className="mb-5 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
              Your spaces
            </h2>

            {/* My collectives */}
            <div className={[
              'mb-4 grid gap-4',
              activeMemberships.length > 1 ? 'sm:grid-cols-2' : '',
            ].join(' ')}>
              {activeMemberships.length > 0 ? (
                activeMemberships.map((m) => {
                  const cs = getCollectiveCoverStyle(m.space_slug)
                  return (
                    <Link
                      key={m.space_id}
                      href={`/spaces/${m.space_slug}`}
                      className="group block overflow-hidden rounded-2xl transition-all hover:-translate-y-0.5 hover:shadow-lg"
                      style={{ border: CARD_BORDER, boxShadow: CARD_SHADOW }}
                    >
                      <div
                        className="relative"
                        style={{
                          paddingBottom: '38%',
                          background: cs.background,
                          backgroundSize: cs.backgroundSize ?? 'auto',
                        }}
                      >
                        <div className="absolute inset-x-0 bottom-0 p-4">
                          <p
                            className="mb-0.5 text-[9px] font-bold uppercase tracking-[0.20em]"
                            style={{ color: cs.labelColor }}
                          >
                            Collective
                          </p>
                          <p
                            className="font-serif text-xl leading-tight transition-opacity group-hover:opacity-90"
                            style={{ color: cs.titleColor }}
                          >
                            {m.space_name}
                          </p>
                        </div>
                        <span
                          className="absolute right-3 top-3 rounded-lg border px-3 py-1.5 text-[12px] font-semibold opacity-0 transition-all group-hover:opacity-100"
                          style={{
                            color: cs.isDark ? '#FFFFFF' : '#073B3A',
                            borderColor: cs.isDark ? 'rgba(255,255,255,0.35)' : 'rgba(56,160,158,0.40)',
                            background: cs.isDark ? 'rgba(0,0,0,0.30)' : 'rgba(56,160,158,0.10)',
                          }}
                        >
                          Open →
                        </span>
                      </div>
                    </Link>
                  )
                })
              ) : (
                /* Fallback — not yet joined, show fresh-collective */
                (() => {
                  const cs = getCollectiveCoverStyle('fresh-collective')
                  return (
                    <Link
                      href="/spaces/fresh-collective"
                      className="group block overflow-hidden rounded-2xl transition-all hover:-translate-y-0.5 hover:shadow-lg"
                      style={{ border: CARD_BORDER, boxShadow: CARD_SHADOW }}
                    >
                      <div
                        className="relative"
                        style={{
                          paddingBottom: '38%',
                          background: cs.background,
                          backgroundSize: cs.backgroundSize ?? 'auto',
                        }}
                      >
                        <div className="absolute inset-x-0 bottom-0 p-4">
                          <p
                            className="mb-0.5 text-[9px] font-bold uppercase tracking-[0.20em]"
                            style={{ color: cs.labelColor }}
                          >
                            Your collective
                          </p>
                          <p
                            className="font-serif text-xl leading-tight transition-opacity group-hover:opacity-90"
                            style={{ color: cs.titleColor }}
                          >
                            Fresh Collective
                          </p>
                        </div>
                        <span
                          className="absolute right-3 top-3 rounded-lg border px-3 py-1.5 text-[12px] font-semibold opacity-0 transition-all group-hover:opacity-100"
                          style={{
                            color: cs.isDark ? '#FFFFFF' : '#073B3A',
                            borderColor: cs.isDark ? 'rgba(255,255,255,0.35)' : 'rgba(56,160,158,0.40)',
                            background: cs.isDark ? 'rgba(0,0,0,0.30)' : 'rgba(56,160,158,0.10)',
                          }}
                        >
                          Open →
                        </span>
                      </div>
                    </Link>
                  )
                })()
              )}
            </div>

            {/* Continue journey + live snippets */}
            <div className="grid gap-4 lg:grid-cols-3">

              {/* Continue — main action card */}
              <Link
                href={continueHref}
                className="group block overflow-hidden rounded-2xl bg-white transition-all hover:-translate-y-0.5 hover:shadow-lg lg:col-span-2"
                style={{ border: CARD_BORDER, boxShadow: CARD_SHADOW }}
              >
                <div className="px-6 py-6">
                  <div
                    className="mb-3 h-[2px] w-5"
                    style={{ background: 'linear-gradient(90deg, #E7C65A 0%, transparent 100%)' }}
                  />
                  <p className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.16em] text-teal-600">
                    {continueData?.all_complete ? 'Journey complete' : 'Continue your journey'}
                  </p>
                  <h3 className="font-serif text-xl leading-snug text-navy-900 md:text-2xl">
                    {continueData ? continueData.step_title : 'Begin the REAL Journey'}
                  </h3>
                  {continueData && (
                    <p className="mt-1 text-[13px] text-slate-400">{continueData.pathway_title}</p>
                  )}
                  <div className="mt-5">
                    <span
                      className="inline-flex items-center gap-1.5 rounded-xl px-5 py-2.5 text-[13px] font-semibold text-white transition-opacity group-hover:opacity-90"
                      style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
                    >
                      {continueData?.all_complete ? 'Review' : continueData ? 'Continue' : 'Begin'} →
                    </span>
                  </div>
                </div>
              </Link>

              {/* Live snippets — stacked */}
              <div className="flex flex-col gap-4">

                {/* Coming up */}
                {nextEvent && nextEventDate ? (
                  <Link
                    href={`/spaces/fresh-collective/events/${nextEvent.id}`}
                    className="group flex flex-1 flex-col rounded-2xl bg-white px-4 py-4 transition-all hover:-translate-y-0.5 hover:shadow-md"
                    style={{ border: CARD_BORDER, boxShadow: CARD_SHADOW }}
                  >
                    <p className="mb-2.5 text-[10px] font-bold uppercase tracking-[0.14em] text-teal-600">
                      Coming up
                    </p>
                    <div className="flex flex-1 items-start gap-3">
                      <div
                        className="min-w-[40px] shrink-0 rounded-xl p-2 text-center"
                        style={{ background: 'rgba(231,198,90,0.10)' }}
                      >
                        <div className="font-serif text-lg leading-none text-navy-900">
                          {nextEventDate.day}
                        </div>
                        <div
                          className="mt-0.5 text-[9px] font-bold uppercase tracking-wider"
                          style={{ color: '#9A7A18' }}
                        >
                          {nextEventDate.month}
                        </div>
                      </div>
                      <div className="min-w-0">
                        <p className="line-clamp-2 text-[13px] font-medium leading-snug text-navy-900 transition-colors group-hover:text-teal-700">
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
                    className="flex flex-1 flex-col rounded-2xl bg-white px-4 py-4"
                    style={{ border: CARD_BORDER }}
                  >
                    <p className="mb-2 text-[10px] font-bold uppercase tracking-[0.14em] text-teal-500">
                      Coming up
                    </p>
                    <p className="flex-1 text-[13px] text-slate-400">
                      No upcoming events yet.
                    </p>
                    <Link
                      href="/spaces/fresh-collective/events"
                      className="mt-3 text-[12px] font-semibold text-teal-600 hover:underline"
                    >
                      View all events →
                    </Link>
                  </div>
                )}

                {/* Community */}
                {recentPost ? (
                  <Link
                    href={`/spaces/fresh-collective/community/${recentPost.id}`}
                    className="group flex flex-1 flex-col rounded-2xl bg-white px-4 py-4 transition-all hover:-translate-y-0.5 hover:shadow-md"
                    style={{ border: CARD_BORDER, boxShadow: CARD_SHADOW }}
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
                    <span className="mt-2 text-[12px] font-semibold text-teal-600 transition-colors group-hover:text-teal-700">
                      Join the conversation →
                    </span>
                  </Link>
                ) : (
                  <Link
                    href="/spaces/fresh-collective/community"
                    className="group flex flex-1 flex-col rounded-2xl bg-white px-4 py-4 transition-all hover:-translate-y-0.5 hover:shadow-sm"
                    style={{ border: CARD_BORDER }}
                  >
                    <p className="mb-2 text-[10px] font-bold uppercase tracking-[0.14em] text-teal-600">
                      Community
                    </p>
                    <p className="flex-1 font-serif text-[14px] text-navy-700">
                      The conversation begins with you.
                    </p>
                    <span className="mt-2 text-[12px] font-semibold text-teal-600 transition-colors group-hover:text-teal-700">
                      Open community →
                    </span>
                  </Link>
                )}

              </div>
            </div>
          </section>

          {/* ══════════════════════════════════════════════════
              LAYER 2 — DISCOVER
          ══════════════════════════════════════════════════ */}
          <section className="mb-12">
            <h2 className="mb-5 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
              Discover
            </h2>
            <Link
              href="/dashboard/explore"
              className="group block max-w-xl overflow-hidden rounded-2xl bg-white transition-all hover:-translate-y-0.5 hover:shadow-lg"
              style={{ border: CARD_BORDER, boxShadow: CARD_SHADOW }}
            >
              <div
                className="h-[3px] w-full"
                style={{
                  background: 'linear-gradient(90deg, #38A09E 0%, #55B8B6 55%, transparent 100%)',
                }}
              />
              <div className="px-6 py-5">
                <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-teal-600">
                  Discover
                </p>
                <h3 className="font-serif text-xl text-navy-900 transition-colors group-hover:text-teal-700">
                  Explore collectives
                </h3>
                <p className="mt-1.5 text-[13px] leading-relaxed text-slate-500">
                  Find other guided spaces and communities to join.
                </p>
                <span
                  className="mt-4 inline-flex items-center gap-1.5 rounded-xl px-4 py-2.5 text-[13px] font-semibold text-white transition-opacity group-hover:opacity-90"
                  style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
                >
                  Browse collectives →
                </span>
              </div>
            </Link>
          </section>

          {/* ══════════════════════════════════════════════════
              LAYER 3 — CREATOR TOOLS (creator/admin only)
          ══════════════════════════════════════════════════ */}
          {isCreatorOrAdmin && (
            <section className="mb-12">
              <h2 className="mb-5 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
                Creator tools
              </h2>
              <Link
                href="/creator-studio"
                className="group block max-w-xl overflow-hidden rounded-2xl bg-white transition-all hover:-translate-y-0.5 hover:shadow-lg"
                style={{ border: CARD_BORDER, boxShadow: CARD_SHADOW }}
              >
                {/* Browser chrome */}
                <div className="flex items-center gap-1.5 border-b border-slate-100 bg-slate-50 px-4 py-2.5">
                  <span className="h-2.5 w-2.5 rounded-full bg-red-400" />
                  <span className="h-2.5 w-2.5 rounded-full bg-yellow-400" />
                  <span className="h-2.5 w-2.5 rounded-full bg-green-400" />
                  <span className="ml-2 text-[11px] text-slate-400">creator-studio</span>
                </div>
                <div className="px-6 py-5">
                  <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-teal-600">
                    Creator
                  </p>
                  <h3 className="font-serif text-xl text-navy-900 transition-colors group-hover:text-teal-700">
                    Creator Studio
                  </h3>
                  <p className="mt-1.5 text-[13px] leading-relaxed text-slate-500">
                    Build and manage your collectives, pathways, gatherings, and people.
                  </p>
                  <span
                    className="mt-4 inline-flex items-center gap-1.5 rounded-xl px-4 py-2.5 text-[13px] font-semibold text-white transition-opacity group-hover:opacity-90"
                    style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
                  >
                    Open Studio →
                  </span>
                </div>
              </Link>
            </section>
          )}

          {/* ── Footer ── */}
          <div className="border-t border-slate-100 pt-6">
            <LogoutButton className="text-xs text-slate-400 transition-colors hover:text-slate-600" />
          </div>

        </Container>
      </main>
    </div>
  )
}
