import type { Metadata } from 'next'
import { cookies } from 'next/headers'
import Link from 'next/link'
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
import { isDiscoveryPillarEnabled } from '@/lib/featureFlags'
import type { CreatorSpaceDetail, SpaceMembership, SpaceSummary, PublicSpaceCard, SpaceResponse, EventSummary } from '@/types/platform'
import { ATLAS_CARD_STYLE, AtlasArtwork, AtlasCardBody } from './AtlasCard'
import CreatorCollectiveCard from './CreatorCollectiveCard'
import RecentMomentsSection from './RecentMomentsSection'

export const metadata: Metadata = {
  title: 'Your World · Fresh Collective',
  description:
    "What's happening in your communities today, and a few quiet doors to elsewhere.",
}

/**
 * Your World — the member's personal home (route: /dashboard).
 *
 * Reads as a home, not a dashboard. Answers "what is happening in my
 * world today?" — never "what do I need to do?" See
 * docs/experience/your-world.md for the design brief this page is
 * measured against.
 *
 * Single-column vertical flow (no sticky sidebar). Order:
 *   1. Welcome            — warm greeting, unchanged from before
 *   2. Recent Moments     — retrospective, "while you were away"
 *   3. Coming up          — upcoming Gatherings, invitational; hidden
 *                            when there's nothing to say (breathing
 *                            room, per the brief)
 *   4. Your Collectives   — the communities you belong to; no count,
 *                            grid of cards
 *   5. Elsewhere          — Gentle Invitations: Explore Collectives
 *                            (always), plus Discover Places and Ways
 *                            to Connect when the Discovery pillar
 *                            flag is on
 *   6. For creators       — Collectives you've created + Creator
 *                            Studio, visually separated below the
 *                            member surfaces so the two modes don't
 *                            blur
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
 * Filter upcoming Gatherings for the "Coming up" section:
 *   - `soon`:      up to 4 active events starting within the next 14 days
 *   - `hasMore`:   any upcoming event exists beyond what's shown (either
 *                  outside the 14-day window, or past the 4-item cap)
 *
 * Two weeks (not one) is a gentle expansion — the previous 7-day window
 * often produced an empty state on a quiet week even when a real
 * Gathering sat 9 or 10 days out. Your World would rather show a
 * warmer, slightly longer horizon than say "nothing scheduled" when
 * something is genuinely coming.
 */
function filterUpcoming(cards: MembershipCard[]): { soon: UpcomingEvent[]; hasMore: boolean } {
  const now = Date.now()
  const windowEnd = now + 14 * 24 * 60 * 60 * 1000
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

  const inWindow = all.filter((u) => new Date(u.event.starts_at).getTime() <= windowEnd)
  const soon = inWindow.slice(0, 4)
  const hasMore = all.length > soon.length
  return { soon, hasMore }
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
  const { soon, hasMore } = filterUpcoming(cards)
  const discoveryOn = isDiscoveryPillarEnabled()

  return (
    <div className="min-h-screen" style={{ background: '#FAFAF8' }}>
      {/* The persistent member header (wordmark, peer nav, notifications,
          profile shortcut, logout) is provided by WorldShell mounted in
          dashboard/layout.tsx. Nothing to render here. */}

      {/* Welcome — warm greeting, unchanged from before. */}
      <WelcomeBanner firstName={firstName} />

      <main className="mx-auto max-w-[1000px] px-6 pt-12 pb-24 md:px-10 md:pt-14 md:pb-28">

        {/* Page title — kept for now (product decision to trial keeping
            vs. removing). Subtitle reframed toward the brief: what's
            happening + a quiet nod to curiosity. No "Overview" eyebrow;
            this is a home, not a dashboard section. */}
        <div className="mb-12">
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
            What&rsquo;s happening in your communities today, and a
            few quiet doors to elsewhere.
          </p>
        </div>

        {/* Recent Moments — retrospective read: "here's what your
            communities have been doing while you were away." */}
        <RecentMomentsSection />

        {/* Coming up — invitational not obligation. Only rendered
            when there's actually something coming; if the horizon is
            quiet, the page is allowed to breathe. */}
        {soon.length > 0 && (
          <Section
            title="Coming up"
            subtitle="Upcoming Gatherings from the communities you belong to."
            noSpacing
            className="mt-12"
          >
            <div className="flex flex-col gap-3">
              {soon.map((g) => (
                <SidebarGatheringRow key={g.event.id} g={g} />
              ))}
            </div>
            {hasMore && (
              <p
                className="mt-3 text-[12px] italic"
                style={{ color: 'rgba(12, 24, 38, 0.50)', fontFamily: 'Georgia, serif' }}
              >
                More Gatherings beyond the next two weeks.
              </p>
            )}
          </Section>
        )}

        {/* Your Collectives — the communities you're currently part
            of. No count next to the title (belonging is not
            inventory). The empty state stays for members yet to
            join anything, but stays quiet. */}
        <Section
          title="Your Collectives"
          subtitle="Communities you&rsquo;re currently part of."
          noSpacing
          className="mt-14"
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
                You&rsquo;re not part of any Collectives yet.
              </p>
            </div>
          )}
        </Section>

        {/* Elsewhere in the world — gentle invitations. Always shows
            Explore Collectives; adds Discover Places and Ways to
            Connect when the Discovery pillar flag is on. Framed as
            doors, not tasks — the brief's "curiosity" outcome lives
            here. */}
        <Section
          title="Elsewhere in the world"
          subtitle="A few quiet doors, when you&rsquo;re curious."
          noSpacing
          className="mt-14"
        >
          <div className={
            discoveryOn
              ? 'grid gap-8 sm:grid-cols-2 lg:grid-cols-3'
              : 'grid gap-8 sm:grid-cols-2'
          }>
            <ExploreCollectivesCard
              artUrl={exploreArt?.thumbnail_url ?? exploreArt?.image_url ?? null}
            />
            {discoveryOn && (
              <>
                <DiscoverPlacesCard />
                <WaysToConnectCard />
              </>
            )}
          </div>
        </Section>

        {/* ─────── For creators — visually separated below the member
            surfaces so the two modes don't blur. Only rendered when
            the reader is a creator/admin, or when they've created at
            least one Collective. ─────── */}
        {(creatorCards.length > 0 || isCreatorOrAdmin) && (
          <div
            className="mt-20 pt-12"
            style={{ borderTop: '1px dashed rgba(12,24,38,0.10)' }}
          >
            <p
              className="mb-2 text-[11px] font-semibold uppercase tracking-[0.28em]"
              style={{ color: 'rgba(12,24,38,0.45)' }}
            >
              For creators
            </p>
            <h3
              className="mb-8 font-serif text-[22px] leading-tight md:text-[24px]"
              style={{ color: '#0C1826' }}
            >
              What you&rsquo;re building
            </h3>

            {creatorCards.length > 0 && (
              <Section
                title="Collectives you created"
                subtitle="Communities you&rsquo;re building and managing."
                noSpacing
                className="mb-12"
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

            {isCreatorOrAdmin && (
              <Section
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
          </div>
        )}

      </main>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section header — matches the Admin Atlas section pattern
// ---------------------------------------------------------------------------

function Section({
  eyebrow, title, subtitle, children, noSpacing, className,
}: {
  /** Optional small caps label above the title. Most Your World
   *  sections drop this — a home shouldn't feel like a dashboard
   *  of eyebrows. Kept as an option for the "For creators" band. */
  eyebrow?: string
  title: string
  subtitle?: string
  children: React.ReactNode
  /** When true, omit the top margin — used when the Section is placed
   *  inside a composed layout wrapper that already provides spacing. */
  noSpacing?: boolean
  /** Extra classes for spacing / positioning. */
  className?: string
}) {
  const spacingClass = noSpacing ? '' : 'mt-14 first:mt-10'
  return (
    <section className={[spacingClass, className].filter(Boolean).join(' ')}>
      <div className="mb-6">
        {eyebrow && (
          <p
            className="mb-2 text-[11px] font-semibold uppercase tracking-[0.28em]"
            style={{ color: '#38A09E' }}
          >
            {eyebrow}
          </p>
        )}
        <h2
          className="font-serif text-[22px] leading-tight md:text-[24px]"
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
// Discover Places card — Gentle Invitation to the Discovery pillar.
// Only rendered when the pillar flag is on. The visual identity uses a
// calm coastal-teal atmosphere so it reads as a place, not a menu.
// ---------------------------------------------------------------------------

function DiscoverPlacesCard() {
  return (
    <Link
      href="/discover-places"
      className="group block overflow-hidden rounded-2xl bg-white transition-all"
      style={ATLAS_CARD_STYLE}
    >
      <div
        className="relative w-full overflow-hidden"
        style={{
          aspectRatio: '3 / 2',
          background:
            'linear-gradient(135deg, rgba(181, 217, 213, 0.55) 0%, rgba(122, 182, 177, 0.60) 100%)',
        }}
      >
        <div
          className="absolute inset-0"
          style={{
            background:
              'radial-gradient(ellipse at 22% 22%, rgba(255,255,255,0.32), transparent 60%)',
          }}
        />
      </div>
      <AtlasCardBody
        name="Discover Places"
        description="The cities and regions where Fresh Collective communities are quietly growing."
        meta="Elsewhere in the world"
        cta="Explore →"
      />
    </Link>
  )
}

// ---------------------------------------------------------------------------
// Ways to Connect card — Gentle Invitation. Warm sand atmosphere to
// distinguish it from Discover Places without loudness.
// ---------------------------------------------------------------------------

function WaysToConnectCard() {
  return (
    <Link
      href="/ways-to-connect"
      className="group block overflow-hidden rounded-2xl bg-white transition-all"
      style={ATLAS_CARD_STYLE}
    >
      <div
        className="relative w-full overflow-hidden"
        style={{
          aspectRatio: '3 / 2',
          background:
            'linear-gradient(135deg, rgba(232, 223, 211, 0.70) 0%, rgba(199, 185, 156, 0.65) 100%)',
        }}
      >
        <div
          className="absolute inset-0"
          style={{
            background:
              'radial-gradient(ellipse at 22% 22%, rgba(255,255,255,0.36), transparent 60%)',
          }}
        />
      </div>
      <AtlasCardBody
        name="Ways to Connect"
        description="Meaningful moments of connection — Gatherings, conversations, and shared journeys."
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
