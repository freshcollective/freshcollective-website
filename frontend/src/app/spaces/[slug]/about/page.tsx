import { getSpace, getSpaceMembers, getMe, getSpaceEvents, getMySpaceAccess } from '@/lib/serverApi'
import { resolveMediaUrl } from '@/lib/api'
import { formatCollectiveAccessLabel, formatCollectivePricingSummary } from '@/lib/pricing'
import { notFound } from 'next/navigation'
import Link from 'next/link'
import Avatar from '@/components/ui/Avatar'
import type { MemberProfile, EventSummary, UserProfile, SpaceResponse } from '@/types/platform'
import SpaceAboutCTA from './SpaceAboutCTA'

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

  const memberCount    = members.length
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

  const coverUrl      = resolveMediaUrl(space.cover_image_url)
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
        <p className="text-[15px] font-semibold" style={{ color: 'rgba(255,255,255,0.90)' }}>
          {space.name}
        </p>
        {space.tagline && (
          <p className="mt-1 text-[14px] leading-relaxed" style={{ color: 'rgba(255,255,255,0.65)' }}>
            {space.tagline}
          </p>
        )}
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
            {/* Cover image */}
            {coverUrl && (
              <div className="relative h-52 w-full overflow-hidden">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={coverUrl}
                  alt={space.name}
                  className="h-full w-full object-cover"
                />
              </div>
            )}

            <div className="px-7 py-7">
              <h2 className="mb-5 text-xl font-semibold text-navy-900">{space.name}</h2>

              {/* Quick facts row */}
              <div className="mb-6 flex flex-wrap gap-x-5 gap-y-2.5">
                <span className="flex items-center gap-1.5 text-[13px] text-slate-500">
                  <span>{space.is_public ? '🌐' : '🔒'}</span>
                  <span>{space.is_public ? 'Public' : 'Private'}</span>
                </span>
                {memberCount > 0 && (
                  <span className="flex items-center gap-1.5 text-[13px] text-slate-500">
                    <span>👥</span>
                    <span>{memberCount} {memberCount === 1 ? 'member' : 'members'}</span>
                  </span>
                )}
                {pathwayCount > 0 && (
                  <span className="flex items-center gap-1.5 text-[13px] text-slate-500">
                    <span>🧭</span>
                    <span>{pathwayCount} {pathwayCount === 1 ? 'pathway' : 'pathways'}</span>
                  </span>
                )}
                {gatheringCount > 0 && (
                  <span className="flex items-center gap-1.5 text-[13px] text-slate-500">
                    <span>📅</span>
                    <span>{gatheringCount} upcoming {gatheringCount === 1 ? 'gathering' : 'gatherings'}</span>
                  </span>
                )}
                <span className="flex items-center gap-1.5 text-[13px] text-slate-500">
                  <span>🏷️</span>
                  <span>{formatCollectivePricingSummary({ ...space, min_paid_pathway_price_cents: minPaidPathwayPriceCents })}</span>
                </span>
                {creatorName && (
                  <span className="flex items-center gap-1.5 text-[13px] text-slate-500">
                    <span>✨</span>
                    <span>Led by {creatorName}</span>
                  </span>
                )}
              </div>

              <div className="mb-6 h-px" style={{ background: 'rgba(0,0,0,0.06)' }} />

              {/* Description — preserves line breaks and renders emojis naturally */}
              {space.description ? (
                <div
                  className="text-[15px] leading-[1.85] text-slate-600"
                  style={{ whiteSpace: 'pre-wrap' }}
                >
                  {space.description}
                </div>
              ) : (
                <p className="text-[14px] text-slate-400">
                  This collective doesn&apos;t have an About description yet.
                </p>
              )}
            </div>
          </div>

        </div>

        {/* ── Right: summary card (sticky) ── */}
        <div className="lg:sticky lg:top-6">
          <div
            className="overflow-hidden rounded-2xl bg-white"
            style={{ border: '1px solid rgba(0,0,0,0.07)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
          >
            {/* Cover image or gradient fallback */}
            {coverUrl ? (
              <div className="relative h-32 w-full overflow-hidden">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={coverUrl} alt="" aria-hidden="true" className="h-full w-full object-cover" />
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
              <h3 className="mb-0.5 text-[15px] font-semibold text-navy-900">{space.name}</h3>
              {space.tagline && (
                <p className="mb-4 text-[13px] leading-relaxed text-slate-500">{space.tagline}</p>
              )}

              {/* Stats */}
              {(memberCount > 0 || pathwayCount > 0 || gatheringCount > 0) && (
                <div className="mb-4 flex gap-5">
                  {memberCount > 0 && (
                    <div>
                      <p className="text-[20px] font-semibold text-navy-900">{memberCount}</p>
                      <p className="text-[11px] text-slate-400">{memberCount === 1 ? 'member' : 'members'}</p>
                    </div>
                  )}
                  {pathwayCount > 0 && (
                    <div>
                      <p className="text-[20px] font-semibold text-navy-900">{pathwayCount}</p>
                      <p className="text-[11px] text-slate-400">{pathwayCount === 1 ? 'pathway' : 'pathways'}</p>
                    </div>
                  )}
                  {gatheringCount > 0 && (
                    <div>
                      <p className="text-[20px] font-semibold text-navy-900">{gatheringCount}</p>
                      <p className="text-[11px] text-slate-400">upcoming</p>
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
                    <span className="ml-2 text-[12px] text-slate-400">+{memberCount - 5} more</span>
                  )}
                </div>
              )}

              {/* Pricing */}
              <div className="mb-4 rounded-xl border border-slate-100 bg-slate-50 px-4 py-3">
                <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Access</p>
                <p className="text-[15px] font-semibold text-navy-900">{formatCollectiveAccessLabel(space)}</p>

                {effectiveHasPaidContent ? (
                  <div className="mt-2 space-y-1.5">
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Included</p>
                      <p className="text-[12px] text-slate-500">
                        {space.included_access_summary?.trim() || 'Available community content'}
                      </p>
                    </div>
                    <div>
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Paid separately</p>
                      <p className="text-[12px] text-slate-500">{paidSeparatelyCopy}</p>
                    </div>
                  </div>
                ) : (
                  <>
                    {space.pricing_note ? (
                      <p className="mt-1 text-[12px] text-slate-500">{space.pricing_note}</p>
                    ) : space.pricing_type === 'free' ? (
                      <p className="mt-1 text-[12px] text-slate-400">All available content is included.</p>
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
              />
            </div>
          </div>
        </div>

      </div>
    </div>
  )
}
