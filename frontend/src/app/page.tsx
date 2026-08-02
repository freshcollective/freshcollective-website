import type { Metadata } from 'next'
import Link from 'next/link'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import HomeHero from '@/components/home/HomeHero'
import ArtworkFeatureComposition from '@/components/marketing/ArtworkFeatureComposition'
import ClosingInvitation from '@/components/marketing/ClosingInvitation'
import { atmosphereBackground, atmosphereForSlug } from '@/lib/placeAtmosphere'
import { resolveMediaUrl } from '@/lib/api'
import { getPublicPlatformArtwork, type PublicPlatformArtwork } from '@/lib/serverApi'

/**
 * Fresh Collective homepage.
 *
 * Three-part narrative, presented as one continuous editorial page
 * rather than a stack of chapter title cards. The overall body stays
 * white so the artwork, cards, and small accents carry the colour;
 * the closing invitation returns to deep navy for a calm final moment.
 *
 * Managed artwork lives in the shared World Artwork registry
 * (see backend/app/admin/platform_artwork.py, keys `homepage_*`).
 * Missing artwork falls back to atmospheric gradients or, where the
 * brief prefers, a hand-coded interface visual.
 *
 * TODO(homepage-screenshots): the four "Life inside a Collective"
 * cards use hand-coded editorial mockups. When real product surfaces
 * are strong enough to capture, drop the PNGs under
 * `public/homepage/screenshots/` and swap the mockup component for
 * an <img>.
 */

export const metadata: Metadata = {
  title: 'Fresh Collective — a home for creator-led communities',
  description:
    'Fresh Collective is a home for creator-led communities where people learn, gather, connect and grow together. Explore a collective, or create one of your own.',
  openGraph: {
    title: 'Fresh Collective — a home for creator-led communities',
    description:
      'Places where people learn together, gather and grow. Explore a collective, or create one of your own.',
    type: 'website',
  },
}


// ─── Design tokens (scoped to this file) ─────────────────────────────
const TEAL = '#38A09E'
const TEAL_DEEP = '#246B6A'
const NAVY = '#0C1826'
const INK_BODY = 'rgba(12, 24, 38, 0.80)'
const INK_SOFT = 'rgba(12, 24, 38, 0.66)'
const HAIRLINE = 'rgba(12, 24, 38, 0.10)'



function buildArtLookup(items: PublicPlatformArtwork[]): (key: string) => string | null {
  const byKey = new Map(items.map((a) => [a.key, a]))
  return (key: string) => {
    const item = byKey.get(key)
    if (!item) return null
    return resolveMediaUrl(item.image_url ?? item.thumbnail_url ?? undefined) ?? null
  }
}


export default async function HomePage() {
  const artwork = await getPublicPlatformArtwork().catch(() => [] as PublicPlatformArtwork[])
  const artFor = buildArtLookup(artwork)

  return (
    <SiteShell heroHeader>
      <HomeHero />
      <Belief />
      <ExploreSection artFor={artFor} />
      <InsideCollectiveSection artFor={artFor} />
      <CreatorSection artUrl={artFor('homepage_creator_studio')} />
      <ClosingInvitation
        headingLines={['Find your Collective.', 'Or create one.']}
        body="Every meaningful community begins with someone deciding to bring people together."
        primaryCta={{ label: 'Explore Collectives', href: '/spaces' }}
        secondaryCta={{ label: 'Create a Collective', href: '/for-creators' }}
        artUrl={artFor('homepage_closing_invitation')}
      />
    </SiteShell>
  )
}


// ═══════════════════════════════════════════════════════════════════
// BELIEF — the philosophy beat that immediately follows the hero.
//
// Focal point is the headline. Second sentence carries the teal→navy
// gradient. Body copy and "Come and see" sit as secondary detail.
// ═══════════════════════════════════════════════════════════════════

function Belief() {
  return (
    <section
      className="pt-20 pb-14 sm:pt-28 sm:pb-16"
      style={{ background: '#FFFFFF' }}
    >
      <Container>
        <div className="mx-auto max-w-[860px] text-center">

          <h2
            className="mx-auto font-serif leading-[1.08] text-navy-900"
            style={{
              fontSize: 'clamp(2.125rem, 5.4vw, 3.75rem)',
              letterSpacing: '-0.03em',
              color: NAVY,
              maxWidth: '780px',
            }}
          >
            <span className="block">Most platforms optimise for engagement.</span>
            <span
              className="mt-2 block"
              style={{
                backgroundImage: `linear-gradient(100deg, ${TEAL} 0%, ${TEAL_DEEP} 55%, ${NAVY} 100%)`,
                WebkitBackgroundClip: 'text',
                backgroundClip: 'text',
                color: 'transparent',
              }}
            >
              We optimise for belonging.
            </span>
          </h2>

          <p
            className="mx-auto mt-10 max-w-[620px] text-[16px] italic leading-relaxed"
            style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
          >
            Meaningful communities grow when people feel welcomed,
            supported and able to contribute. Every part of Fresh
            Collective has been built to encourage connection — to
            create more human moments, rather than simply more
            consumption.
          </p>
          <p
            className="mx-auto mt-5 max-w-[620px] text-[16px] italic leading-relaxed"
            style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
          >
            People grow through what they do together — the
            conversations they have, the sessions they show up for,
            the small contributions that help someone else along.
            A membership that leaves a mark isn&rsquo;t measured in
            what you consumed; it&rsquo;s measured in what you took
            part in.
          </p>
        </div>
      </Container>
    </section>
  )
}


// ═══════════════════════════════════════════════════════════════════
// SECTION OPENING — a small heading + intro block that lives inside
// a section (not on its own titled "chapter" page). No numerals, no
// separate background, no divider ornaments.
// ═══════════════════════════════════════════════════════════════════

function SectionOpening({
  title, body, className,
}: {
  title: string
  body?: string
  className?: string
}) {
  return (
    <div className={`mx-auto max-w-[680px] text-center ${className ?? ''}`}>
      <h2
        className="font-serif leading-[1.1] text-navy-900"
        style={{
          fontSize: 'clamp(1.875rem, 4.4vw, 2.75rem)',
          letterSpacing: '-0.03em',
          color: NAVY,
        }}
      >
        {title}
      </h2>
      {body && (
        <p
          className="mx-auto mt-5 max-w-[560px] text-[15.5px] italic leading-relaxed"
          style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
        >
          {body}
        </p>
      )}
    </div>
  )
}


// ═══════════════════════════════════════════════════════════════════
// EXPLORE THE WORLD — heading + three discovery cards.
// ═══════════════════════════════════════════════════════════════════

interface DiscoveryEntry {
  artKey: string
  atmosphereSlug: string
  title: string
  body: string
  href: string
  cta: string
  alt: string
}

const DISCOVERY_ENTRIES: DiscoveryEntry[] = [
  {
    artKey: 'homepage_explore_collectives',
    atmosphereSlug: 'homepage-explore-collectives',
    title: 'Explore Collectives',
    body: 'Find Collectives shaped around what you care about — the ideas, practices and journeys that match your interests, needs or direction.',
    href: '/spaces',
    cta: 'Explore Collectives',
    alt: 'Fresh Collective — Explore Collectives',
  },
  {
    artKey: 'homepage_discover_places',
    atmosphereSlug: 'homepage-discover-places',
    title: 'Discover Places',
    body: 'See where Collectives are gathering across cities, regions and other real-world places.',
    href: '/discover-places',
    cta: 'Discover Places',
    alt: 'Fresh Collective — Discover Places',
  },
  {
    artKey: 'homepage_ways_to_connect',
    atmosphereSlug: 'homepage-ways-to-connect',
    title: 'Ways to Connect',
    body: 'Meet people through the meaningful things you already share — the Collectives you belong to, the Pathways you walk, the Places you gather in.',
    href: '/ways-to-connect',
    cta: 'See how it works',
    alt: 'Fresh Collective — Ways to Connect',
  },
]

function ExploreSection({ artFor }: { artFor: (key: string) => string | null }) {
  return (
    <section className="py-16 sm:py-20" style={{ background: '#FFFFFF' }}>
      <Container>
        <SectionOpening
          title="Explore the world."
          body="Fresh Collective gives you different ways to discover where you might belong. Explore Collectives by name, theme or the experiences they offer. Discover communities gathering in your local area. Or meet people whose Pathways, Gatherings and interests already cross with your own."
          className="mb-10 sm:mb-14"
        />
        <div className="grid gap-6 md:grid-cols-3">
          {DISCOVERY_ENTRIES.map((entry) => (
            <DiscoveryCard
              key={entry.artKey}
              entry={entry}
              artUrl={artFor(entry.artKey)}
            />
          ))}
        </div>
      </Container>
    </section>
  )
}

function DiscoveryCard({
  entry, artUrl,
}: {
  entry: DiscoveryEntry
  artUrl: string | null
}) {
  return (
    <Link
      href={entry.href}
      className="group flex flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white transition-shadow hover:shadow-[0_10px_28px_rgba(12,24,38,0.06)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/50 focus-visible:ring-offset-2"
    >
      <div
        className="relative w-full overflow-hidden"
        style={{ aspectRatio: '5 / 3' }}
      >
        {artUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={artUrl}
            alt={entry.alt}
            className="absolute inset-0 h-full w-full object-cover object-center transition-transform duration-500 group-hover:scale-[1.02]"
          />
        ) : (
          <div
            aria-hidden="true"
            className="absolute inset-0"
            style={{
              background: atmosphereBackground(atmosphereForSlug(entry.atmosphereSlug, false)),
            }}
          />
        )}
      </div>
      <div className="flex flex-1 flex-col p-6 md:p-7">
        <h3
          className="font-serif text-[22px] leading-tight md:text-[24px]"
          style={{ color: NAVY }}
        >
          {entry.title}
        </h3>
        <p
          className="mt-3 text-[14px] leading-relaxed"
          style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
        >
          {entry.body}
        </p>
        <p
          className="mt-auto pt-6 text-[13px] font-semibold transition-transform group-hover:translate-x-0.5"
          style={{ color: TEAL_DEEP }}
        >
          {entry.cta} →
        </p>
      </div>
    </Link>
  )
}


// ═══════════════════════════════════════════════════════════════════
// LIFE INSIDE A COLLECTIVE — four editorial feature rows.
//
// No cards, no borders, no dividers. Each row is a spread — copy on
// one side, the interface visual on the other, alternating. The
// mockups themselves are the hero; whitespace defines the rhythm.
//
// Column proportions vary per feature so the four rows never feel
// mechanically identical (Apple / Airbnb / Notion editorial style).
//
// Mockups render directly on the page white with a soft ambient
// shadow — floating product photography rather than framed cards.
// ═══════════════════════════════════════════════════════════════════

// The grid template flips per row so the ARTWORK column is always
// the wider one regardless of whether the row shows copy-left or
// copy-right. Without this flip, source-order swapping alone would
// leave the artwork in the narrow column on flipped rows.
const INSIDE_GRID_COPY_LEFT  = 'md:grid-cols-[minmax(0,0.78fr)_minmax(0,1.3fr)]'
const INSIDE_GRID_COPY_RIGHT = 'md:grid-cols-[minmax(0,1.3fr)_minmax(0,0.78fr)]'

interface Feature {
  title: string
  body: string
  artKey: string
  atmosphereSlug: string
  artAlt: string
}

function InsideCollectiveSection({ artFor }: { artFor: (key: string) => string | null }) {
  const features: Feature[] = [
    {
      title: 'Walk meaningful Pathways.',
      body: 'Pathways are creator-guided journeys made up of thoughtful steps — courses, programs, practices, prompts, reflections and materials to learn from and grow.',
      artKey: 'homepage_pathways',
      atmosphereSlug: 'inside-pathways',
      artAlt: 'A Pathway inside a Fresh Collective community',
    },
    {
      title: 'Come together at Gatherings.',
      body: 'Gatherings bring members and creators together online or in person — sessions, circles, workshops and events. Human-centred, interactive, and worth showing up for.',
      artKey: 'homepage_gatherings',
      atmosphereSlug: 'inside-gatherings',
      artAlt: 'A Gathering inside a Fresh Collective community',
    },
    {
      title: 'Continue in Conversation.',
      body: 'Conversations give members a place to keep talking between Gatherings and Pathway steps — reflect on what has been shared, welcome new arrivals, and support one another along the way.',
      artKey: 'homepage_conversations',
      atmosphereSlug: 'inside-conversations',
      artAlt: 'Members in conversation inside a Fresh Collective community',
    },
    {
      title: 'Resources you can return to.',
      body: 'Practical materials for members to use in their own time — recordings, guides, workbooks and worksheets, all kept in one place. A reference shelf that grows as the Collective does.',
      artKey: 'homepage_resources',
      atmosphereSlug: 'inside-resources',
      artAlt: 'Resources shared inside a Fresh Collective community',
    },
  ]

  return (
    <section className="py-24 sm:py-32" style={{ background: '#FFFFFF' }}>
      <Container>
        <SectionOpening
          title="Life inside a Collective."
          body="Every Collective holds different experiences, including — Pathways to walk, Gatherings to attend, Conversations to connect, and Resources to return to. Together they shape the daily rhythm of belonging."
          className="mb-20 sm:mb-28"
        />

        <div className="mx-auto flex max-w-[1160px] flex-col gap-20 md:gap-28">
          {features.map((feature, i) => (
            <FeatureRow
              key={feature.title}
              feature={feature}
              flipped={i % 2 === 1}
              artUrl={artFor(feature.artKey)}
            />
          ))}
        </div>
      </Container>
    </section>
  )
}

function FeatureRow({
  feature, flipped, artUrl,
}: {
  feature: Feature
  flipped: boolean
  artUrl: string | null
}) {
  const copy = (
    <div className="flex flex-col justify-center">
      <h3
        className="font-serif leading-[1.08] text-navy-900"
        style={{
          fontSize: 'clamp(1.75rem, 3.4vw, 2.5rem)',
          letterSpacing: '-0.02em',
          color: NAVY,
        }}
      >
        {feature.title}
      </h3>
      <p
        className="mt-5 max-w-[420px] text-[15.5px] leading-relaxed"
        style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
      >
        {feature.body}
      </p>
    </div>
  )

  const artwork = (
    <ArtworkFeatureComposition
      artworkUrl={artUrl}
      atmosphereSlug={feature.atmosphereSlug}
      artworkAlt={feature.artAlt}
    />
  )

  // The grid template flips so the artwork is always in the wider
  // 1.3fr column, and source order flips to match — no `order`
  // trickery. Result: identical artwork dimensions on every row.
  const gridClass = flipped ? INSIDE_GRID_COPY_RIGHT : INSIDE_GRID_COPY_LEFT

  return (
    <div className={`grid grid-cols-1 items-center gap-12 md:gap-20 ${gridClass}`}>
      {flipped ? (
        <>{artwork}{copy}</>
      ) : (
        <>{copy}{artwork}</>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════
// CREATOR SECTION — heading, wide anchor image, outcomes, CTA.
//
// When homepage_creator_studio artwork is uploaded, that's the anchor.
// Otherwise fall back to a polished Creator Studio interface mockup
// (not a plain atmospheric gradient — this section deserves a real
// interface moment).
// ═══════════════════════════════════════════════════════════════════

function CreatorSection({ artUrl }: { artUrl: string | null }) {
  const outcomes = [
    {
      title: 'Design your place.',
      body: 'Choose the atmosphere, the palette, the voice — the feeling people get when they visit your Collective.',
    },
    {
      title: 'Build Pathways.',
      body: 'Guide members through your programs, courses and memberships.',
    },
    {
      title: 'Host Gatherings.',
      body: 'Set live moments — circles, workshops, retreats, video calls, movement sessions and more — and welcome people in for that human connection.',
    },
    {
      title: 'Grow your community.',
      body: 'Watch your Collective blossom as people return, participate, contribute and stay.',
    },
  ]

  return (
    <section className="py-16 sm:py-20" style={{ background: '#FFFFFF' }}>
      <Container>
        <SectionOpening
          title="Build a place of your own."
          body="Every meaningful community begins with someone deciding to bring people together. Fresh Collective gives you the tools to start building a Collective people want to return to."
          className="mb-10 sm:mb-12"
        />

        {/* Anchor — managed artwork if present, otherwise a polished
            Creator Studio interface mockup. */}
        <div className="mx-auto max-w-[1080px]">
          <div
            className="relative w-full overflow-hidden rounded-3xl bg-white"
            style={{
              aspectRatio: artUrl ? '16 / 9' : undefined,
              border: '1px solid rgba(12, 24, 38, 0.08)',
              boxShadow: '0 1px 3px rgba(12, 24, 38, 0.04)',
            }}
          >
            {artUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={artUrl}
                alt="Fresh Collective — Creator Studio"
                className="absolute inset-0 h-full w-full object-cover object-center"
              />
            ) : (
              <CreatorStudioMockup />
            )}
          </div>
        </div>

        {/* Outcomes */}
        <div className="mx-auto mt-12 max-w-[880px] sm:mt-14">
          <ul className="grid gap-x-14 gap-y-8 sm:grid-cols-2">
            {outcomes.map((o) => (
              <li key={o.title}>
                <h4
                  className="font-serif text-[20px] leading-tight"
                  style={{ color: NAVY, letterSpacing: '-0.01em' }}
                >
                  {o.title}
                </h4>
                <p
                  className="mt-2 text-[14.5px] leading-relaxed"
                  style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
                >
                  {o.body}
                </p>
              </li>
            ))}
          </ul>

          <div className="mt-10 text-center">
            <Link
              href="/for-creators"
              className="text-[14px] font-semibold transition-opacity hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2 rounded"
              style={{ color: TEAL_DEEP }}
            >
              See what else is available to creators →
            </Link>
          </div>
        </div>
      </Container>
    </section>
  )
}


// Creator Studio interface mockup — polished, editorial, uses the
// same design tokens as the real /creator-studio/home surface.
function CreatorStudioMockup() {
  return (
    <div className="flex flex-col gap-8 p-8 md:flex-row md:gap-10 md:p-12">
      {/* Left column — collective identity + Today's focus */}
      <div className="flex-1">
        <p
          className="text-[10.5px] font-semibold uppercase tracking-[0.24em]"
          style={{ color: TEAL }}
        >
          Collective Overview
        </p>
        <h4
          className="mt-2 font-serif text-[26px] leading-tight md:text-[30px]"
          style={{ color: NAVY, letterSpacing: '-0.02em' }}
        >
          The Grove
        </h4>
        <p className="mt-1 text-[13px]" style={{ color: INK_SOFT }}>
          Alive and open · 47 members
        </p>

        <div className="mt-6">
          <div className="mb-3 flex items-baseline justify-between">
            <p className="font-serif text-[16px]" style={{ color: NAVY }}>
              Today&rsquo;s focus
            </p>
            <span
              className="rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold"
              style={{ background: 'rgba(56, 160, 158, 0.10)', color: TEAL_DEEP }}
            >
              2 waiting
            </span>
          </div>
          <div
            className="relative overflow-hidden rounded-xl bg-white px-4 py-3.5 pl-5"
            style={{ border: `1px solid ${HAIRLINE}` }}
          >
            <span
              className="absolute inset-y-0 left-0 w-[3px]"
              style={{ background: `linear-gradient(180deg, ${TEAL} 0%, rgba(56, 160, 158, 0.55) 100%)` }}
              aria-hidden="true"
            />
            <p className="text-[13.5px] font-semibold" style={{ color: NAVY }}>
              A pathway is waiting to open
            </p>
            <p className="mt-1 text-[12.5px]" style={{ color: INK_BODY }}>
              Publish when it feels ready.
            </p>
          </div>
        </div>
      </div>

      {/* Right column — Snapshot stats */}
      <div className="md:w-[280px] md:shrink-0">
        <p
          className="text-[10.5px] font-semibold uppercase tracking-[0.24em]"
          style={{ color: TEAL }}
        >
          Snapshot
        </p>
        <div className="mt-3 grid grid-cols-2 gap-2.5">
          <MiniStat label="Members" value="47" tint="teal" />
          <MiniStat label="Pathways" value="5" tint="teal" />
          <MiniStat label="Gatherings" value="2" tint="gold" />
          <MiniStat label="Conversations" value="12" tint="teal" />
        </div>

        <p
          className="mt-6 text-[10.5px] font-semibold uppercase tracking-[0.24em]"
          style={{ color: TEAL }}
        >
          What to do next
        </p>
        <ul className="mt-3 flex flex-col gap-2">
          {['Create a pathway', 'Invite members', 'Host a gathering'].map((label) => (
            <li
              key={label}
              className="flex items-center justify-between rounded-xl px-3.5 py-2.5"
              style={{ border: `1px solid ${HAIRLINE}` }}
            >
              <span className="text-[13px]" style={{ color: NAVY }}>{label}</span>
              <span aria-hidden="true" className="text-[13px] font-semibold" style={{ color: TEAL_DEEP }}>→</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function MiniStat({
  label, value, tint,
}: {
  label: string
  value: string
  tint: 'teal' | 'gold'
}) {
  const bg = tint === 'teal' ? 'rgba(56, 160, 158, 0.10)' : 'rgba(212, 176, 72, 0.14)'
  return (
    <div
      className="rounded-xl bg-white px-3 py-2.5"
      style={{ border: `1px solid ${HAIRLINE}` }}
    >
      <div className="flex items-start justify-between">
        <p className="text-[10.5px] font-medium uppercase" style={{ color: INK_SOFT, letterSpacing: '0.08em' }}>
          {label}
        </p>
        <span
          className="h-4 w-4 shrink-0 rounded-full"
          style={{ background: bg }}
          aria-hidden="true"
        />
      </div>
      <p className="mt-1 font-serif text-[22px] leading-none" style={{ color: NAVY }}>
        {value}
      </p>
    </div>
  )
}


