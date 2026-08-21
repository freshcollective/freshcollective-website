import Link from 'next/link'
import Container from '@/components/layout/Container'
import { PUBLIC_PLANS } from '@/lib/plans'

const NAVY = '#0C1826'
const INK_BODY = 'rgba(12, 24, 38, 0.80)'
const INK_SOFT = 'rgba(12, 24, 38, 0.66)'
const TEAL = '#38A09E'
const TEAL_DEEP = '#246B6A'
const HAIRLINE = 'rgba(12, 24, 38, 0.10)'

// Homepage pricing preview. Four cards mirror the /for-creators plans
// page — same imagery keys, same overall vocabulary — but with tighter
// homepage-appropriate copy. The section is a first impression; the
// full plan comparison lives on /for-creators via the CTA below the
// grid.
//
// Naming note: on the homepage the free plan is shortened from
// "Community Collective" (its full name on /for-creators) to just
// "Community", per this pass's copy direction. The internal slug and
// canonical display name in `plans.ts` are unchanged.
interface HomePlanCard {
  displayName: string
  tagline: string
  priceLabel: string
  positioning: string
  bullets: readonly string[]
  artworkKey: string
  artworkAlt: string
  emphasised?: boolean
  status?: 'available' | 'coming_soon'
}

const HOMEPAGE_PLAN_CARDS: readonly HomePlanCard[] = [
  {
    displayName: 'Community',
    tagline: 'A simple place to gather.',
    priceLabel: PUBLIC_PLANS.community.priceLabel,   // 'Free'
    positioning:
      'A simple place for a non-commercial community — free to run and easy to open.',
    bullets: [
      '1 Collective',
      'Up to 100 members',
      'Up to 5 Pathways',
    ],
    artworkKey: PUBLIC_PLANS.community.artworkKey,
    artworkAlt: PUBLIC_PLANS.community.artworkAlt,
  },
  {
    displayName: PUBLIC_PLANS.creator.displayName,   // 'Creator'
    tagline: PUBLIC_PLANS.creator.tagline,           // 'Build your business.'
    priceLabel: PUBLIC_PLANS.creator.priceLabel,     // '$19 / month'
    positioning: 'Build your business — paid memberships, sessions and resources.',
    bullets: [
      'One commercial Collective',
      'Up to 500 members',
      '8% on paid transactions',
    ],
    artworkKey: PUBLIC_PLANS.creator.artworkKey,
    artworkAlt: PUBLIC_PLANS.creator.artworkAlt,
    emphasised: true,
  },
  {
    displayName: PUBLIC_PLANS.pro.displayName,       // 'Creator Portfolio'
    tagline: 'Multiple Collectives.',
    priceLabel: PUBLIC_PLANS.pro.priceLabel,         // '$79 / month'
    positioning: 'Grow multiple Collectives under one Creator account.',
    bullets: [
      'Up to 5 Collectives',
      'Advanced options',
      '3% on paid transactions',
    ],
    artworkKey: PUBLIC_PLANS.pro.artworkKey,
    artworkAlt: PUBLIC_PLANS.pro.artworkAlt,
  },
  {
    // Ecosystem isn't in PUBLIC_PLANS (deliberately absent from any
    // signup / checkout flow), so its display metadata is defined
    // inline. Mirrors the /for-creators presentation.
    displayName: 'Ecosystem',
    tagline: 'Multiple creators and Collectives.',
    priceLabel: 'Coming soon',
    positioning:
      'For organisations building connected ecosystems of Collectives under shared care.',
    bullets: [
      'Multiple Creators',
      'Tailored implementation',
      'Enterprise support',
    ],
    artworkKey: 'for_creators_organisation',
    artworkAlt:
      'An Ecosystem on Fresh Collective — a wider connected landscape of interlinked Collectives',
    status: 'coming_soon',
  },
]

interface Props {
  artFor: (key: string) => string | null
}

export default function HomePricing({ artFor }: Props) {
  return (
    <section className="pt-14 pb-6 md:pt-20 md:pb-10" style={{ background: '#FFFFFF' }}>
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
            Start where <span style={{ color: TEAL_DEEP }}>you</span> are.
          </h2>
        </div>

        <div className="mx-auto mt-12 grid max-w-[1200px] gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {HOMEPAGE_PLAN_CARDS.map((plan) => (
            <PlanCard
              key={plan.displayName}
              plan={plan}
              artUrl={artFor(plan.artworkKey)}
            />
          ))}
        </div>

        <div className="mt-10 text-center">
          <Link
            href="/for-creators#plans"
            className="inline-flex items-center gap-2 text-[14px] font-semibold transition-opacity hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400/40 focus-visible:ring-offset-2 rounded"
            style={{ color: TEAL_DEEP }}
          >
            Discover more about Collective plans <span aria-hidden="true">→</span>
          </Link>
        </div>
      </Container>
    </section>
  )
}

function PlanCard({
  plan,
  artUrl,
}: {
  plan: HomePlanCard
  artUrl: string | null
}) {
  const isComingSoon = plan.status === 'coming_soon'
  const isEmphasised = !!plan.emphasised
  return (
    <article
      className={`relative flex h-full flex-col overflow-hidden rounded-2xl bg-white transition-shadow ${
        isEmphasised ? 'md:-translate-y-2' : ''
      }`}
      style={{
        border: isEmphasised
          ? `2px solid ${TEAL}`
          : `1px solid ${HAIRLINE}`,
        boxShadow: isEmphasised
          ? '0 22px 52px rgba(36, 107, 106, 0.20), 0 3px 10px rgba(12, 24, 38, 0.06)'
          : '0 1px 3px rgba(12, 24, 38, 0.04)',
      }}
    >
      {/* Plan artwork — same key + alt as the /for-creators page so
          the visual language matches. */}
      <div
        className="relative w-full overflow-hidden"
        style={{ aspectRatio: '5 / 4', background: '#F4F7F6' }}
      >
        {artUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={artUrl}
            alt={plan.artworkAlt}
            className="absolute inset-0 h-full w-full object-cover object-center"
          />
        ) : (
          <div
            aria-hidden="true"
            className="absolute inset-0"
            style={{
              background:
                'linear-gradient(160deg, #F4F7F6 0%, #EAF0EE 100%)',
            }}
          />
        )}
        {isComingSoon && (
          <span
            className="absolute left-4 top-4 rounded-full px-3 py-1 text-[10.5px] font-semibold uppercase"
            style={{
              background: 'rgba(255, 255, 255, 0.95)',
              color: INK_BODY,
              letterSpacing: '0.14em',
            }}
          >
            Coming soon
          </span>
        )}
      </div>

      <div className="flex flex-1 flex-col p-6">
        <h3
          className="font-serif text-[20px] leading-tight"
          style={{
            color: isEmphasised ? TEAL_DEEP : NAVY,
            letterSpacing: '-0.01em',
          }}
        >
          {plan.displayName}
        </h3>
        <p
          className="mt-1 text-[13px] italic"
          style={{ color: TEAL, fontFamily: 'Georgia, serif' }}
        >
          {plan.tagline}
        </p>

        <p
          className="mt-4 font-serif text-[22px] leading-none"
          style={{ color: NAVY, letterSpacing: '-0.02em' }}
        >
          {plan.priceLabel}
        </p>

        <p
          className="mt-4 text-[13.5px] leading-relaxed"
          style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
        >
          {plan.positioning}
        </p>

        <ul
          className="mt-4 flex flex-col gap-1.5 text-[13px] leading-relaxed"
          style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
        >
          {plan.bullets.map((b) => (
            <li key={b} className="flex gap-2">
              <span aria-hidden="true" style={{ color: TEAL }}>
                •
              </span>
              <span>{b}</span>
            </li>
          ))}
        </ul>
      </div>
    </article>
  )
}
