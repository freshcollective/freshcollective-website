import { cookies } from 'next/headers'
import Link from 'next/link'
import Container from '@/components/layout/Container'
import LogoutButton from '@/components/layout/LogoutButton'
import Avatar from '@/components/ui/Avatar'
import { GoldLabel, PillTag } from '@/components/ui/BrandLabel'
import { SESSION_COOKIE } from '@/lib/session'
import { apiUrl, resolveMediaUrl } from '@/lib/api'
import { getContinue, getSpaceEvents, getMyMemberships, getCommunityFeed, getPublicSpaces } from '@/lib/serverApi'
import { getCollectiveCoverStyle } from '@/lib/coverArt'
import type { ContinueResponse, EventSummary, SpaceMembership, PostSummary, PublicSpaceCard } from '@/types/platform'

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
  const [user, continueData, events, memberships, communityPosts, publicSpaces]: [
    User | null,
    ContinueResponse | null,
    EventSummary[],
    SpaceMembership[],
    PostSummary[],
    PublicSpaceCard[],
  ] = await Promise.all([
    getUser(),
    getContinue(),
    getSpaceEvents('fresh-collective'),
    getMyMemberships(),
    getCommunityFeed('fresh-collective'),
    getPublicSpaces(),
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

  // Build a lookup so we can grab cover images and taglines for member collectives
  const spaceCardBySlug = new Map(publicSpaces.map((s) => [s.slug, s]))

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

      <main className="flex-1 py-8">
        <Container>

          {/* ── Welcome — white card panel, elevated slightly above warm-white page ── */}
          <div
            className="mb-8 overflow-hidden rounded-2xl bg-white px-6 py-5 md:px-8 md:py-6"
            style={{
              boxShadow: '0 1px 4px rgba(0,0,0,0.04), 0 4px 20px rgba(0,0,0,0.06)',
              border: '1px solid rgba(0,0,0,0.06)',
            }}
          >
            <div
              className="mb-2 h-[2px] w-5 rounded-full"
              style={{ background: 'linear-gradient(90deg, #E7C65A 0%, transparent 100%)' }}
            />
            <h1 className="font-serif text-3xl text-navy-900 md:text-4xl">
              Welcome back, {firstName}.
            </h1>
            <p className="mt-1.5 text-[14px] text-slate-500">
              Ready to continue where you left off?
            </p>
          </div>

          {/* ══════════════════════════════════════════════════
              LAYER 1 — YOUR SPACES
          ══════════════════════════════════════════════════ */}
          <section className="mb-8">
            <GoldLabel className="mb-4">Your spaces</GoldLabel>

            {/* ── Collective cards — image-led, card proportion ── */}
            <div className={[
              'mb-4 grid gap-4',
              activeMemberships.length > 1 ? 'sm:grid-cols-2' : '',
            ].join(' ')}>
              {activeMemberships.length > 0 ? (
                activeMemberships.map((m) => {
                  const spaceCard = spaceCardBySlug.get(m.space_slug)
                  const cs = getCollectiveCoverStyle(m.space_slug)
                  const resolvedImageUrl = resolveMediaUrl(spaceCard?.cover_image_url ?? null)
                  const hasImage = Boolean(resolvedImageUrl)

                  return (
                    <Link
                      key={m.space_id}
                      href={`/spaces/${m.space_slug}`}
                      className="group block overflow-hidden rounded-2xl transition-all hover:-translate-y-0.5 hover:shadow-xl"
                      style={{ border: CARD_BORDER, boxShadow: CARD_SHADOW }}
                    >
                      {/* Cover */}
                      <div className="relative overflow-hidden" style={{ height: '168px' }}>
                        {hasImage ? (
                          <>
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img
                              src={resolvedImageUrl!}
                              alt={m.space_name}
                              className="h-full w-full object-cover"
                            />
                            <div
                              className="absolute inset-0"
                              style={{
                                background:
                                  'linear-gradient(to top, rgba(7,24,36,0.78) 0%, rgba(7,24,36,0.20) 50%, transparent 80%)',
                              }}
                            />
                          </>
                        ) : (
                          <div
                            className="absolute inset-0"
                            style={{
                              background: cs.background,
                              backgroundSize: cs.backgroundSize ?? 'auto',
                            }}
                          />
                        )}

                        {/* Name + tagline */}
                        <div className="absolute inset-x-0 bottom-0 p-4">
                          <p
                            className="mb-0.5 text-[9px] font-bold uppercase tracking-[0.20em]"
                            style={{ color: hasImage ? 'rgba(255,255,255,0.60)' : cs.labelColor }}
                          >
                            Collective
                          </p>
                          <p
                            className="font-serif text-xl leading-tight transition-opacity group-hover:opacity-90"
                            style={{ color: hasImage ? '#FFFFFF' : cs.titleColor }}
                          >
                            {m.space_name}
                          </p>
                          {spaceCard?.tagline && (
                            <p
                              className="mt-0.5 line-clamp-1 text-[12px]"
                              style={{ color: hasImage ? 'rgba(255,255,255,0.68)' : cs.labelColor }}
                            >
                              {spaceCard.tagline}
                            </p>
                          )}
                        </div>

                        {/* Hover CTA */}
                        <span
                          className="absolute right-3 top-3 rounded-lg border px-3 py-1.5 text-[12px] font-semibold opacity-0 transition-all group-hover:opacity-100"
                          style={{
                            color: '#FFFFFF',
                            borderColor: 'rgba(255,255,255,0.35)',
                            background: 'rgba(0,0,0,0.32)',
                          }}
                        >
                          Open →
                        </span>
                      </div>

                      {/* Footer — counts + CTA */}
                      <div className="flex items-center justify-between gap-3 bg-white px-4 py-2.5">
                        <div className="flex items-center gap-3 text-[12px] text-slate-400">
                          {spaceCard?.pathway_count ? (
                            <span>{spaceCard.pathway_count} {spaceCard.pathway_count === 1 ? 'pathway' : 'pathways'}</span>
                          ) : null}
                          {spaceCard?.member_count ? (
                            <span>{spaceCard.member_count} {spaceCard.member_count === 1 ? 'member' : 'members'}</span>
                          ) : null}
                        </div>
                        <span className="shrink-0 text-[12px] font-semibold text-teal-600 transition-colors group-hover:text-teal-700">
                          Open collective →
                        </span>
                      </div>
                    </Link>
                  )
                })
              ) : (
                /* Fallback — not yet joined, show fresh-collective */
                (() => {
                  const spaceCard = spaceCardBySlug.get('fresh-collective')
                  const cs = getCollectiveCoverStyle('fresh-collective')
                  const resolvedImageUrl = resolveMediaUrl(spaceCard?.cover_image_url ?? null)
                  const hasImage = Boolean(resolvedImageUrl)

                  return (
                    <Link
                      href="/spaces/fresh-collective"
                      className="group block overflow-hidden rounded-2xl transition-all hover:-translate-y-0.5 hover:shadow-xl"
                      style={{ border: CARD_BORDER, boxShadow: CARD_SHADOW }}
                    >
                      <div className="relative overflow-hidden" style={{ height: '168px' }}>
                        {hasImage ? (
                          <>
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img
                              src={resolvedImageUrl!}
                              alt="Fresh Collective"
                              className="h-full w-full object-cover"
                            />
                            <div
                              className="absolute inset-0"
                              style={{
                                background:
                                  'linear-gradient(to top, rgba(7,24,36,0.78) 0%, rgba(7,24,36,0.20) 50%, transparent 80%)',
                              }}
                            />
                          </>
                        ) : (
                          <div
                            className="absolute inset-0"
                            style={{
                              background: cs.background,
                              backgroundSize: cs.backgroundSize ?? 'auto',
                            }}
                          />
                        )}
                        <div className="absolute inset-x-0 bottom-0 p-4">
                          <p
                            className="mb-0.5 text-[9px] font-bold uppercase tracking-[0.20em]"
                            style={{ color: hasImage ? 'rgba(255,255,255,0.60)' : cs.labelColor }}
                          >
                            Your collective
                          </p>
                          <p
                            className="font-serif text-xl leading-tight"
                            style={{ color: hasImage ? '#FFFFFF' : cs.titleColor }}
                          >
                            Fresh Collective
                          </p>
                          {spaceCard?.tagline && (
                            <p
                              className="mt-0.5 line-clamp-1 text-[12px]"
                              style={{ color: hasImage ? 'rgba(255,255,255,0.68)' : cs.labelColor }}
                            >
                              {spaceCard.tagline}
                            </p>
                          )}
                        </div>
                        <span
                          className="absolute right-3 top-3 rounded-lg border px-3 py-1.5 text-[12px] font-semibold opacity-0 transition-all group-hover:opacity-100"
                          style={{
                            color: '#FFFFFF',
                            borderColor: 'rgba(255,255,255,0.35)',
                            background: 'rgba(0,0,0,0.32)',
                          }}
                        >
                          Open →
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-3 bg-white px-4 py-2.5">
                        <div className="flex items-center gap-3 text-[12px] text-slate-400">
                          {spaceCard?.pathway_count ? (
                            <span>{spaceCard.pathway_count} {spaceCard.pathway_count === 1 ? 'pathway' : 'pathways'}</span>
                          ) : null}
                          {spaceCard?.member_count ? (
                            <span>{spaceCard.member_count} {spaceCard.member_count === 1 ? 'member' : 'members'}</span>
                          ) : null}
                        </div>
                        <span className="shrink-0 text-[12px] font-semibold text-teal-600 transition-colors group-hover:text-teal-700">
                          Open collective →
                        </span>
                      </div>
                    </Link>
                  )
                })()
              )}
            </div>

          </section>

          {/* ── Your Journey — soft structured pillar-card layout ── */}
          <section className="mb-8">
            <GoldLabel className="mb-4">Your journey</GoldLabel>
            <div className="grid gap-4 lg:grid-cols-3">

              {/* Continue Journey — pale aqua pillar card, 2/3 width */}
              <Link
                href={continueHref}
                className="group relative flex flex-col overflow-hidden rounded-2xl transition-all hover:-translate-y-0.5 hover:shadow-md lg:col-span-2"
                style={{
                  background: '#EAF7F6',
                  border: '1px solid rgba(56,160,158,0.16)',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
                }}
              >
                {/* Large faint decorative arrow */}
                <div
                  className="pointer-events-none absolute right-5 top-4 select-none font-serif text-[80px] font-bold leading-none"
                  style={{ color: 'rgba(56,160,158,0.08)' }}
                  aria-hidden="true"
                >
                  →
                </div>
                {/* flex-1 so CTA is pushed to bottom regardless of card height */}
                <div className="relative flex flex-1 flex-col px-6 py-6 md:px-7 md:py-7">
                  <p className="mb-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-teal-600">
                    {continueData?.all_complete
                      ? 'Journey complete'
                      : continueData
                        ? 'Continue your journey'
                        : 'Begin your journey'}
                  </p>
                  <h3 className="font-serif text-2xl leading-snug text-navy-900 transition-colors group-hover:text-teal-700 md:text-3xl">
                    {continueData ? continueData.step_title : 'Begin the REAL Journey'}
                  </h3>
                  {continueData && (
                    <p className="mt-1.5 text-[13px] text-slate-500">
                      {continueData.pathway_title}
                    </p>
                  )}
                  <div className="mt-auto pt-5">
                    <span
                      className="inline-flex items-center gap-1.5 rounded-xl px-4 py-2.5 text-[13px] font-semibold text-white transition-opacity group-hover:opacity-90"
                      style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
                    >
                      {continueData?.all_complete ? 'Review' : continueData ? 'Continue' : 'Begin'} →
                    </span>
                  </div>
                </div>
              </Link>

              {/* Right column — Coming Up + Community, equal-height flex children */}
              <div className="flex flex-col gap-4">

                {/* Coming up — pale cream */}
                {nextEvent && nextEventDate ? (
                  <Link
                    href={`/spaces/fresh-collective/events/${nextEvent.id}`}
                    className="group flex flex-1 flex-col rounded-2xl p-5 transition-all hover:-translate-y-0.5 hover:shadow-md"
                    style={{
                      background: '#FBF6E8',
                      border: '1px solid rgba(231,198,90,0.24)',
                      boxShadow: '0 1px 3px rgba(0,0,0,0.03)',
                    }}
                  >
                    <p className="mb-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                      Coming up
                    </p>
                    <div className="flex flex-1 items-start gap-3">
                      <div
                        className="min-w-[40px] shrink-0 rounded-xl p-2 text-center"
                        style={{ background: 'rgba(231,198,90,0.14)' }}
                      >
                        <div className="font-serif text-base leading-none text-navy-900">
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
                    <span className="mt-auto pt-3 text-[12px] font-semibold text-teal-600 transition-colors group-hover:text-teal-700">
                      View details →
                    </span>
                  </Link>
                ) : (
                  <div
                    className="flex flex-1 flex-col rounded-2xl p-5"
                    style={{
                      background: '#FBF6E8',
                      border: '1px solid rgba(231,198,90,0.22)',
                    }}
                  >
                    <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                      Coming up
                    </p>
                    <p className="flex-1 text-[13px] leading-relaxed text-slate-400">
                      No upcoming events yet.
                    </p>
                    <Link
                      href="/spaces/fresh-collective/events"
                      className="mt-auto pt-3 text-[12px] font-semibold text-teal-600 hover:underline"
                    >
                      View all events →
                    </Link>
                  </div>
                )}

                {/* Community — pale blue-grey */}
                {recentPost ? (
                  <Link
                    href={`/spaces/fresh-collective/community/${recentPost.id}`}
                    className="group flex flex-1 flex-col rounded-2xl p-5 transition-all hover:-translate-y-0.5 hover:shadow-md"
                    style={{
                      background: '#EEF2F5',
                      border: '1px solid rgba(148,163,184,0.24)',
                      boxShadow: '0 1px 3px rgba(0,0,0,0.03)',
                    }}
                  >
                    <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-teal-600">
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
                    <p className="mt-1 text-[11px] text-slate-400">{recentPost.author.display_name}</p>
                    <span className="mt-auto pt-2 text-[12px] font-semibold text-teal-600 transition-colors group-hover:text-teal-700">
                      Join the conversation →
                    </span>
                  </Link>
                ) : (
                  <Link
                    href="/spaces/fresh-collective/community"
                    className="group flex flex-1 flex-col rounded-2xl p-5 transition-all hover:-translate-y-0.5 hover:shadow-md"
                    style={{
                      background: '#EEF2F5',
                      border: '1px solid rgba(148,163,184,0.24)',
                      boxShadow: '0 1px 3px rgba(0,0,0,0.03)',
                    }}
                  >
                    <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-teal-600">
                      Community
                    </p>
                    <p className="flex-1 font-serif text-[14px] text-navy-900">
                      The conversation begins with you.
                    </p>
                    <span className="mt-auto pt-2 text-[12px] font-semibold text-teal-600 transition-colors group-hover:text-teal-700">
                      Open community →
                    </span>
                  </Link>
                )}

              </div>
            </div>
          </section>

          {/* ── Discover ── */}
          <section className="mb-8 max-w-2xl">
            <GoldLabel className="mb-4">Discover</GoldLabel>
            <Link
              href="/dashboard/explore"
              className="group relative block overflow-hidden rounded-2xl transition-all hover:-translate-y-0.5 hover:shadow-md"
              style={{
                background: '#EAF7F6',
                border: '1px solid rgba(56,160,158,0.18)',
                boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
              }}
            >
              <div
                className="pointer-events-none absolute right-4 top-2 select-none font-serif text-[96px] font-bold leading-none"
                style={{ color: 'rgba(56,160,158,0.09)' }}
                aria-hidden="true"
              >
                →
              </div>
              <div className="relative px-6 py-6">
                <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-teal-600">
                  Discover
                </p>
                <h3 className="font-serif text-xl text-navy-900 transition-colors group-hover:text-teal-700">
                  Explore collectives
                </h3>
                <p className="mt-2 text-[13px] leading-relaxed text-slate-500">
                  Find other guided spaces and communities to join.
                </p>
                <span
                  className="mt-5 inline-flex items-center gap-1.5 rounded-xl px-4 py-2.5 text-[13px] font-semibold text-white transition-opacity group-hover:opacity-90"
                  style={{ background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)' }}
                >
                  Browse collectives →
                </span>
              </div>
            </Link>
          </section>

          {/* ── Creator tools — clean card, no chrome ── */}
          {isCreatorOrAdmin && (
            <section className="mb-8 max-w-2xl">
              <GoldLabel className="mb-4">Creator tools</GoldLabel>
              <Link
                href="/creator-studio"
                className="group block overflow-hidden rounded-2xl bg-white transition-all hover:-translate-y-0.5 hover:shadow-md"
                style={{ border: CARD_BORDER, boxShadow: CARD_SHADOW }}
              >
                <div className="px-6 py-6">
                  <div className="mb-3">
                    <PillTag>Creator</PillTag>
                  </div>
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
