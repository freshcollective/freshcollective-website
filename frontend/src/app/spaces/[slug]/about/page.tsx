import { getSpace, getSpaceMembers, getMe, getSpaceEvents, getMySpaceAccess } from '@/lib/serverApi'
import { resolveMediaUrl } from '@/lib/api'
import { formatCollectiveAccessLabel, formatCollectivePricingSummary } from '@/lib/pricing'
import { formatGatheringDate } from '@/lib/dateTime'
import { notFound } from 'next/navigation'
import Link from 'next/link'
import Avatar from '@/components/ui/Avatar'
import type { MemberProfile, EventSummary, UserProfile, SpaceResponse } from '@/types/platform'
import SpaceAboutCTA from './SpaceAboutCTA'
import MarkdownBody from '@/components/ui/MarkdownBody'

interface Props {
  params: Promise<{ slug: string }>
}

export default async function SpaceAboutPage({ params }: Props) {
  const { slug } = await params

  const [space, members, me, events] = await Promise.all([
    getSpace(slug) as Promise<SpaceResponse | null>,
    getSpaceMembers(slug) as Promise<MemberProfile[]>,
    getMe() as Promise<UserProfile | null>,
    getSpaceEvents(slug) as Promise<EventSummary[]>,
  ])

  if (!space) notFound()

  // Authoritative aggregate counts come from the space detail endpoint.
  // The /api/spaces/{slug}/members list is privacy-filtered for
  // learner-role viewers (hides learners when show_member_directory=False),
  // so members.filter(...).length would silently render "0 members" in the
  // stats row and sidebar for every ordinary member. Identity-display uses
  // (spaceCreators, avatarMembers) may still be derived from the visible
  // list — those intentionally only show people the viewer is allowed to see.
  const learnerCount   = space.learner_count ?? 0
  const leaderCount    = space.leader_count ?? 0
  const memberCount    = learnerCount + leaderCount
  const pathwayCount   = space.pathways?.length ?? 0
  const gatheringCount = events.length
  const spaceCreators  = members.filter((m) => m.space_role === 'creator')
  const creatorName    = spaceCreators[0]?.display_name ?? null

  const currentUserMember = me ? members.find((m) => m.id === me.id) : null
  const isSpaceMember     = !!currentUserMember
  const currentUserRole   = currentUserMember?.space_role ?? null
  const canManage         = currentUserRole === 'creator' || currentUserRole === 'moderator'

  // Check if logged-in non-member has a pending access request or pending invite
  const myAccess = me && !isSpaceMember ? await getMySpaceAccess(slug) : null

  // Atlas v1.2 — the collective's assigned Location is the primary visual
  // identity. The right-hand sidebar uses the Location thumbnail (falling
  // back to the hero, then the legacy space cover, then a subtle gradient).
  // The main About card no longer repeats a hero banner — the layout-level
  // CollectiveIdentityHeader already establishes visual identity.
  const locationName = space.location?.name ?? null
  const sidebarArtworkUrl = resolveMediaUrl(
    space.location?.thumbnail_artwork_url
      ?? space.location?.hero_artwork_url
      ?? space.cover_image_url,
  )
  const logoUrl = resolveMediaUrl(space.logo_url ?? undefined)
  const avatarMembers = members.slice(0, 5)

  // Effective paid content = manual toggle OR auto-detected from paid pathways
  const effectiveHasPaidContent = space.has_paid_internal_content || space.derived_has_paid_internal_content

  // Derive minimum paid pathway price from pathways already in the response
  const paidPathwayCents = space.pathways
    .filter((p) => (p.access_type === 'one_time' || p.access_type === 'subscription') && p.status === 'active' && p.price_cents != null && p.price_cents > 0)
    .map((p) => p.price_cents as number)
  const minPaidPathwayPriceCents = paidPathwayCents.length > 0 ? Math.min(...paidPathwayCents) : null

  // Paid-separately copy — priority: creator summary > derived price > generic
  const paidSeparatelyCopy = space.paid_content_summary?.trim()
    || (minPaidPathwayPriceCents != null ? `Pathways from $${Math.round(minPaidPathwayPriceCents / 100)} AUD` : 'Paid pathways available separately')

  return (
    <div className="max-w-5xl">

      {/* ── Navy intro card ── */}
      <div
        className="mb-8 overflow-hidden rounded-2xl px-7 py-7"
        style={{
          background: '#071824',
          border: '1px solid rgba(66,199,198,0.10)',
          boxShadow: '0 4px 24px rgba(7,24,36,0.18), 0 1px 4px rgba(0,0,0,0.10)',
        }}
      >
        <div
          className="mb-3 h-[2px] w-8 rounded-full"
          style={{ background: 'linear-gradient(90deg, #55D7D2 0%, transparent 100%)' }}
        />
        <h1 className="mb-2 leading-snug">
          <span
            className="inline-block text-2xl font-semibold"
            style={{
              background: 'linear-gradient(90deg, #55D7D2 0%, #D9FFFD 50%, #FFFFFF 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}
          >
            About
          </span>
        </h1>
        <p className="text-[14px] leading-relaxed" style={{ color: '#FFFFFF' }}>
          Learn more about this collective, who it&apos;s for, and what you&apos;ll find inside.
        </p>
      </div>

      {/* ── Two-column layout ── */}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_272px] lg:items-start">

        {/* ── Left: main content ── */}
        <div className="flex flex-col gap-6">

          {/* Main about card */}
          {/* TODO: Collective About content can be expanded into a richer creator-managed editor later. */}
          <div
            className="overflow-hidden rounded-2xl bg-white"
            style={{ border: '1px solid rgba(0,0,0,0.07)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
          >
            {/* Atlas v1.2 — the old cover_image_url banner is intentionally
                omitted here. Collective visual identity is established by
                the CollectiveIdentityHeader at the layout level. */}
            <div className="px-7 py-7">
              <div className="mb-5 flex items-center gap-3">
                {logoUrl && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={logoUrl}
                    alt=""
                    aria-hidden="true"
                    className="h-9 w-9 shrink-0 rounded-lg object-contain"
                    style={{
                      background: 'rgba(12,24,38,0.04)',
                      border: '1px solid rgba(12,24,38,0.08)',
                      padding: 3,
                    }}
                  />
                )}
                <div>
                  <h2 className="text-xl font-semibold text-navy-900">{space.name}</h2>
                  {space.tagline && (
                    <p className="mt-0.5 text-[13px] italic text-black" style={{ fontFamily: 'Georgia, serif' }}>
                      {space.tagline}
                    </p>
                  )}
                </div>
              </div>

              {/* Quick facts row */}
              <div className="mb-6 flex flex-wrap gap-x-5 gap-y-2.5">
                <span className="flex items-center gap-1.5 text-[13px] text-black">
                  <span>{space.is_public ? '🌐' : '🔒'}</span>
                  <span>{space.is_public ? 'Public' : 'Private'}</span>
                </span>
                {learnerCount > 0 && (
                  <span className="flex items-center gap-1.5 text-[13px] text-black">
                    <span>👥</span>
                    <span>{learnerCount} {learnerCount === 1 ? 'member' : 'members'}</span>
                  </span>
                )}
                {leaderCount > 0 && (
                  <span className="flex items-center gap-1.5 text-[13px] text-black">
                    <span>✦</span>
                    <span>{leaderCount} {leaderCount === 1 ? 'leader' : 'leaders'}</span>
                  </span>
                )}
                {pathwayCount > 0 && (
                  <span className="flex items-center gap-1.5 text-[13px] text-black">
                    <span>🧭</span>
                    <span>{pathwayCount} {pathwayCount === 1 ? 'pathway' : 'pathways'}</span>
                  </span>
                )}
                {gatheringCount > 0 && (
                  <span className="flex items-center gap-1.5 text-[13px] text-black">
                    <span>📅</span>
                    <span>{gatheringCount} upcoming {gatheringCount === 1 ? 'gathering' : 'gatherings'}</span>
                  </span>
                )}
                <span className="flex items-center gap-1.5 text-[13px] text-black">
                  <span>🏷️</span>
                  <span>{formatCollectivePricingSummary({ ...space, min_paid_pathway_price_cents: minPaidPathwayPriceCents })}</span>
                </span>
                {creatorName && (
                  <span className="flex items-center gap-1.5 text-[13px] text-black">
                    <span>✨</span>
                    <span>Led by {creatorName}</span>
                  </span>
                )}
              </div>

              <div className="mb-6 h-px" style={{ background: 'rgba(0,0,0,0.06)' }} />

              {/* About content — prefers about_content, falls back to description */}
              {(space.about_content ?? space.description) ? (
                <MarkdownBody content={(space.about_content ?? space.description)!} />
              ) : (
                <p className="text-[14px] text-black">
                  This collective doesn&apos;t have an About description yet.
                </p>
              )}
            </div>
          </div>

          {/* Upcoming public sessions — shown to non-members when events are publicly visible.
              Suppressed for auto-managed collectives (World Builders) so the About page reads
              as an information card, not an invitation. */}
          {!isSpaceMember && !space.auto_grant_role && events.length > 0 && (
            <div
              className="overflow-hidden rounded-2xl bg-white"
              style={{ border: '1px solid rgba(0,0,0,0.07)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
            >
              <div className="border-b border-border px-6 py-4">
                <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-black">
                  Upcoming sessions
                </p>
              </div>
              <div className="divide-y divide-border">
                {events.slice(0, 3).map((event) => {
                  const { day, month, time } = formatGatheringDate(event.starts_at, space.timezone)
                  return (
                    <div key={event.id} className="flex items-center gap-4 px-6 py-4">
                      <div className="shrink-0 text-center">
                        <div className="text-xl font-bold leading-none text-navy-900">{day}</div>
                        <div
                          className="text-[10px] font-semibold uppercase tracking-wide"
                          style={{ color: 'var(--fc-accent, #0d9488)' }}
                        >{month}</div>
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[14px] font-medium text-navy-900">{event.title}</p>
                        <p className="text-[12px] text-black">{time}</p>
                      </div>
                    </div>
                  )
                })}
              </div>
              <div className="border-t border-border px-6 py-4">
                <p className="text-[13px] text-black">
                  Join to book your spot in these sessions.{' '}
                </p>
              </div>
            </div>
          )}

        </div>

        {/* ── Right: summary card (sticky) ── */}
        <div className="lg:sticky lg:top-6">
          <div
            className="overflow-hidden rounded-2xl bg-white"
            style={{ border: '1px solid rgba(0,0,0,0.07)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
          >
            {/* Atlas v1.2 — sidebar leads with the Location artwork so the
                compact card reads as an identity card for the collective:
                Location thumbnail → hero → legacy cover → subtle gradient. */}
            {sidebarArtworkUrl ? (
              <div className="relative h-32 w-full overflow-hidden">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={sidebarArtworkUrl} alt="" aria-hidden="true" className="h-full w-full object-cover" />
              </div>
            ) : (
              <div
                className="h-16 w-full"
                style={{
                  background: 'linear-gradient(135deg, #071824 0%, #073B3A 55%, #0F5E5C 100%)',
                }}
              />
            )}

            <div className="p-5">
              <div className="mb-3 flex items-center gap-2.5">
                {logoUrl && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={logoUrl}
                    alt=""
                    aria-hidden="true"
                    className="h-7 w-7 shrink-0 rounded-md object-contain"
                    style={{
                      background: 'rgba(12,24,38,0.04)',
                      border: '1px solid rgba(12,24,38,0.08)',
                      padding: 2,
                    }}
                  />
                )}
                <div className="min-w-0">
                  <h3 className="truncate text-[15px] font-semibold text-navy-900">{space.name}</h3>
                  {locationName && (
                    <p
                      className="text-[11px] italic"
                      style={{ color: 'rgba(12,24,38,0.55)', fontFamily: 'Georgia, serif' }}
                    >
                      {locationName}
                    </p>
                  )}
                </div>
              </div>
              {space.tagline && (
                <p className="mb-4 text-[13px] leading-relaxed text-black">{space.tagline}</p>
              )}

              {/* Stats */}
              {(memberCount > 0 || pathwayCount > 0 || gatheringCount > 0) && (
                <div className="mb-4 flex gap-5">
                  {learnerCount > 0 && (
                    <div>
                      <p className="text-[20px] font-semibold text-navy-900">{learnerCount}</p>
                      <p className="text-[11px] text-black">{learnerCount === 1 ? 'member' : 'members'}</p>
                    </div>
                  )}
                  {leaderCount > 0 && (
                    <div>
                      <p className="text-[20px] font-semibold text-navy-900">{leaderCount}</p>
                      <p className="text-[11px] text-black">{leaderCount === 1 ? 'leader' : 'leaders'}</p>
                    </div>
                  )}
                  {pathwayCount > 0 && (
                    <div>
                      <p className="text-[20px] font-semibold text-navy-900">{pathwayCount}</p>
                      <p className="text-[11px] text-black">{pathwayCount === 1 ? 'pathway' : 'pathways'}</p>
                    </div>
                  )}
                  {gatheringCount > 0 && (
                    <div>
                      <p className="text-[20px] font-semibold text-navy-900">{gatheringCount}</p>
                      <p className="text-[11px] text-black">upcoming</p>
                    </div>
                  )}
                </div>
              )}

              {/* Member avatar stack */}
              {avatarMembers.length > 0 && (
                <div className="mb-5 flex items-center">
                  <div className="flex -space-x-2">
                    {avatarMembers.map((m) => (
                      <div key={m.id} className="rounded-full ring-2 ring-white">
                        <Avatar name={m.display_name} avatarUrl={m.avatar_url} size="sm" />
                      </div>
                    ))}
                  </div>
                  {memberCount > 5 && (
                    <span className="ml-2 text-[12px] text-black">+{memberCount - 5} more</span>
                  )}
                </div>
              )}

              {/* Pricing */}
              <div className="mb-4 rounded-xl border border-slate-100 bg-slate-50 px-4 py-3">
                <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-black">Access</p>
                <p className="text-[15px] font-semibold text-navy-900">{formatCollectiveAccessLabel(space)}</p>

                {effectiveHasPaidContent ? (
                  <div className="mt-2 space-y-1.5">
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-black">Included</p>
                      <p className="text-[12px] text-black">
                        {space.included_access_summary?.trim() || 'Available community content'}
                      </p>
                    </div>
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-black">Paid separately</p>
                      <p className="text-[12px] text-black">{paidSeparatelyCopy}</p>
                    </div>
                  </div>
                ) : (
                  <>
                    {space.pricing_note ? (
                      <p className="mt-1 text-[12px] text-black">{space.pricing_note}</p>
                    ) : space.pricing_type === 'free' ? (
                      <p className="mt-1 text-[12px] text-black">All available content is included.</p>
                    ) : null}
                  </>
                )}
              </div>

              <div className="mb-4 h-px" style={{ background: 'rgba(0,0,0,0.06)' }} />

              {/* CTAs */}
              <SpaceAboutCTA
                slug={slug}
                isPublic={space.is_public}
                isMember={isSpaceMember}
                isLoggedIn={!!me}
                hasPendingRequest={myAccess?.has_pending_request ?? false}
                hasPendingInvite={myAccess?.has_pending_invite ?? false}
                canManage={canManage}
                pricingType={space.pricing_type}
                autoGrantRole={space.auto_grant_role ?? null}
              />
            </div>
          </div>
        </div>

      </div>
    </div>
  )
}
