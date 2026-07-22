import type { Metadata } from 'next'
import { cookies } from 'next/headers'
import Link from 'next/link'
import Container from '@/components/layout/Container'
import LogoutButton from '@/components/layout/LogoutButton'
import Avatar from '@/components/ui/Avatar'
import { SESSION_COOKIE } from '@/lib/session'
import { apiUrl, resolveMediaUrl } from '@/lib/api'
import {
  getCreatorSpace,
  getCreatorSpaces,
  getMyMemberships,
  getPublicSpaces,
  getPublicPlatformArtwork,
  getSpace,
  getSpaceEvents,
} from '@/lib/serverApi'
import { getCollectiveCoverStyle } from '@/lib/coverArt'
import type { CreatorSpaceDetail, SpaceMembership, SpaceSummary, PublicSpaceCard, SpaceResponse, EventSummary } from '@/types/platform'
import { ATLAS_CARD_STYLE, AtlasArtwork, AtlasCardBody } from './AtlasCard'
import CreatorCollectiveCard from './CreatorCollectiveCard'

export const metadata: Metadata = {
  title: 'Your World · Fresh Collective',
  description:
    'The Collectives you belong to, the places you’re creating, and what’s happening next.',
}

/**
 * Your World — the member's personal overview page (route: /dashboard).
 *
 * Two-column layout on desktop; single column on tablet/mobile with This
 * Week promoted to the second slot so the "what's next" answer stays high
 * on the page even without a sidebar.
 *
 * Desktop main column order:
 *   1. Collectives you belong to
 *   2. Explore Collectives
 *   3. Collectives you created  (only if any)
 *   4. Create & Manage          (only if creator/admin)
 *
 * Right sidebar (desktop only):
 *   5. This Week — compact rows, cap at 4, "View all Gatherings" link
 */

interface User {
  id: string
  email: string
  name: string | null
  role: string
}

interface MembershipCard {
  membership: SpaceMembership
  space: SpaceResponse | null
  events: EventSummary[]
}

// A collective the current user owns. `detail` may be null if the creator
// endpoint fails; fall back to `summary` for name/tagline/status.
interface CreatorCollective {
  summary: SpaceSummary
  detail: CreatorSpaceDetail | null
}

interface UpcomingEvent {
  event: EventSummary
  spaceSlug: string
  spaceName: string
  locationArt: string | null
  fallbackBg: string
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

/**
 * Filter memberships' events down to the dashboard's "This Week" summary:
 *   - `thisWeek`:  up to 4 active events starting within the next 7 days
 *   - `hasMore`:   any upcoming event exists beyond what's shown (either
 *                  outside the 7-day window, or past the 4-item cap)
 *
 * The dashboard is meant to answer "what should I do next?" — the full
 * schedule lives on the aggregate gatherings page.
 */
function filterUpcoming(cards: MembershipCard[]): { thisWeek: UpcomingEvent[]; hasMore: boolean } {
  const now = Date.now()
  const weekEnd = now + 7 * 24 * 60 * 60 * 1000
  const all = cards
    .flatMap((c) => {
      const loc = c.space?.location
      const locArt = resolveMediaUrl(
        loc?.thumbnail_artwork_url ?? loc?.hero_artwork_url ?? undefined,
      )
      const cover = resolveMediaUrl(c.space?.cover_image_url ?? undefined)
      return (c.events ?? []).map((e) => ({
        event: e,
        spaceSlug: c.membership.space_slug,
        spaceName: c.membership.space_name,
        locationArt: locArt ?? cover ?? null,
        fallbackBg: getCollectiveCoverStyle(c.membership.space_slug).background,
      }))
    })
    .filter((u) => u.event.status === 'active' && new Date(u.event.starts_at).getTime() > now)
    .sort((a, b) => new Date(a.event.starts_at).getTime() - new Date(b.event.starts_at).getTime())

  const inWindow = all.filter((u) => new Date(u.event.starts_at).getTime() <= weekEnd)
  const thisWeek = inWindow.slice(0, 4)
  const hasMore = all.length > thisWeek.length
  return { thisWeek, hasMore }
}

async function _safe<T>(p: Promise<T>, label: string, fallback: T): Promise<T> {
  try { return await p }
  catch (err) { console.error(`[dashboard] ${label} failed:`, err); return fallback }
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default async function DashboardPage() {
  const [user, memberships, publicSpaces, platformArtwork, creatorSpaces]: [
    User | null,
    SpaceMembership[],
    PublicSpaceCard[],
    Awaited<ReturnType<typeof getPublicPlatformArtwork>>,
    SpaceSummary[],
  ] = await Promise.all([
    _safe(getUser(), 'getUser', null),
    _safe(getMyMemberships(), 'getMyMemberships', []),
    _safe(getPublicSpaces(), 'getPublicSpaces', []),
    _safe(getPublicPlatformArtwork(), 'getPublicPlatformArtwork', []),
    _safe(getCreatorSpaces() as Promise<SpaceSummary[]>, 'getCreatorSpaces', []),
  ])
  const artworkByKey = new Map(platformArtwork.map((a) => [a.key, a]))
  const exploreArt = artworkByKey.get('explore_collectives') ?? null
  const creatorStudioArt = artworkByKey.get('creator_studio') ?? null

  const firstName = user?.name?.split(' ')[0] ?? 'friend'
  const displayName = user?.name ?? firstName
  const isCreatorOrAdmin = user?.role === 'creator' || user?.role === 'admin'
  const activeMemberships = memberships.filter((m) => m.status === 'active')

  // "Collectives you belong to" — active memberships against a *published*
  // collective. Draft collectives never appear here even when the current
  // user is also the creator.
  const cards: MembershipCard[] = (await Promise.all(
    activeMemberships.map(async (m) => {
      const [space, events] = await Promise.all([
        _safe(getSpace(m.space_slug), `getSpace(${m.space_slug})`, null),
        _safe(getSpaceEvents(m.space_slug), `getSpaceEvents(${m.space_slug})`, [] as EventSummary[]),
      ])
      return { membership: m, space, events }
    }),
  )).filter((c) => c.space?.status === 'active')

  // "Collectives you created" — every space the current user owns, whether
  // published or draft. Full detail hydrated so cards can render artwork,
  // tagline, and Location identity the same way membership cards do.
  const creatorCards: CreatorCollective[] = await Promise.all(
    creatorSpaces.map(async (s) => {
      const detail = await _safe(
        getCreatorSpace(s.slug) as Promise<CreatorSpaceDetail | null>,
        `getCreatorSpace(${s.slug})`,
        null,
      )
      return { summary: s, detail }
    }),
  )

  const publicBySlug = new Map(publicSpaces.map((s) => [s.slug, s]))
  const { thisWeek, hasMore } = filterUpcoming(cards)

  return (
    <div className="min-h-screen" style={{ background: '#FAFAF8' }}>
      {/* Top navigation — kept as-is */}
      <header className="border-b border-slate-100 bg-white py-3.5" style={{ borderTop: '2px solid #38A09E' }}>
        <Container className="flex items-center justify-between">
          <span className="font-serif text-xl text-navy-900">Fresh Collective</span>
          <div className="flex items-center gap-3">
            <Link href="/settings" className="text-sm text-black transition-colors hover:text-navy-700">
              Settings
            </Link>
            <Link
              href="/settings/profile"
              className="flex items-center rounded-lg px-1.5 py-1 transition-colors hover:bg-slate-50"
              aria-label="Your profile"
            >
              <Avatar name={displayName} size="sm" />
            </Link>
            <LogoutButton className="text-sm text-black transition-colors hover:text-slate-600" />
          </div>
        </Container>
      </header>

      {/* Welcome banner — full-bleed dark section. */}
      <WelcomeBanner firstName={firstName} />

      <main className="mx-auto max-w-[1200px] px-6 pt-12 pb-16 md:px-10 md:pt-14 md:pb-20">

        {/* Page title lives above the two-column grid so it spans the full
            width on both desktop and mobile. */}
        <div className="mb-10">
          <p
            className="mb-2 text-[11px] font-semibold uppercase tracking-[0.28em]"
            style={{ color: '#38A09E' }}
          >
            Overview
          </p>
          <h2
            className="font-serif text-[26px] leading-tight md:text-[30px]"
            style={{ color: '#0C1826' }}
          >
            Your World
          </h2>
          <p
            className="mt-2 max-w-[640px] text-[14px] italic leading-relaxed"
            style={{ color: 'rgba(12, 24, 38, 0.62)', fontFamily: 'Georgia, serif' }}
          >
            The Collectives you belong to, the places you&rsquo;re creating,
            and what&rsquo;s happening next.
          </p>
        </div>

        {/* Two-column grid on lg+. Explicit lg:col-start / lg:row-start on
            every child guarantees main-column items land in column 1 and
            the aside stays in column 2. `order-N` only governs mobile,
            where the single column falls back to auto-placement. */}
        <div className="grid grid-cols-1 gap-x-12 gap-y-12 lg:grid-cols-[minmax(0,1fr)_320px]">

          {/* ─────── Main column (lg:col-start-1) ─────── */}

          {/* 1. Collectives you belong to */}
          <Section
            className="order-1 lg:col-start-1 lg:row-start-1"
            eyebrow="Where you belong"
            title="Collectives you belong to"
            subtitle="Communities you're currently part of."
            count={cards.length}
            noSpacing
          >
            {cards.length > 0 ? (
              <div className="grid gap-8 sm:grid-cols-2">
                {cards.map((c) => (
                  <CollectiveCard
                    key={c.membership.space_id}
                    card={c}
                    publicCard={publicBySlug.get(c.membership.space_slug) ?? null}
                  />
                ))}
              </div>
            ) : (
              <div
                className="rounded-2xl bg-white px-6 py-8 text-center"
                style={ATLAS_CARD_STYLE}
              >
                <p
                  className="text-[14px] italic"
                  style={{ color: 'rgba(12, 24, 38, 0.62)', fontFamily: 'Georgia, serif' }}
                >
                  You&apos;re not part of any collectives yet.
                </p>
              </div>
            )}
          </Section>

          {/* 2. Explore Collectives — sits directly under "belong to" in the
              main column. Rendered inside the same sm:grid-cols-2 grid so
              the card is exactly one Collective-card wide, left-aligned. */}
          <Section
            className="order-3 lg:col-start-1 lg:row-start-2"
            eyebrow="Discover"
            title="Explore Collectives"
            subtitle="Discover places that feel like home."
            noSpacing
          >
            <div className="grid gap-8 sm:grid-cols-2">
              <ExploreCollectivesCard
                artUrl={exploreArt?.thumbnail_url ?? exploreArt?.image_url ?? null}
              />
            </div>
          </Section>

          {/* 3. Collectives you created — every space the user owns, published
              or draft. Hidden when there are none. Row 3 in the main column. */}
          {creatorCards.length > 0 && (
            <Section
              className="order-4 lg:col-start-1 lg:row-start-3"
              eyebrow="What you've created"
              title="Collectives you created"
              subtitle="Communities you're building and managing."
              count={creatorCards.length}
              noSpacing
            >
              <div className="grid gap-8 sm:grid-cols-2">
                {creatorCards.map((c) => (
                  <CreatorCollectiveCard
                    key={c.summary.id}
                    summary={c.summary}
                    detail={c.detail}
                  />
                ))}
              </div>
            </Section>
          )}

          {/* 4. Create & Manage — creators/admins only. Row 4 in the main
              column. Creator Studio card sits in the same 2-col grid as
              creator Collective cards above so it reads as the next card. */}
          {isCreatorOrAdmin && (
            <Section
              className="order-5 lg:col-start-1 lg:row-start-4"
              eyebrow="For creators"
              title="Create & Manage"
              noSpacing
            >
              <div className="grid gap-8 sm:grid-cols-2">
                <CreatorStudioCard
                  artUrl={creatorStudioArt?.thumbnail_url ?? creatorStudioArt?.image_url ?? null}
                />
              </div>
            </Section>
          )}

          {/* ─────── Right sidebar (lg:col-start-2, spans all main rows) ─────── */}

          {/* This Week — compact rows for a narrow column. On desktop the
              aside spans all 4 possible main-column rows so col 2 stays
              reserved even when the aside itself is short; `self-start`
              plus `sticky top-24` keeps the block pinned near the top as
              the main column scrolls. On mobile it slots in as order-2. */}
          <aside className="order-2 lg:col-start-2 lg:row-start-1 lg:row-span-4 lg:sticky lg:top-24 lg:self-start">
            <Section
              eyebrow="Happening soon"
              title="This Week"
              subtitle={undefined}
              noSpacing
              compact
            >
              {thisWeek.length > 0 ? (
                <div className="flex flex-col gap-3">
                  {thisWeek.map((g) => (
                    <SidebarGatheringRow key={g.event.id} g={g} />
                  ))}
                </div>
              ) : (
                <div
                  className="rounded-2xl bg-white px-5 py-6 text-center"
                  style={ATLAS_CARD_STYLE}
                >
                  <p
                    className="text-[13px] italic leading-relaxed"
                    style={{ color: 'rgba(12, 24, 38, 0.62)', fontFamily: 'Georgia, serif' }}
                  >
                    Nothing is scheduled this week.
                  </p>
                </div>
              )}

              {/* Always render "View all Gatherings" so members can reach
                  the full schedule even when this week is empty. */}
              <div className="mt-5">
                <Link
                  href="/gatherings"
                  className="inline-flex items-center text-[13px] font-semibold transition-opacity hover:opacity-70"
                  style={{ color: '#38A09E' }}
                >
                  View all Gatherings →
                </Link>
                {hasMore && (
                  <p
                    className="mt-1 text-[11px]"
                    style={{ color: 'rgba(12, 24, 38, 0.50)' }}
                  >
                    More upcoming beyond this week.
                  </p>
                )}
              </div>
            </Section>
          </aside>

        </div>
      </main>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section header — matches the Admin Atlas section pattern
// ---------------------------------------------------------------------------

function Section({
  eyebrow, title, subtitle, count, children, noSpacing, compact, className,
}: {
  eyebrow: string
  title: string
  subtitle?: string
  count?: number
  children: React.ReactNode
  /** When true, omit the top margin — used when the Section is placed
   *  inside a composed layout wrapper that already provides spacing. */
  noSpacing?: boolean
  /** Sidebar variant: smaller title, tighter margins, no count chip on the
   *  right (the narrow column can't spare the horizontal space). */
  compact?: boolean
  /** Extra classes for grid ordering. */
  className?: string
}) {
  const spacingClass = noSpacing ? '' : 'mt-14 first:mt-10'
  return (
    <section className={[spacingClass, className].filter(Boolean).join(' ')}>
      <div
        className={
          compact
            ? 'mb-4 flex flex-wrap items-baseline justify-between gap-2'
            : 'mb-6 flex flex-wrap items-baseline justify-between gap-4'
        }
      >
        <div>
          <p
            className="mb-2 text-[11px] font-semibold uppercase tracking-[0.28em]"
            style={{ color: '#38A09E' }}
          >
            {eyebrow}
          </p>
          <h2
            className={
              compact
                ? 'font-serif text-[18px] leading-tight'
                : 'font-serif text-[22px] leading-tight md:text-[26px]'
            }
            style={{ color: '#0C1826' }}
          >
            {title}
          </h2>
          {subtitle && (
            <p
              className="mt-1.5 max-w-[560px] text-[13.5px] italic leading-relaxed"
              style={{ color: 'rgba(12, 24, 38, 0.60)', fontFamily: 'Georgia, serif' }}
            >
              {subtitle}
            </p>
          )}
        </div>
        {!compact && count !== undefined && count > 0 && (
          <p className="text-[12px]" style={{ color: 'rgba(12, 24, 38, 0.50)' }}>
            {count === 1 ? '1 in your world' : `${count} in your world`}
          </p>
        )}
      </div>
      {children}
    </section>
  )
}

// ---------------------------------------------------------------------------
// 1. Welcome hero — visually identical to the collective identity band on
//    /spaces/[slug]. Same background treatment, same box shadow into the
//    page below, same accent line + serif h1 + teal→white gradient text.
//    Inner container uses max-w-[1200px] so text stays aligned with the
//    dashboard sections that live under <main>.
// ---------------------------------------------------------------------------

function WelcomeBanner({ firstName }: { firstName: string }) {
  return (
    <div
      className="relative overflow-hidden px-6 py-10 md:px-10 md:py-14"
      style={{
        // Same layered treatment as /spaces/[slug]:
        //   1. fine dot overlay for texture (background-size 22px)
        //   2. large teal glow at top-right
        //   3. secondary teal glow at bottom-left
        //   4. navy diagonal linear-gradient base
        background:
          'radial-gradient(rgba(66,199,198,0.07) 1px, transparent 1px), '
          + 'radial-gradient(ellipse at 78% 20%, rgba(66,199,198,0.38), transparent 48%), '
          + 'radial-gradient(ellipse at 10% 80%, rgba(56,160,158,0.22), transparent 42%), '
          + 'linear-gradient(135deg, #071824 0%, #092030 40%, #073B3A 100%)',
        backgroundSize: '22px 22px, auto, auto, auto',
        boxShadow: '0 8px 40px rgba(7,24,36,0.28)',
      }}
    >
      <div className="relative mx-auto max-w-[1200px]">
        <div
          className="mb-4 h-[2px] w-8 rounded-full"
          style={{ background: 'linear-gradient(90deg, #E7C65A 0%, transparent 100%)' }}
          aria-hidden="true"
        />
        <h1 className="font-serif text-3xl md:text-4xl" style={{ color: '#FFFFFF' }}>
          <span
            style={{
              background: 'linear-gradient(120deg, #55D7D2 0%, #FFFFFF 55%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}
          >
            Welcome back
          </span>
          , {firstName}.
        </h1>
        <p
          className="mt-2 text-[14px] italic leading-relaxed"
          style={{ color: 'rgba(255, 255, 255, 0.85)', fontFamily: 'Georgia, serif' }}
        >
          Your communities are ready whenever you are.
        </p>
      </div>
    </div>
  )
}

// (AtlasArtwork + AtlasCardBody now live in ./AtlasCard so the same
// primitives back membership cards, creator cards, and platform tiles.)

// ---------------------------------------------------------------------------
// My Collectives card
// ---------------------------------------------------------------------------

function CollectiveCard({
  card, publicCard,
}: {
  card: MembershipCard
  publicCard: PublicSpaceCard | null
}) {
  const name = card.membership.space_name
  const description =
    card.space?.tagline?.trim()
    ?? card.space?.description?.trim()
    ?? publicCard?.tagline
    ?? publicCard?.description
    ?? null

  const pathwayCount = publicCard?.pathway_count ?? 0
  const memberCount = publicCard?.member_count ?? 0

  const meta = [
    pathwayCount > 0 ? `${pathwayCount} ${pathwayCount === 1 ? 'pathway' : 'pathways'}` : null,
    memberCount > 0 ? `${memberCount} ${memberCount === 1 ? 'member' : 'members'}` : null,
  ].filter(Boolean).join(' · ') || null

  const loc = card.space?.location
  const locationArt = resolveMediaUrl(
    loc?.thumbnail_artwork_url ?? loc?.hero_artwork_url ?? undefined,
  )
  const cover = resolveMediaUrl(card.space?.cover_image_url ?? publicCard?.cover_image_url ?? null)
  const artUrl = locationArt ?? cover
  const cs = getCollectiveCoverStyle(card.membership.space_slug)

  return (
    <Link
      href={`/spaces/${card.membership.space_slug}/community`}
      className="group block overflow-hidden rounded-2xl bg-white transition-all"
      style={ATLAS_CARD_STYLE}
    >
      <AtlasArtwork url={artUrl} fallbackBg={cs.background} alt={name} />
      <AtlasCardBody name={name} description={description} meta={meta} cta="Continue →" />
    </Link>
  )
}

// ---------------------------------------------------------------------------
// Explore Collectives — final Atlas card in the My Collectives grid
// ---------------------------------------------------------------------------

function ExploreCollectivesCard({ artUrl }: { artUrl?: string | null }) {
  const resolved = resolveMediaUrl(artUrl ?? undefined)
  return (
    <Link
      href="/spaces"
      className="group block overflow-hidden rounded-2xl bg-white transition-all"
      style={ATLAS_CARD_STYLE}
    >
      <div
        className="relative w-full overflow-hidden"
        style={{
          aspectRatio: '3 / 2',
          background:
            'linear-gradient(135deg, rgba(56, 160, 158, 0.12) 0%, rgba(247, 232, 200, 0.10) 55%, rgba(212, 176, 72, 0.16) 100%)',
        }}
      >
        {resolved ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={resolved}
            alt="Explore Collectives"
            className="absolute inset-0 h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.02]"
          />
        ) : (
          <svg
            viewBox="0 0 240 160"
            className="absolute left-1/2 top-1/2 h-32 w-40 -translate-x-1/2 -translate-y-1/2 transition-transform duration-500 group-hover:scale-[1.05]"
            aria-hidden="true"
          >
            <circle cx="120" cy="60" r="14" fill="#D4B048" opacity="0.60" />
            <path d="M 20 100 Q 120 92 220 100" stroke="#38A09E" strokeWidth="1.5" fill="none" opacity="0.55" />
            <path d="M 55 100 Q 70 88 90 100 Z" fill="#0C1826" opacity="0.55" />
            <path d="M 150 100 Q 170 82 195 100 Z" fill="#0C1826" opacity="0.45" />
            <path d="M 40 118 Q 120 114 200 118" stroke="#38A09E" strokeWidth="0.8" fill="none" opacity="0.35" />
            <path d="M 60 130 Q 120 126 180 130" stroke="#38A09E" strokeWidth="0.6" fill="none" opacity="0.25" />
          </svg>
        )}
      </div>
      <AtlasCardBody
        name="Explore Collectives"
        description="Discover other places you might feel at home in."
        meta="Elsewhere in the world"
        cta="Explore →"
      />
    </Link>
  )
}

// ---------------------------------------------------------------------------
// Creator Studio card
// ---------------------------------------------------------------------------

function CreatorStudioCard({ artUrl }: { artUrl?: string | null }) {
  const resolved = resolveMediaUrl(artUrl ?? undefined)
  return (
    <Link
      href="/creator-studio"
      className="group block overflow-hidden rounded-2xl bg-white transition-all"
      style={ATLAS_CARD_STYLE}
    >
      <div
        className="relative w-full overflow-hidden"
        style={{
          aspectRatio: '3 / 2',
          background:
            'linear-gradient(135deg, rgba(56, 160, 158, 0.14) 0%, rgba(85, 184, 182, 0.06) 55%, rgba(212, 176, 72, 0.14) 100%)',
        }}
      >
        {resolved ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={resolved}
            alt="Creator Studio"
            className="absolute inset-0 h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.02]"
          />
        ) : (
          <svg
            viewBox="0 0 200 200"
            className="absolute left-1/2 top-1/2 h-24 w-24 -translate-x-1/2 -translate-y-1/2 transition-transform duration-500 group-hover:scale-[1.05]"
            aria-hidden="true"
          >
            <circle cx="100" cy="100" r="80" fill="none" stroke="#38A09E" strokeWidth="1.5" opacity="0.55" />
            <circle cx="100" cy="100" r="60" fill="none" stroke="#38A09E" strokeWidth="0.8" opacity="0.35" />
            <path d="M 100 30 L 108 100 L 100 170 L 92 100 Z" fill="#0C1826" opacity="0.75" />
            <path d="M 30 100 L 100 92 L 170 100 L 100 108 Z" fill="#0C1826" opacity="0.55" />
            <circle cx="100" cy="100" r="4" fill="#D4B048" />
          </svg>
        )}
      </div>
      <AtlasCardBody
        name="Creator Studio"
        description="Create new collectives, build pathways, host gatherings and grow your community."
        meta="For creators"
        cta="Enter Studio →"
      />
    </Link>
  )
}

// ---------------------------------------------------------------------------
// Sidebar Gathering row — narrow-column variant. Compact date block, single
// meta line, and one state/action label that reflects the member's real
// booking/permission state. Reuses the existing EventSummary fields — no
// new booking logic.
// ---------------------------------------------------------------------------

function SidebarGatheringRow({ g }: { g: UpcomingEvent }) {
  const date = new Date(g.event.starts_at)
  const dayNum = date.toLocaleDateString('en-AU', { day: 'numeric' })
  const monthShort = date.toLocaleDateString('en-AU', { month: 'short' }).toUpperCase()
  const time = date
    .toLocaleTimeString('en-AU', { hour: 'numeric', minute: '2-digit', hour12: true })
    .toLowerCase().replace(/\s+/g, '')

  // State resolution matches the source-of-truth flags on EventSummary.
  // Paid Gatherings are labelled distinctly so a ticketed row never uses
  // the free-Reserve verb; the detail page runs the full purchase flow.
  const isAttending = g.event.my_booking_status === 'confirmed'
  const isPaid = g.event.booking_access_type === 'paid_separately'
  const canReserve = !isAttending && !isPaid && g.event.requires_booking && g.event.can_book
  const paidBuyable = !isAttending && isPaid && g.event.sales_enabled
    && (g.event.spots_remaining === null || g.event.spots_remaining > 0)
  const actionLabel = isAttending
    ? "You're attending"
    : paidBuyable
      ? 'Buy your ticket →'
      : canReserve
        ? 'Reserve →'
        : 'View →'
  const actionColor = isAttending ? 'rgba(12, 24, 38, 0.55)' : '#38A09E'

  return (
    <Link
      href={`/spaces/${g.spaceSlug}/events/${g.event.id}`}
      className="group flex items-start gap-3 rounded-2xl bg-white px-4 py-3 transition-all hover:-translate-y-0.5"
      style={{
        ...ATLAS_CARD_STYLE,
        boxShadow: '0 3px 12px rgba(12, 24, 38, 0.05)',
      }}
    >
      {/* Compact date block */}
      <div
        className="flex h-[52px] w-[52px] shrink-0 flex-col items-center justify-center rounded-lg"
        style={{
          background:
            'linear-gradient(180deg, rgba(56, 160, 158, 0.08) 0%, rgba(212, 176, 72, 0.12) 100%)',
          border: '1px solid rgba(12, 24, 38, 0.06)',
        }}
      >
        <span
          className="font-serif text-[17px] leading-none"
          style={{ color: '#0C1826' }}
        >
          {dayNum}
        </span>
        <span
          className="mt-0.5 text-[9px] font-semibold uppercase tracking-[0.14em]"
          style={{ color: '#38A09E' }}
        >
          {monthShort}
        </span>
      </div>

      <div className="min-w-0 flex-1">
        <h3
          className="truncate font-serif text-[14.5px] leading-snug"
          style={{ color: '#0C1826' }}
        >
          {g.event.title}
        </h3>
        <p
          className="mt-0.5 truncate text-[12px]"
          style={{ color: 'rgba(12, 24, 38, 0.60)' }}
        >
          {g.spaceName}
        </p>
        <p
          className="mt-0.5 truncate text-[12px]"
          style={{ color: 'rgba(12, 24, 38, 0.60)' }}
        >
          {time}
        </p>
        <p
          className="mt-1.5 text-[12px] font-semibold"
          style={{ color: actionColor }}
        >
          {actionLabel}
        </p>
      </div>
    </Link>
  )
}
