import type { Metadata } from 'next'
import Link from 'next/link'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import ArtworkFeatureComposition from '@/components/marketing/ArtworkFeatureComposition'
import ClosingInvitation from '@/components/marketing/ClosingInvitation'
import { resolveMediaUrl } from '@/lib/api'
import { getPublicPlatformArtwork, type PublicPlatformArtwork } from '@/lib/serverApi'

/**
 * /for-creators — editorial companion to the homepage.
 *
 * Structure: Hero → Journey → Plans → World Builders → Closing.
 * Every row is an editorial spread: artwork on one side, quiet framing
 * copy on the other. No pricing-table decoration, no eyebrow labels —
 * hierarchy is carried by typography, spacing and composition alone.
 *
 * Artwork is served by the managed Platform Artwork registry
 * (see backend/app/admin/platform_artwork.py, keys `for_creators_*`).
 * Missing artwork falls back to atmospheric gradients so a fresh
 * install still reads considered.
 */

export const metadata: Metadata = {
  title: 'For Creators — Fresh Collective',
  description:
    'Build a Collective people want to return to. Four creator accounts, from a first non-commercial community to a landscape of many places.',
  openGraph: {
    title: 'For Creators — Fresh Collective',
    description:
      'Four creator accounts, from a first non-commercial community to a landscape of many places.',
    type: 'website',
  },
}


// ─── Design tokens (mirror the homepage) ─────────────────────────────
const TEAL = '#38A09E'
const TEAL_DEEP = '#246B6A'
const NAVY = '#0C1826'
const INK_BODY = 'rgba(12, 24, 38, 0.80)'
const INK_SOFT = 'rgba(12, 24, 38, 0.66)'


function buildArtLookup(items: PublicPlatformArtwork[]): (key: string) => string | null {
  const byKey = new Map(items.map((a) => [a.key, a]))
  return (key: string) => {
    const item = byKey.get(key)
    if (!item) return null
    return resolveMediaUrl(item.image_url ?? item.thumbnail_url ?? undefined) ?? null
  }
}


export default async function ForCreatorsPage() {
  const artwork = await getPublicPlatformArtwork().catch(() => [] as PublicPlatformArtwork[])
  const artFor = buildArtLookup(artwork)

  return (
    <SiteShell>
      <Hero artUrl={artFor('homepage_creator_studio')} />
      <Journey />
      <PlansSection artFor={artFor} />
      <WorldBuildersSection artUrl={artFor('for_creators_world_builders')} />
      <ClosingInvitation
        headingLines={['Ready to build your Collective?']}
        body="Bring your ideas, experiences and community together in one place—and create something people genuinely want to return to."
        primaryCta={{ label: 'Start building', href: '/signup?plan=creator' }}
      />
    </SiteShell>
  )
}


// ═══════════════════════════════════════════════════════════════════
// HERO — magazine spread. Artwork opens the page, heading follows.
// No eyebrow label. Hero CTA anchors to the plans section so a
// visitor never has to hunt for their first move.
// ═══════════════════════════════════════════════════════════════════

function Hero({ artUrl }: { artUrl: string | null }) {
  return (
    <section className="pt-14 pb-16 sm:pt-20 sm:pb-20" style={{ background: '#FFFFFF' }}>
      <Container>
        {artUrl && (
          <div className="mx-auto max-w-[1080px]">
            <div
              className="relative w-full overflow-hidden rounded-3xl bg-white"
              style={{
                aspectRatio: '16 / 9',
                boxShadow:
                  '0 24px 60px rgba(12, 24, 38, 0.14),' +
                  '0 6px 20px rgba(12, 24, 38, 0.08)',
              }}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={artUrl}
                alt="Fresh Collective — Creator Studio"
                className="absolute inset-0 h-full w-full object-cover object-center"
              />
            </div>
          </div>
        )}

        <div className="mx-auto mt-14 max-w-[860px] text-center sm:mt-16">
          <h1
            className="mx-auto font-serif leading-[1.08]"
            style={{
              fontSize: 'clamp(2.125rem, 5.4vw, 3.75rem)',
              letterSpacing: '-0.03em',
              color: NAVY,
              maxWidth: '780px',
            }}
          >
            <span className="block">Create a Collective</span>
            <span className="block">people want to return to.</span>
          </h1>
          <p
            className="mx-auto mt-8 max-w-[620px] text-[16px] italic leading-relaxed"
            style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
          >
            Fresh Collective gives creators a considered place to bring
            people together — to teach, to gather, to grow, and to make
            something that lasts. Choose the plan that matches where
            you are today; grow into more as your Collective does.
          </p>
          <div className="mt-10 flex justify-center">
            <Link
              href="#plans"
              className="inline-flex items-center justify-center rounded-full px-7 py-3 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
              style={{
                background: `linear-gradient(135deg, ${TEAL} 0%, #55B8B6 100%)`,
                letterSpacing: '0.04em',
                boxShadow: '0 6px 24px rgba(56, 160, 158, 0.30)',
              }}
            >
              Choose your plan
            </Link>
          </div>
        </div>
      </Container>
    </section>
  )
}


// ═══════════════════════════════════════════════════════════════════
// JOURNEY — three editorial blocks with large serif numerals.
// ═══════════════════════════════════════════════════════════════════

interface JourneyStep {
  numeral: string
  title: string
  body: string
}

const JOURNEY_STEPS: JourneyStep[] = [
  {
    numeral: 'One',
    title: 'Shape the feeling.',
    body: 'Choose the atmosphere, colours, voice and experience you want people to have when they arrive.',
  },
  {
    numeral: 'Two',
    title: 'Build what lives inside.',
    body: 'Create Pathways, Gatherings, Conversations and Resources that bring your Collective to life.',
  },
  {
    numeral: 'Three',
    title: 'Welcome people in.',
    body: 'Invite members, nurture relationships and create a community people want to return to.',
  },
]

function Journey() {
  return (
    <section className="py-20 sm:py-24" style={{ background: '#FFFFFF' }}>
      <Container>
        <div className="mx-auto max-w-[680px] text-center">
          <h2
            className="font-serif leading-[1.1]"
            style={{
              fontSize: 'clamp(1.875rem, 4.4vw, 2.75rem)',
              letterSpacing: '-0.03em',
              color: NAVY,
            }}
          >
            How to start a Collective.
          </h2>
        </div>

        <div className="mx-auto mt-14 grid max-w-[1080px] gap-12 sm:mt-16 md:grid-cols-3 md:gap-14">
          {JOURNEY_STEPS.map((step) => (
            <div key={step.numeral} className="text-center md:text-left">
              <p
                className="font-serif italic leading-none"
                style={{
                  fontSize: 'clamp(2.25rem, 4vw, 2.75rem)',
                  color: TEAL,
                  letterSpacing: '-0.02em',
                }}
              >
                {step.numeral}.
              </p>
              <h3
                className="mt-5 font-serif leading-tight"
                style={{
                  fontSize: 'clamp(1.375rem, 2.6vw, 1.625rem)',
                  color: NAVY,
                  letterSpacing: '-0.01em',
                }}
              >
                {step.title}
              </h3>
              <p
                className="mt-3 text-[15px] leading-relaxed"
                style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
              >
                {step.body}
              </p>
            </div>
          ))}
        </div>
      </Container>
    </section>
  )
}


// ═══════════════════════════════════════════════════════════════════
// PLANS — four editorial rows.
//
// Plan name is the primary heading; the atmospheric line beneath is
// the secondary heading. No teal eyebrow labels — hierarchy comes
// from typography and spacing alone. Every row ends with its own CTA.
// ═══════════════════════════════════════════════════════════════════

const PLANS_GRID_COPY_LEFT  = 'md:grid-cols-[minmax(0,0.9fr)_minmax(0,1.15fr)]'
const PLANS_GRID_COPY_RIGHT = 'md:grid-cols-[minmax(0,1.15fr)_minmax(0,0.9fr)]'

interface Plan {
  name: string
  tagline: string
  body: string
  facts: string[]
  cta: { label: string; href: string }
  artKey: string
  atmosphereSlug: string
  artAlt: string
  /** Optional quiet badge rendered beside the plan name (e.g. "Coming soon"). */
  badge?: string
}

const PLANS: Plan[] = [
  {
    name: 'Community Collective',
    tagline: 'A first place to gather.',
    body: 'A welcoming home for the gatherings that do not need to become a business — neighbourhood groups, clubs, volunteer teams, hobby circles and shared-interest communities. A beautiful place to come together, freely and without pressure.',
    facts: [
      'Free',
      'One approved Collective',
      'Up to 100 members',
      'Up to 5 Pathways',
      'For non-commercial gatherings',
    ],
    cta: { label: 'Start for free', href: '/signup?plan=community' },
    artKey: 'for_creators_community',
    atmosphereSlug: 'for-creators-community',
    artAlt: 'A Community Collective on Fresh Collective — a shared table, a small local gathering',
  },
  {
    name: 'Creator',
    tagline: 'Build your business.',
    body: 'For creators building a livelihood around what they teach, host or share. Offer paid Pathways, paid Gatherings and paid Collective Memberships — everything you need to grow a sustainable creative business from a single considered home.',
    facts: [
      '$19 / month',
      'One Collective, up to 500 members',
      'Paid Pathways, Gatherings and Collective Memberships',
      'Unlimited Pathways',
      '8% platform fee on paid offers',
    ],
    cta: { label: 'Choose Creator', href: '/signup?plan=creator' },
    artKey: 'for_creators_creator',
    atmosphereSlug: 'for-creators-creator',
    artAlt: 'A single creator at work — a studio, considered craft',
  },
  {
    name: 'Creator Portfolio',
    tagline: 'Multiple Collectives. One Creator.',
    body: 'Grow multiple Collectives under one Creator account, each with its own identity, members, Pathways, Gatherings and Resources. Perfect for creators with several offerings, brands or communities they want to tend together.',
    facts: [
      '$79 / month',
      'Up to 5 Collectives',
      'Commercial use',
      'Advanced analytics',
      'Multiple workspaces per Collective',
      '3% platform fee on paid offers',
    ],
    cta: { label: 'Choose Creator Portfolio', href: '/signup?plan=pro' },
    artKey: 'for_creators_pro',
    atmosphereSlug: 'for-creators-pro',
    artAlt: 'Several Collectives thriving under one Creator — a connected landscape',
  },
  {
    name: 'Ecosystem',
    tagline: 'Many Creators. Many Collectives.',
    body: 'For organisations building connected ecosystems of Collectives. Many Creators can build alongside one another under shared care, while each Collective keeps its own identity, members and experiences.',
    facts: [
      'Talk to us',
      'Custom capacity across many Collectives',
      'Many Creators building in one connected world',
      'Tailored onboarding and ongoing support',
    ],
    cta: { label: 'Join the waitlist', href: '/ecosystem-interest' },
    artKey: 'for_creators_organisation',
    atmosphereSlug: 'for-creators-organisation',
    artAlt: 'A wider connected landscape — an ecosystem of interlinked Collectives',
    badge: 'Coming soon',
  },
]

function PlansSection({ artFor }: { artFor: (key: string) => string | null }) {
  return (
    <section id="plans" className="py-20 sm:py-28" style={{ background: '#FFFFFF' }}>
      <Container>
        <div className="mx-auto max-w-[720px] text-center">
          <h2
            className="font-serif leading-[1.1]"
            style={{
              fontSize: 'clamp(1.875rem, 4.4vw, 2.75rem)',
              letterSpacing: '-0.03em',
              color: NAVY,
            }}
          >
            Choose the plan that matches what you&rsquo;re building.
          </h2>
          <p
            className="mx-auto mt-5 max-w-[600px] text-[15.5px] italic leading-relaxed"
            style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
          >
            Every Creator account includes your own Creator Studio — a
            considered place to shape, tend and grow your Collectives
            over time. The plan you choose simply reflects how many
            Collectives you&rsquo;ll build, and whether you&rsquo;re
            offering your work freely or as a livelihood.
          </p>
        </div>

        <div className="mx-auto mt-16 flex max-w-[1160px] flex-col gap-20 sm:mt-20 md:gap-28">
          {PLANS.map((plan, i) => (
            <PlanRow
              key={plan.artKey}
              plan={plan}
              flipped={i % 2 === 1}
              artUrl={artFor(plan.artKey)}
            />
          ))}
        </div>
      </Container>
    </section>
  )
}

function PlanRow({
  plan, flipped, artUrl,
}: {
  plan: Plan
  flipped: boolean
  artUrl: string | null
}) {
  const copy = (
    <div className="flex flex-col justify-center">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <h3
          className="font-serif leading-[1.06]"
          style={{
            fontSize: 'clamp(1.875rem, 3.6vw, 2.625rem)',
            letterSpacing: '-0.025em',
            color: NAVY,
          }}
        >
          {plan.name}
        </h3>
        {plan.badge && (
          <span
            className="inline-flex items-center rounded-full border px-3 py-1"
            style={{
              borderColor: 'rgba(56, 160, 158, 0.32)',
              color: TEAL_DEEP,
              fontSize: '11px',
              letterSpacing: '0.16em',
              textTransform: 'uppercase',
              fontWeight: 600,
              fontFamily:
                'ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
            }}
          >
            {plan.badge}
          </span>
        )}
      </div>
      <p
        className="mt-3 font-serif italic leading-snug"
        style={{
          fontSize: 'clamp(1.125rem, 2vw, 1.375rem)',
          color: TEAL_DEEP,
          letterSpacing: '-0.01em',
        }}
      >
        {plan.tagline}
      </p>
      <p
        className="mt-6 max-w-[460px] text-[15.5px] leading-relaxed"
        style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
      >
        {plan.body}
      </p>
      <ul className="mt-6 flex max-w-[460px] flex-col gap-1.5">
        {plan.facts.map((fact) => (
          <li
            key={fact}
            className="text-[14px] leading-relaxed"
            style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
          >
            <span aria-hidden="true" style={{ color: TEAL_DEEP }}>·</span>{' '}
            {fact}
          </li>
        ))}
      </ul>
      <div className="mt-8">
        <Link
          href={plan.cta.href}
          className="inline-flex items-center rounded-full px-6 py-3 text-[13.5px] font-semibold text-white transition-opacity hover:opacity-90"
          style={{
            background: `linear-gradient(135deg, ${TEAL} 0%, #55B8B6 100%)`,
            letterSpacing: '0.04em',
            boxShadow: '0 6px 20px rgba(56, 160, 158, 0.28)',
          }}
        >
          {plan.cta.label} →
        </Link>
      </div>
    </div>
  )

  const artwork = (
    <ArtworkFeatureComposition
      artworkUrl={artUrl}
      atmosphereSlug={plan.atmosphereSlug}
      artworkAlt={plan.artAlt}
      aspectRatio="4 / 3"
    />
  )

  const gridClass = flipped ? PLANS_GRID_COPY_RIGHT : PLANS_GRID_COPY_LEFT

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
// WORLD BUILDERS — editorial spread introducing the shared creator
// community every account joins. Bridges the plans section into the
// closing invitation.
// ═══════════════════════════════════════════════════════════════════

function WorldBuildersSection({ artUrl }: { artUrl: string | null }) {
  return (
    <section className="py-20 sm:py-24" style={{ background: '#FFFFFF' }}>
      <Container>
        <div className={`mx-auto grid max-w-[1160px] grid-cols-1 items-center gap-12 md:gap-20 ${PLANS_GRID_COPY_LEFT}`}>
          <div className="flex flex-col justify-center">
            <h2
              className="font-serif leading-[1.08]"
              style={{
                fontSize: 'clamp(1.75rem, 3.4vw, 2.5rem)',
                letterSpacing: '-0.02em',
                color: NAVY,
              }}
            >
              World Builders Collective
            </h2>
            <p
              className="mt-6 max-w-[460px] text-[15.5px] leading-relaxed"
              style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
            >
              Every Fresh Collective Creator receives free, automatic
              access to the World Builders Collective — a shared place
              for tutorials, templates, practical guidance and support
              as you build.
            </p>
            <p
              className="mt-4 max-w-[460px] text-[15.5px] leading-relaxed"
              style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
            >
              Learn how Fresh Collective works, ask questions, share
              ideas and connect with other creators building alongside
              you.
            </p>
            <div className="mt-8">
              <Link
                href="/world-builders"
                className="text-[14px] font-semibold transition-opacity hover:opacity-80"
                style={{ color: TEAL_DEEP }}
              >
                Explore World Builders →
              </Link>
            </div>
          </div>
          <ArtworkFeatureComposition
            artworkUrl={artUrl}
            atmosphereSlug="for-creators-world-builders"
            artworkAlt="Creators learning together inside the World Builders Collective"
            aspectRatio="4 / 3"
          />
        </div>
      </Container>
    </section>
  )
}
