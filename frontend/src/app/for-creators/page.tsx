import type { Metadata } from 'next'
import Link from 'next/link'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import ArtworkFeatureComposition from '@/components/marketing/ArtworkFeatureComposition'
import ClosingInvitation from '@/components/marketing/ClosingInvitation'
import {
  buildPlatformArtLookup,
  getPublicPlatformArtwork,
  type PublicPlatformArtwork,
} from '@/lib/serverApi'
import {
  PROCESSING_COVERED_LINE,
  PUBLIC_PLANS,
  commissionBullet,
} from '@/lib/plans'
import { CONTACT_INFO_EMAIL } from '@/lib/contact'
import {
  CREATOR_FAQ,
  FEE_ROWS,
  FEE_TABLE_HEADINGS,
  creatorFaqJsonLd,
} from '@/lib/creatorFaq'

/**
 * /for-creators — editorial companion to the homepage.
 *
 * Structure: Hero → Journey → Plans → World Builders → Closing → FAQ.
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


export default async function ForCreatorsPage() {
  const artwork = await getPublicPlatformArtwork().catch(() => [] as PublicPlatformArtwork[])
  const artFor = buildPlatformArtLookup(artwork)

  return (
    <SiteShell>
      <Hero artUrl={artFor('homepage_creator_studio')} />
      <Journey />
      <PlansSection artFor={artFor} />
      <WorldBuildersSection artUrl={artFor('for_creators_world_builders')} />
      <ClosingInvitation
        headingLines={['Ready to build your Collective?']}
        body="Bring your ideas, experiences and community together in one place—and create something people genuinely want to return to."
        primaryCta={{ label: 'Choose your plan', href: '/for-creators#plans' }}
      />
      {/* After the closing CTA on purpose. The CTA completes the
          creator journey; the FAQ is reference material for somebody
          who wants to keep reading, and putting it before the CTA made
          the page ask its question and then keep talking. */}
      <FaqSection />
      <AboutStoryLink />
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
    name: PUBLIC_PLANS.community.displayName,
    tagline: 'A first place to gather.',
    body: 'A welcoming home for the gatherings that do not need to become a business — neighbourhood groups, clubs, volunteer teams, hobby circles and shared-interest communities. A beautiful place to come together, freely and without pressure.',
    facts: [
      'Free',
      'One Collective',
      'Up to 100 members',
      'Up to 5 Pathways',
      'For non-commercial gatherings',
    ],
    cta: { label: 'Start for free', href: PUBLIC_PLANS.community.ctaHref },
    artKey: 'for_creators_community',
    atmosphereSlug: 'for-creators-community',
    artAlt: 'A Community Collective on Fresh Collective — a shared table, a small local gathering',
  },
  {
    name: PUBLIC_PLANS.creator.displayName,
    tagline: 'Build your business.',
    body: 'For creators building a livelihood around what they teach, host or share. Offer paid Pathways, paid Gatherings and paid Collective Memberships — everything you need to grow a sustainable creative business from a single considered home.',
    facts: [
      PUBLIC_PLANS.creator.priceLabel,
      'One Collective, up to 500 members',
      'Paid Pathways, Gatherings and Collective Memberships',
      'Unlimited Pathways',
      commissionBullet(PUBLIC_PLANS.creator)!,
      PROCESSING_COVERED_LINE,
    ],
    cta: { label: 'Choose Creator', href: PUBLIC_PLANS.creator.ctaHref },
    artKey: 'for_creators_creator',
    atmosphereSlug: 'for-creators-creator',
    artAlt: 'A single creator at work — a studio, considered craft',
  },
  {
    name: PUBLIC_PLANS.pro.displayName,
    tagline: 'Multiple Collectives. One Creator.',
    body: 'Grow multiple Collectives under one Creator account, each with its own identity, members, Pathways, Gatherings and Resources. Perfect for creators with several offerings, brands or communities they want to tend together.',
    facts: [
      PUBLIC_PLANS.pro.priceLabel,
      'Up to 5 Collectives',
      'Commercial use',
      'Advanced analytics',
      'Multiple workspaces per Collective',
      commissionBullet(PUBLIC_PLANS.pro)!,
      PROCESSING_COVERED_LINE,
    ],
    cta: { label: 'Choose Creator Portfolio', href: PUBLIC_PLANS.pro.ctaHref },
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
            <p
              className="mt-6 max-w-[460px] text-[14px] italic leading-relaxed"
              style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
            >
              Included automatically with every Creator plan.
            </p>
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


// ═══════════════════════════════════════════════════════════════════
// FAQ — the practical questions, answered plainly.
//
// Native <details>/<summary> rather than a scripted accordion. It is
// keyboard accessible, announced correctly by screen readers and works
// with JavaScript disabled, which no hand-rolled disclosure gets for
// free. Each question is independently collapsible: a one-at-a-time
// accordion would mean either JavaScript or ``name``, and closing the
// answer somebody is halfway through reading to open another is a
// worse trade than two answers being open at once.
//
// Copy and structured data both come from ``lib/creatorFaq`` so the
// FAQPage JSON-LD cannot drift from the visible answers.
// ═══════════════════════════════════════════════════════════════════

function FaqSection() {
  return (
    <section id="faq" className="py-20 sm:py-24" style={{ background: '#FFFFFF' }}>
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
            Questions creators ask
          </h2>
          <p
            className="mx-auto mt-5 max-w-[600px] text-[15.5px] italic leading-relaxed"
            style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
          >
            The practical bits, answered plainly.
          </p>
        </div>

        <div className="mx-auto mt-12 max-w-[760px] sm:mt-14">
          {CREATOR_FAQ.map((item) => (
            <details
              key={item.id}
              id={item.id}
              className="group border-b"
              style={{ borderColor: 'rgba(12, 24, 38, 0.10)' }}
            >
              <summary
                className="flex cursor-pointer list-none items-start justify-between gap-5 py-5 text-left [&::-webkit-details-marker]:hidden"
              >
                <span
                  className="font-serif text-[17px] leading-snug sm:text-[18.5px]"
                  style={{ color: NAVY }}
                >
                  {item.question}
                </span>
                {/* Rotates on open via Tailwind's group-open variant —
                    no state, no JavaScript. aria-hidden because the
                    summary element already announces its own expanded
                    state. */}
                <svg
                  aria-hidden="true"
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  className="mt-1 shrink-0 transition-transform duration-200 group-open:rotate-180"
                  style={{ color: TEAL_DEEP }}
                >
                  <path
                    d="M6 9l6 6 6-6"
                    stroke="currentColor"
                    strokeWidth="1.75"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </summary>

              <div className="pb-6">
                {item.paragraphs.map((text, i) => (
                  <div key={text.slice(0, 24)}>
                    <p
                      className={`${i === 0 ? '' : 'mt-4 '}max-w-[640px] text-[15.5px] leading-relaxed`}
                      style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
                    >
                      {text}
                    </p>
                    {item.feeTable && i === 0 && <FeeTable />}
                  </div>
                ))}
              </div>
            </details>
          ))}

          <p
            className="mt-8 text-[14.5px] leading-relaxed"
            style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
          >
            Still wondering about something? Email{' '}
            <a
              href={`mailto:${CONTACT_INFO_EMAIL}`}
              className="underline decoration-1 underline-offset-2 transition-colors"
              style={{ color: TEAL_DEEP }}
            >
              {CONTACT_INFO_EMAIL}
            </a>
            , or read the full details in the{' '}
            <Link
              href="/world-guide/creator-agreement"
              className="underline decoration-1 underline-offset-2 transition-colors"
              style={{ color: TEAL_DEEP }}
            >
              Creator Agreement
            </Link>{' '}
            and{' '}
            <Link
              href="/world-guide/payment-refund-and-cancellation-policy"
              className="underline decoration-1 underline-offset-2 transition-colors"
              style={{ color: TEAL_DEEP }}
            >
              Payment, Refund and Cancellation Policy
            </Link>
            .
          </p>
        </div>
      </Container>

      {/* FAQPage structured data, serialised from the same copy rendered
          above. Inside the section rather than the metadata export so it
          sits beside what it describes. */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(creatorFaqJsonLd()) }}
      />
    </section>
  )
}

/**
 * The worked fee examples.
 *
 * Scrolls inside its own container rather than stacking into
 * definition rows: three money columns compared across two plans is a
 * comparison, and a stacked version repeats the headings twice and
 * makes the reader hold the numbers in their head. ``min-w`` is what
 * forces the scroll to happen here instead of widening the page —
 * without it the table squashes and the page itself scrolls, which is
 * the failure this is written to avoid.
 */
function FeeTable() {
  return (
    <div className="mt-5 max-w-[640px]">
      {/* Phone only. The table scrolls inside its own box, which is the
          right behaviour and an invisible one — the third column sits
          just past the right edge with nothing to say it is there.
          ``sm:hidden`` because on a wider screen all three columns are
          already visible and the hint would be telling the reader to do
          something pointless.

          aria-hidden: a screen-reader user is not swiping, and the
          table is reachable by keyboard and by the usual table
          navigation regardless. */}
      <p
        aria-hidden="true"
        className="mb-2 text-[12.5px] italic sm:hidden"
        style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
      >
        Swipe to compare plans &rarr;
      </p>
      <div
        className="overflow-x-auto rounded-xl border"
        style={{ borderColor: 'rgba(12, 24, 38, 0.10)' }}
      >
        <table className="w-full min-w-[460px] border-collapse text-left">
          <thead>
            <tr style={{ background: 'rgba(12, 24, 38, 0.03)' }}>
              {[FEE_TABLE_HEADINGS.sale, FEE_TABLE_HEADINGS.creator, FEE_TABLE_HEADINGS.portfolio].map((h) => (
                <th
                  key={h}
                  scope="col"
                  className="px-4 py-3 text-[12.5px] font-semibold leading-snug"
                  style={{ color: NAVY }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {FEE_ROWS.map((row) => (
              <tr
                key={row.sale}
                className="border-t"
                style={{ borderColor: 'rgba(12, 24, 38, 0.08)' }}
              >
                <th
                  scope="row"
                  className="px-4 py-3 text-[13.5px] font-normal"
                  style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
                >
                  {row.sale}
                </th>
                <td className="px-4 py-3 text-[13.5px]" style={{ color: NAVY }}>
                  {row.creator}
                </td>
                <td className="px-4 py-3 text-[13.5px]" style={{ color: NAVY }}>
                  {row.portfolio}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}


// ═══════════════════════════════════════════════════════════════════
// ABOUT LINK — one quiet line to the story behind the platform
// ═══════════════════════════════════════════════════════════════════

/**
 * A single text link to ``/about``.
 *
 * Placed after the FAQ, at the very end of the page, for two reasons.
 * It is the last thing a reader meets, so it cannot interrupt the
 * creator journey — the hero, the plans, the World Builders section
 * and the closing CTA all run their course first. And it answers the
 * question somebody naturally has once they have finished reading
 * about the plans and the fees: who built this, and why. Nothing
 * above it changes.
 *
 * Deliberately a line of text rather than a button. There is already
 * one primary action on this page and it is "Choose your plan"; a
 * second button would compete with it.
 */
function AboutStoryLink() {
  return (
    <Container className="pb-20 md:pb-28">
      <div className="mx-auto max-w-2xl text-center">
        <Link
          href="/about"
          className="text-[14.5px] underline decoration-1 underline-offset-4 transition-colors hover:opacity-80"
          style={{ color: TEAL_DEEP, textDecorationColor: 'rgba(36,107,106,0.35)' }}
        >
          Discover why Fresh Collective exists →
        </Link>
      </div>
    </Container>
  )
}
