import type { Metadata } from 'next'
import Link from 'next/link'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import HomeHero from '@/components/home/HomeHero'
import HomeWhatThisIs from '@/components/home/HomeWhatThisIs'
import HomeFriction from '@/components/home/HomeFriction'
import HomeOnboardingWalkthrough from '@/components/home/HomeOnboardingWalkthrough'
import HomeWorldBuilders from '@/components/home/HomeWorldBuilders'
import HomePricing from '@/components/home/HomePricing'
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
// Warm gold — used for a single accent word in headings that live on
// a light ground. On dark grounds the brighter `#EDBE5D` variant is
// used instead (in HomeHero and HomeWhatThisIs).
const WARM_GOLD = '#D4B048'



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

  // Pre-resolve the four onboarding URLs into a plain object so the
  // interactive (client) walkthrough component doesn't need to receive
  // the server-only `artFor` function across the boundary.
  const onboardingScreenshotUrls: Record<string, string | null> = {
    homepage_onboarding_begin_shaping:       artFor('homepage_onboarding_begin_shaping'),
    homepage_onboarding_shape_the_feeling:   artFor('homepage_onboarding_shape_the_feeling'),
    homepage_onboarding_choose_island:       artFor('homepage_onboarding_choose_island'),
    homepage_onboarding_practical_settings:  artFor('homepage_onboarding_practical_settings'),
  }

  return (
    <SiteShell heroHeader>
      <HomeHero />
      <HomeWhatThisIs />
      <HomeFriction imageSrc={artFor('homepage_friction_conversation')} />
      <ExploreSection artFor={artFor} />
      <InsideCollectiveSection artFor={artFor} />
      <CreatorSection artUrl={artFor('homepage_creator_studio')} />
      <HomeOnboardingWalkthrough screenshotUrls={onboardingScreenshotUrls} />
      <HomeWorldBuilders artFor={artFor} />
      <HomePricing artFor={artFor} />
      <ClosingInvitation
        headingLines={[
          'Create your Collective.',
          // Secondary line — same family, ~72% of the primary size so
          // it clearly still belongs to the headline but sits quieter
          // beneath the creator-first primary line. ClosingInvitation
          // already wraps each entry in a `<span className="block">`,
          // so this inner span only styles size/tone.
          <span
            key="secondary"
            style={{
              fontSize: '0.72em',
              opacity: 0.85,
              marginTop: '0.35em',
              display: 'inline-block',
            }}
          >
            Or find one to join.
          </span>,
        ]}
        body="Every meaningful community begins with someone deciding to bring people together."
        primaryCta={{ label: 'Create a Collective', href: '/for-creators' }}
        secondaryCta={{ label: 'Explore Collectives', href: '/spaces' }}
        artUrl={artFor('homepage_closing_invitation')}
        buttonVariant="hero"
      />
    </SiteShell>
  )
}


// ═══════════════════════════════════════════════════════════════════
// SECTION OPENING — a small heading + intro block that lives inside
// a section (not on its own titled "chapter" page). No numerals, no
// separate background, no divider ornaments.
// ═══════════════════════════════════════════════════════════════════

function SectionOpening({
  title, body, className, titleColor, bodyColor,
}: {
  /** Accepts a plain string for simple headings, or a JSX node for
   *  headings that split colour across words (e.g. navy + a single
   *  teal accent word). Colour is applied per-span in the JSX. */
  title: React.ReactNode
  body?: string
  className?: string
  /** Default fallback colour applied via `color:` on the h2. When the
   *  title itself is a JSX node with per-span colours, its spans win
   *  by cascade. Kept for backwards compatibility with the previous
   *  single-colour headings. Defaults to navy (readable on white). */
  titleColor?: string
  /** Body copy colour override for sections rendered on a dark
   *  background. Defaults to the soft navy ink that reads on white. */
  bodyColor?: string
}) {
  return (
    <div className={`mx-auto max-w-[680px] text-center ${className ?? ''}`}>
      <h2
        className="font-serif leading-[1.1] text-navy-900"
        style={{
          fontSize: 'clamp(1.875rem, 4.4vw, 2.75rem)',
          letterSpacing: '-0.03em',
          color: titleColor ?? NAVY,
        }}
      >
        {title}
      </h2>
      {body && (
        <p
          className="mx-auto mt-5 max-w-[560px] text-[15.5px] italic leading-relaxed"
          style={{ color: bodyColor ?? INK_SOFT, fontFamily: 'Georgia, serif' }}
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

// Informational only — cards on this section do not link anywhere.
// Homepage visitors may not yet have member access; sending them into
// authenticated discovery surfaces from marketing is the wrong door.
interface DiscoveryEntry {
  artKey: string
  atmosphereSlug: string
  title: string
  body: string
  alt: string
}

const DISCOVERY_ENTRIES: DiscoveryEntry[] = [
  {
    artKey: 'homepage_explore_collectives',
    atmosphereSlug: 'homepage-explore-collectives',
    title: 'Explore Collectives',
    body: 'Find Collectives shaped around what you care about — the ideas, practices and journeys that match your interests, needs or direction.',
    alt: 'Fresh Collective — Explore Collectives',
  },
  {
    artKey: 'homepage_discover_places',
    atmosphereSlug: 'homepage-discover-places',
    title: 'Discover Places',
    body: 'See where Collectives are gathering across cities, regions and other real-world places.',
    alt: 'Fresh Collective — Discover Places',
  },
  {
    artKey: 'homepage_ways_to_connect',
    atmosphereSlug: 'homepage-ways-to-connect',
    title: 'Ways to Connect',
    body: 'People participate more when connection starts from something already shared — a Pathway you both walked, a Gathering you both attended, a Place you both know — rather than a blank community feed.',
    alt: 'Fresh Collective — Ways to Connect',
  },
]

function ExploreSection({ artFor }: { artFor: (key: string) => string | null }) {
  return (
    <section className="py-14 md:py-16" style={{ background: '#FFFFFF' }}>
      <Container>
        <SectionOpening
          title={
            <>
              There is a{' '}
              <span style={{ color: WARM_GOLD }}>whole world</span> for
              exploring.
            </>
          }
          body="On most platforms, everyone who finds you got there because you sent them. Fresh Collective is different: your Collective sits inside a wider world people can explore once they&rsquo;re here."
          className="mb-10 sm:mb-12"
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
    <article
      className="flex flex-col overflow-hidden rounded-2xl bg-white"
      style={{
        border: `1px solid ${HAIRLINE}`,
        boxShadow: '0 10px 28px rgba(12, 24, 38, 0.06), 0 1px 3px rgba(12, 24, 38, 0.04)',
      }}
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
            className="absolute inset-0 h-full w-full object-cover object-center"
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
      </div>
    </article>
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
    <section className="py-14 md:py-18" style={{ background: '#FFFFFF' }}>
      <Container>
        <SectionOpening
          title={
            <>
              Life inside a{' '}
              <span style={{ color: TEAL_DEEP }}>Collective.</span>
            </>
          }
          body="Your Collective can hold different experiences — Pathways for members to walk, Gatherings to attend, Conversations to continue and Resources to return to. Together, they give your people reasons to stay connected between the moments you lead."
          className="mb-12 md:mb-14"
        />

        <div className="mx-auto flex max-w-[1160px] flex-col gap-16 md:gap-20">
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
// CREATOR SECTION — opens the deep navy creator-building chapter.
//
// The navy background continues seamlessly into the onboarding
// showcase directly below, so the two sections read as one deliberate
// dark chapter about creating your Collective. The parchment island
// artwork sits prominently on the navy with an editorial drop shadow
// rather than the previous white-page border. The old four outcome
// blurbs beneath the artwork are removed — the onboarding walkthrough
// that immediately follows explains the setup journey in more concrete
// detail, so they were repeating themselves here.
// ═══════════════════════════════════════════════════════════════════

const OFF_WHITE_ON_NAVY = 'rgba(247, 244, 238, 0.80)'

function CreatorSection({ artUrl }: { artUrl: string | null }) {
  return (
    <section
      className="pt-14 pb-10 md:pt-16 md:pb-12"
      style={{ background: NAVY }}
    >
      <Container>
        <SectionOpening
          title="Build a place of your own."
          body="Every meaningful community begins with someone deciding to bring people together. Fresh Collective gives you the tools to start building a Collective people want to return to."
          className="mb-10 sm:mb-12"
          titleColor="#FFFFFF"
          bodyColor={OFF_WHITE_ON_NAVY}
        />

        {/* Anchor — managed artwork if present, otherwise a polished
            Creator Studio interface mockup. The card keeps a white
            surface (parchment / mockup live on light ground); shadow
            switched to an editorial dark-drop so the artwork lifts
            cleanly off the navy chapter. */}
        <div className="mx-auto max-w-[1080px]">
          <div
            className="relative w-full overflow-hidden rounded-3xl bg-white"
            style={{
              aspectRatio: artUrl ? '16 / 9' : undefined,
              boxShadow:
                '0 24px 60px rgba(0, 0, 0, 0.35), 0 6px 20px rgba(0, 0, 0, 0.18)',
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


