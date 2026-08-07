import Link from 'next/link'
import {
  getMe,
  getCreatorSpaces,
  getCreatorSpace,
  getCreatorPathways,
  getCreatorEvents,
  getCreatorBilling,
  getSpaceMembers,
  getBuildYourCollectiveDraft,
} from '@/lib/serverApi'
import type { DraftData } from '@/lib/build-your-collective/types'
import { resolveMediaUrl } from '@/lib/api'
import type {
  CreatorEvent,
  CreatorPathway,
  CreatorSpaceDetail,
  MemberProfile,
  SpaceSummary,
} from '@/types/platform'

/**
 * My World — the Creator Studio landing.
 *
 * The creator's own management space, distinct from Your World (the
 * Member home at /dashboard). Artwork-first, editorially calm view of
 * the collectives a creator is tending. Every visit answers *which
 * collectives am I tending, and which one am I in right now?* Clicking
 * a card sets that collective active and takes the creator into it.
 */

export default async function CreatorStudioHome() {
  const [profile, spacesRaw, draftResponse] = await Promise.all([
    getMe(),
    getCreatorSpaces(),
    getBuildYourCollectiveDraft(),
  ])
  const spaces: SpaceSummary[] = spacesRaw as SpaceSummary[]

  // A "started" draft has crossed past the Welcome step OR carries a
  // real choice. Fresh drafts (auto-created on page load) with no user
  // input should not surface a "Continue setting up" prompt.
  const draftData: DraftData | null = (draftResponse as { data?: DraftData } | null)?.data ?? null
  const hasStartedDraft =
    !!draftData &&
    (
      (draftData.step ?? 0) > 0 ||
      !!draftData.location_id ||
      (draftData.atmosphere_keys?.length ?? 0) > 0 ||
      !!draftData.colour_palette_key ||
      !!(draftData.identity_statement ?? '').trim() ||
      !!(draftData.welcome_message ?? '').trim() ||
      !!(draftData.name ?? '').trim()
    )

  const firstName = profile?.name?.split(' ')[0] ?? 'there'

  // Determine the currently-active collective from the same cookie the
  // shell reads. The `activeSlug` here mirrors the layout so the card
  // grid can highlight the current collective visually.
  const activeSummary = spaces[0] // simple fallback; layout owns cookie logic

  // Hydrate each collective in parallel. The counts are used as a
  // one-line summary beneath each card ("12 members · 3 pathways · 2
  // gatherings"). Failed fetches degrade to empty arrays / null.
  type CollectiveCard = {
    summary: SpaceSummary
    detail: CreatorSpaceDetail | null
    memberCount: number
    pathwayCount: number
    upcomingCount: number
  }

  const cards: CollectiveCard[] = await Promise.all(
    spaces.map(async (summary) => {
      const [detail, pathways, events, members] = (await Promise.all([
        getCreatorSpace(summary.slug),
        getCreatorPathways(summary.slug),
        getCreatorEvents(summary.slug),
        getSpaceMembers(summary.slug),
      ])) as [CreatorSpaceDetail | null, CreatorPathway[], CreatorEvent[], MemberProfile[]]
      const now = new Date()
      return {
        summary,
        detail,
        memberCount: members.length,
        pathwayCount: pathways.filter((p) => p.status !== 'archived').length,
        upcomingCount: events.filter((e) => new Date(e.starts_at) > now).length,
      }
    }),
  )

  const billing = await getCreatorBilling()
  const isPlatformOwner = billing?.is_platform_owner ?? false
  const collectiveLimit = billing?.current_plan?.collective_limit ?? 1
  const activeSpaceCount = spaces.filter((s) => s.status !== 'archived').length
  const atLimit = !isPlatformOwner && activeSpaceCount >= collectiveLimit

  return (
    <div className="mx-auto max-w-[1200px] px-6 py-10 md:px-10 md:py-14">

      {/* ── Hero ─── */}
      <header className="mb-12">
        <p
          className="mb-3 text-[11px] font-semibold uppercase tracking-[0.28em]"
          style={{ color: '#0f766e' }}
        >
          My World
        </p>
        <h1
          className="font-serif text-[32px] leading-tight md:text-[42px]"
          style={{ color: '#0C1826' }}
        >
          Welcome back, {firstName}.
        </h1>
        <p
          className="mt-3 max-w-[560px] text-[15px] leading-relaxed italic"
          style={{ color: 'rgba(12, 24, 38, 0.65)', fontFamily: 'Georgia, serif' }}
        >
          {spaces.length === 0
            ? 'This is where your first collective will begin.'
            : spaces.length === 1
              ? 'The collective you are tending, ready for whatever comes next.'
              : `The ${spaces.length} collectives you are tending.`}
        </p>
        {spaces.length > 0 && (
          <p className="mt-4 text-[13px] text-slate-500">
            Choose a collective to continue building.
          </p>
        )}
      </header>

      {/* ── Empty state — no collectives yet ─── */}
      {spaces.length === 0 && (
        <div
          className="rounded-3xl px-8 py-16 text-center"
          style={{ background: '#FBFAF6' }}
        >
          {hasStartedDraft ? (
            <>
              <p className="mb-2 font-serif text-[24px] leading-snug text-navy-900">
                Your collective is waiting where you left it.
              </p>
              <p
                className="mx-auto mb-8 max-w-md text-[14.5px] leading-relaxed italic"
                style={{ color: 'rgba(12, 24, 38, 0.62)', fontFamily: 'Georgia, serif' }}
              >
                Pick up where you paused — nothing is lost, nothing is hurried.
              </p>
              <Link
                href="/build-your-collective"
                className="inline-flex items-center rounded-full px-6 py-3 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
                style={{
                  background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                  letterSpacing: '0.04em',
                }}
              >
                Continue setting up your collective →
              </Link>
            </>
          ) : (
            <>
              <p className="mb-2 font-serif text-[24px] leading-snug text-navy-900">
                Your first collective begins with a name.
              </p>
              <p
                className="mx-auto mb-8 max-w-md text-[14.5px] leading-relaxed italic"
                style={{ color: 'rgba(12, 24, 38, 0.62)', fontFamily: 'Georgia, serif' }}
              >
                Choose where in the Fresh Collective world it lives, and start shaping the
                experience the people who find it will walk into.
              </p>
              <Link
                href="/build-your-collective"
                className="inline-flex items-center rounded-full px-6 py-3 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
                style={{
                  background: 'linear-gradient(135deg, #38A09E 0%, #55B8B6 100%)',
                  letterSpacing: '0.04em',
                }}
              >
                Build your first collective →
              </Link>
            </>
          )}
        </div>
      )}

      {/* ── Collectives grid ─── */}
      {spaces.length > 0 && (
        <>
          <div className="grid gap-8 md:grid-cols-2 lg:grid-cols-3">
            {cards.map((card) => (
              <CollectiveCard
                key={card.summary.slug}
                card={card}
                isCurrent={card.summary.slug === activeSummary?.slug}
              />
            ))}
            {!atLimit && <BuildAnotherCard />}
          </div>

          {atLimit && (
            <p
              className="mt-6 text-center text-[12.5px] italic"
              style={{ color: 'rgba(12, 24, 38, 0.55)', fontFamily: 'Georgia, serif' }}
            >
              {activeSpaceCount} of {collectiveLimit} collectives used ·{' '}
              <Link href="/creator-studio/billing" className="text-teal-700 hover:underline">
                View plan
              </Link>
            </p>
          )}
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------

function CollectiveCard({
  card, isCurrent,
}: {
  card: {
    summary: SpaceSummary
    detail: CreatorSpaceDetail | null
    memberCount: number
    pathwayCount: number
    upcomingCount: number
  }
  isCurrent: boolean
}) {
  const { summary, detail, memberCount, pathwayCount, upcomingCount } = card
  const artwork = resolveMediaUrl(
    detail?.location?.thumbnail_artwork_url
      ?? detail?.location?.hero_artwork_url
      ?? detail?.cover_image_url
      ?? undefined,
  )
  const locationName = detail?.location?.name ?? null
  const tagline = detail?.tagline ?? summary.tagline ?? null
  const isDraft = summary.status !== 'active'

  // Clicking a card sets the active-space cookie (so downstream pages
  // treat this as the active collective) and lands on the Identity
  // (settings) page — the entry point that reads well for both fresh
  // and mature collectives.
  const href = `/creator-studio/collective/switch/${summary.slug}`

  const stats: string[] = []
  if (memberCount > 0) stats.push(`${memberCount} ${memberCount === 1 ? 'member' : 'members'}`)
  if (pathwayCount > 0) stats.push(`${pathwayCount} ${pathwayCount === 1 ? 'pathway' : 'pathways'}`)
  if (upcomingCount > 0) stats.push(`${upcomingCount} upcoming ${upcomingCount === 1 ? 'gathering' : 'gatherings'}`)

  return (
    <Link
      href={href}
      className="group block overflow-hidden rounded-2xl bg-white transition-all hover:-translate-y-0.5"
      style={{
        border: isCurrent
          ? '1px solid rgba(56,160,158,0.30)'
          : '1px solid rgba(12, 24, 38, 0.06)',
        boxShadow: isCurrent
          ? '0 6px 20px rgba(56,160,158,0.14), 0 2px 6px rgba(12,24,38,0.04)'
          : '0 6px 20px rgba(12, 24, 38, 0.06)',
      }}
    >
      {/* Location artwork header — the primary visual anchor */}
      <div
        className="relative w-full overflow-hidden"
        style={{ aspectRatio: '3 / 2', background: '#F4F7F6' }}
      >
        {artwork ? (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={artwork}
              alt=""
              aria-hidden="true"
              className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.02]"
            />
            {/* Soft bottom scrim so eyebrow copy remains readable when overlaid */}
            <div
              className="absolute inset-x-0 bottom-0 h-1/2 pointer-events-none"
              style={{ background: 'linear-gradient(180deg, transparent 0%, rgba(7,24,36,0.35) 100%)' }}
              aria-hidden="true"
            />
          </>
        ) : (
          <div
            className="h-full w-full"
            style={{
              background: 'linear-gradient(135deg, rgba(56,160,158,0.20) 0%, rgba(85,184,182,0.10) 100%)',
            }}
          />
        )}
        {/* Location eyebrow when the collective has one */}
        {locationName && artwork && (
          <p
            className="absolute bottom-3 left-4 text-[10.5px] font-semibold uppercase tracking-[0.20em]"
            style={{ color: 'rgba(255,255,255,0.92)' }}
          >
            {locationName}
          </p>
        )}
        {/* Status + current chips */}
        <div className="absolute right-3 top-3 flex items-center gap-1.5">
          {isCurrent && (
            <span
              className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em]"
              style={{
                background: 'rgba(255,255,255,0.94)',
                color: '#0f766e',
                backdropFilter: 'blur(6px)',
              }}
            >
              Current
            </span>
          )}
          {isDraft && (
            <span
              className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em]"
              style={{
                background: 'rgba(255,255,255,0.92)',
                color: 'rgba(12,24,38,0.62)',
                backdropFilter: 'blur(6px)',
              }}
            >
              Draft
            </span>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="px-6 pt-5 pb-6">
        <h3
          className="font-serif text-[20px] leading-tight"
          style={{ color: '#0C1826' }}
        >
          {summary.name}
        </h3>
        {tagline && (
          <p
            className="mt-2 line-clamp-2 text-[13.5px] leading-relaxed italic"
            style={{ color: 'rgba(12, 24, 38, 0.62)', fontFamily: 'Georgia, serif' }}
          >
            {tagline}
          </p>
        )}
        {stats.length > 0 ? (
          <p
            className="mt-4 text-[12px]"
            style={{ color: 'rgba(12, 24, 38, 0.55)' }}
          >
            {stats.join(' · ')}
          </p>
        ) : (
          <p
            className="mt-4 text-[12px] italic"
            style={{ color: 'rgba(12, 24, 38, 0.45)', fontFamily: 'Georgia, serif' }}
          >
            {isDraft ? 'Awaiting its first shape' : 'Ready for its first members'}
          </p>
        )}
      </div>
    </Link>
  )
}

function BuildAnotherCard() {
  return (
    <Link
      href="/build-your-collective"
      className="group flex items-center justify-center rounded-2xl transition-colors"
      style={{
        minHeight: 260,
        border: '1px dashed rgba(12, 24, 38, 0.18)',
        background: 'transparent',
      }}
    >
      <div className="text-center">
        <p
          aria-hidden="true"
          className="mx-auto flex h-10 w-10 items-center justify-center rounded-full text-[18px] text-slate-400 transition-colors group-hover:bg-teal-50 group-hover:text-teal-700"
          style={{ border: '1px solid rgba(12, 24, 38, 0.14)' }}
        >
          +
        </p>
        <p
          className="mt-3 font-serif text-[16px] leading-snug"
          style={{ color: 'rgba(12, 24, 38, 0.65)' }}
        >
          Build another collective
        </p>
      </div>
    </Link>
  )
}
