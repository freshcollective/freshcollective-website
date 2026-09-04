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
import type { CreatorSpaceDetail, SpaceMembership, SpaceSummary, PublicSpaceCard, SpaceResponse, EventSummary, UserProfile } from '@/types/platform'
import { ATLAS_CARD_STYLE, AtlasArtwork, AtlasCardBody } from './AtlasCard'
import CreatorCollectiveCard from './CreatorCollectiveCard'
import RecentMomentsSection from './RecentMomentsSection'
import VerifyEmailBanner from '@/components/settings/VerifyEmailBanner'

/**
 * Shared card-grid class for every full-width band on /dashboard —
 * Elsewhere in the world, Your Collectives (when the Coming up
 * sidebar is not present), Collectives you created, Create &
 * Manage. Guarantees a single consistent breakpoint pattern:
 *
 *     mobile          — 1 card per row
 *     sm (640px+)     — 2 cards per row
 *     lg (1024px+)    — 3 cards per row
 *
 * Chosen with the wide-desktop math in mind: at lg the full-width
 * inner is ~944px, comfortably hosting three ~293px cards. Below
 * lg the grid falls back to 2-across naturally.
 *
 * The narrower "Your Collectives" grid that renders inside the
 * two-column sidebar region does NOT use this constant — that
 * variant lives at ~640px of main column and stays at 2-across
 * even on large screens.
 */
const FULL_WIDTH_CARD_GRID = 'grid gap-8 sm:grid-cols-2 lg:grid-cols-3'

export const metadata: Metadata = {
  title: 'Your World · Fresh Collective',
  description:
    "What's happening in your communities today, and a few doorways into the rest of Fresh Collective.",
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

async function getUser(): Promise<UserProfile | null> {
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
    UserProfile | null,
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
  const discoverPlacesArt = artworkByKey.get('discover_places') ?? null
  const waysToConnectArt = artworkByKey.get('ways_to_connect') ?? null
  const orientationArt = artworkByKey.get('new_to_fresh_collective') ?? null

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

      {/* SEC-009 — verification banner. Only appears while the
          account is unverified; disappears the moment the user
          confirms their email. */}
      {user && !user.email_verified_at ? (
        <VerifyEmailBanner email={user.email} />
      ) : null}

      <main className="mx-auto max-w-[1440px] px-6 pt-12 pb-24 md:px-10 md:pt-14 md:pb-28">

        {/* Page title — kept for now (product decision to trial keeping
            vs. removing). Subtitle reframed toward the brief: what's
            happening + a quiet nod to curiosity. No "Overview" eyebrow;
            this is a home, not a dashboard section. Sits above the
            two-column layout so it spans the full width on desktop. */}
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
            few doorways into the rest of Fresh Collective.
          </p>
        </div>

        {/* ─────── Upper member region — two-column on desktop ───────
            The two-column grid holds ONLY Recent Moments + Your
            Collectives on the left and Coming up on the right. Once
            those two sections end the layout returns to full width
            so Elsewhere and the Creator sections can use the whole
            page without being constrained by the sidebar.

            Grid choices:
              * `items-start` — children align to the top of their
                cells (no stretch-to-match-row-height).
              * sidebar `lg:row-span-2` — spans both main rows so its
                natural height never inflates row 1. Each main row
                sizes to its own content.

            When there's nothing coming up, the two-column grid is
            skipped entirely — Recent Moments and Your Collectives
            get full width. */}
        {soon.length > 0 ? (
          <div className="grid grid-cols-1 gap-x-12 gap-y-12 lg:grid-cols-[minmax(0,1fr)_280px] lg:items-start">

            {/* Recent Moments — "while you were away" */}
            <div className="order-1 lg:col-start-1 lg:row-start-1">
              <RecentMomentsSection />
            </div>

            {/* Coming up — quiet right sidebar; spans both main rows
                so it neither inflates them nor stretches empty into
                the sections below. */}
            <aside className="order-2 lg:col-start-2 lg:row-start-1 lg:row-span-2 lg:self-start">
              <div className="mb-4">
                <h3
                  className="font-serif text-[18px] leading-tight"
                  style={{ color: '#0C1826' }}
                >
                  Coming up
                </h3>
                <p
                  className="mt-1 text-[12.5px] italic leading-relaxed"
                  style={{ color: 'rgba(12, 24, 38, 0.55)', fontFamily: 'Georgia, serif' }}
                >
                  Gatherings from your communities in the next two
                  weeks.
                </p>
              </div>
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
            </aside>

            {/* Your Collectives — main column, row 2. */}
            <Section
              title="Your Collectives"
              subtitle="Communities you&rsquo;re currently part of."
              noSpacing
              className="order-3 lg:col-start-1 lg:row-start-2"
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
          </div>
        ) : (
          // No upcoming Gatherings — full-width single column. Recent
          // Moments and Your Collectives take the whole page width;
          // 3-across cards are available at xl.
          <div className="flex flex-col gap-12">
            <RecentMomentsSection />
            <Section
              title="Your Collectives"
              subtitle="Communities you&rsquo;re currently part of."
              noSpacing
            >
              {cards.length > 0 ? (
                <div className={FULL_WIDTH_CARD_GRID}>
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
          </div>
        )}

        {/* ─────── Elsewhere in the world — full-width band ───────
            Sits below the two-column upper region and uses the whole
            page width so 3 invitations sit on one row at xl. */}
        <Section
          title="Elsewhere in the world"
          subtitle="A few doorways, when you&rsquo;re curious."
          className="mt-14"
          noSpacing
        >
          {/* Uses the shared FULL_WIDTH_CARD_GRID (3-across from lg+)
              when three invitations render. When the Discovery
              pillar is off there's only Explore Collectives here,
              which reads better at 2-across so the single card
              sits alongside a neighbour rather than centre-heavy in
              a 3-column layout. */}
          <div className={
            discoveryOn
              ? FULL_WIDTH_CARD_GRID
              : 'grid gap-8 sm:grid-cols-2'
          }>
            {user && !user.has_completed_onboarding && (
              <OrientationCard
                artUrl={orientationArt?.thumbnail_url ?? orientationArt?.image_url ?? null}
              />
            )}
            <ExploreCollectivesCard
              artUrl={exploreArt?.thumbnail_url ?? exploreArt?.image_url ?? null}
            />
            {discoveryOn && (
              <>
                <DiscoverPlacesCard
                  artUrl={discoverPlacesArt?.thumbnail_url ?? discoverPlacesArt?.image_url ?? null}
                />
                <WaysToConnectCard
                  artUrl={waysToConnectArt?.thumbnail_url ?? waysToConnectArt?.image_url ?? null}
                />
              </>
            )}
          </div>
        </Section>

        {/* ─────── For creators — full-width band, visually separated
            below the member surfaces so the two modes don't blur.
            Only rendered when the reader is a creator/admin, or when
            they've created at least one Collective. ─────── */}
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
                <div className={FULL_WIDTH_CARD_GRID}>
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
                {/* Ready to hold up to three management cards on
                    one row using the shared full-width grid; the
                    single Creator Studio card sits at 1/3 width on
                    lg+, not stretched across the page. */}
                <div className={FULL_WIDTH_CARD_GRID}>
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
// Welcome banner — shares the dark-navy visual family with the Explore
// Collectives hero. Full-bleed, deliberately calmer than the previous
// teal-glow treatment: a clean navy base, a subtle teal accent line,
// and the gradient reserved for the two words that carry the warmth
// ("Welcome back") while the rest of the greeting stays in plain white.
// This keeps Your World's welcome personal and warm without making it
// a copy of Explore Collectives.
// ---------------------------------------------------------------------------

function WelcomeBanner({ firstName }: { firstName: string }) {
  return (
    <div
      className="relative overflow-hidden px-6 py-8 md:px-10 md:py-11"
      style={{
        // Clean navy base, matching the Explore Collectives hero
        // (#071824). A very quiet horizontal light-fall from the
        // top-left adds dimension without turning the surface teal.
        //
        // Full-bleed (not a rounded card) is deliberate: Your World
        // is the member's personal return point, so the welcome
        // reads as an entry moment. Explore Collectives is the
        // outward-facing destination and uses a contained card.
        // Both share the navy visual family without becoming the
        // same treatment.
        background:
          'radial-gradient(ellipse at 12% -20%, rgba(56,160,158,0.10), transparent 55%), '
          + 'linear-gradient(180deg, #071824 0%, #061421 100%)',
        borderBottom: '1px solid rgba(56,160,158,0.14)',
        // Soft transition into the page below, not a heavy drop.
        boxShadow: '0 4px 20px rgba(7,24,36,0.14)',
      }}
    >
      {/* Inner container matches the max-w and horizontal padding of
          <main> below so the welcome copy aligns with the page's
          content start on every viewport. */}
      <div className="relative mx-auto max-w-[1440px]">
        <div
          className="mb-5 h-[2px] w-8 rounded-full"
          style={{ background: 'linear-gradient(90deg, #38A09E 0%, rgba(56,160,158,0.2) 100%)' }}
          aria-hidden="true"
        />
        <h1
          className="font-serif"
          style={{
            fontSize: 'clamp(2rem, 4vw, 3rem)',
            lineHeight: 1.1,
            letterSpacing: '-0.02em',
            color: '#FFFFFF',
          }}
        >
          <span
            style={{
              display: 'inline-block',
              background: 'linear-gradient(90deg, #38A09E 0%, #FFFFFF 55%)',
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

// ---------------------------------------------------------------------------
// Orientation card — the soft entry into the (now-optional) Fresh
// Collective orientation. Rendered conditionally when the visitor
// hasn't completed it. Fills the same slot in "Elsewhere in the world"
// as the other invitations so a first-visit member sees it as one of
// several doors, not as a nag.
// ---------------------------------------------------------------------------

function OrientationCard({ artUrl }: { artUrl?: string | null }) {
  const resolved = resolveMediaUrl(artUrl ?? undefined)
  return (
    <Link
      href="/onboarding"
      className="group block overflow-hidden rounded-2xl bg-white transition-all"
      style={ATLAS_CARD_STYLE}
    >
      <div
        className="relative w-full overflow-hidden"
        style={{
          aspectRatio: '3 / 2',
          background:
            'linear-gradient(135deg, rgba(212, 176, 72, 0.18) 0%, rgba(247, 232, 200, 0.22) 55%, rgba(56, 160, 158, 0.14) 100%)',
        }}
      >
        {resolved ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={resolved}
            alt="New to Fresh Collective"
            className="absolute inset-0 h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.02]"
          />
        ) : (
          <svg
            viewBox="0 0 240 160"
            className="absolute left-1/2 top-1/2 h-32 w-40 -translate-x-1/2 -translate-y-1/2 transition-transform duration-500 group-hover:scale-[1.05]"
            aria-hidden="true"
          >
            <circle cx="120" cy="60" r="24" fill="#D4B048" opacity="0.55" />
            <path d="M 20 118 Q 120 108 220 118" stroke="#38A09E" strokeWidth="1.5" fill="none" opacity="0.55" />
            <path d="M 60 130 Q 120 122 180 130" stroke="#38A09E" strokeWidth="0.8" fill="none" opacity="0.35" />
          </svg>
        )}
      </div>
      <AtlasCardBody
        name="New to Fresh Collective?"
        description="Take a short tour of how Collectives, Pathways, Gatherings and Conversations work."
        meta="A gentle introduction"
        cta="Start here →"
      />
    </Link>
  )
}


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

function DiscoverPlacesCard({ artUrl }: { artUrl?: string | null }) {
  const resolved = resolveMediaUrl(artUrl ?? undefined)
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
        {resolved ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={resolved}
            alt="Discover Places"
            className="absolute inset-0 h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.02]"
          />
        ) : (
          <div
            className="absolute inset-0"
            style={{
              background:
                'radial-gradient(ellipse at 22% 22%, rgba(255,255,255,0.32), transparent 60%)',
            }}
          />
        )}
      </div>
      <AtlasCardBody
        name="Discover Places"
        description="The cities and regions where Fresh Collective communities are taking root."
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

function WaysToConnectCard({ artUrl }: { artUrl?: string | null }) {
  const resolved = resolveMediaUrl(artUrl ?? undefined)
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
        {resolved ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={resolved}
            alt="Ways to Connect"
            className="absolute inset-0 h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.02]"
          />
        ) : (
          <div
            className="absolute inset-0"
            style={{
              background:
                'radial-gradient(ellipse at 22% 22%, rgba(255,255,255,0.36), transparent 60%)',
            }}
          />
        )}
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
