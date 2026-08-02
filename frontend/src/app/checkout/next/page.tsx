import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import { getPublicSpaces } from '@/lib/serverApi'
import { getPublicPlan, type PublicPlanDisplay } from '@/lib/plans'
import type { PublicSpaceCard } from '@/types/platform'

/**
 * /checkout/next — honest holding screen for the account-creation and
 * purchase prototype.
 *
 * PROTOTYPE ONLY. This page never claims that a purchase, plan
 * activation, entitlement, enrolment or Collective access has
 * happened. Every branch spells out what the live flow will do once
 * Stripe and entitlement activation are wired, and what this prototype
 * has not done.
 *
 * Named `/checkout/next` (not `/checkout/complete` or `/signup/success`)
 * to keep the URL itself honest during the prototype phase. When
 * Stripe and entitlement activation land, this route can be renamed
 * to `/checkout/complete` and its copy tightened to describe real
 * outcomes.
 *
 * Query params:
 *   flow=creator          — logged-out visitor picked a Creator plan
 *   flow=upgrade          — logged-in visitor picked a Creator plan
 *   flow=member           — logged-out visitor is joining a paid Collective
 *   flow=member-upgrade   — logged-in visitor is joining a paid Collective
 *   plan=<slug>           — required for creator / upgrade
 *   collective=<slug>     — required for member / member-upgrade
 *   preview=true          — required in every prototype URL
 */

export const metadata: Metadata = {
  title: 'Next step — Fresh Collective',
  robots: { index: false, follow: false },
}

const NAVY = '#0C1826'
const TEAL = '#38A09E'
const TEAL_DEEP = '#246B6A'
const INK_BODY = 'rgba(12, 24, 38, 0.80)'
const INK_SOFT = 'rgba(12, 24, 38, 0.66)'

type Flow = 'creator' | 'upgrade' | 'member' | 'member-upgrade'

const KNOWN_FLOWS: readonly Flow[] = ['creator', 'upgrade', 'member', 'member-upgrade']

function isFlow(v: string | undefined): v is Flow {
  return typeof v === 'string' && (KNOWN_FLOWS as readonly string[]).includes(v)
}

interface Screen {
  eyebrow: string
  heading: string
  willHappen: string
  prototypeReality: string
  primary: { label: string; href: string }
  secondary?: { label: string; href: string }
}

export default async function CheckoutNextPage({
  searchParams,
}: {
  searchParams: Promise<{
    flow?: string
    plan?: string
    collective?: string
    preview?: string
  }>
}) {
  const { flow: flowParam, plan: planParam, collective: collectiveSlug } = await searchParams

  if (!isFlow(flowParam)) notFound()

  const screen = await buildScreen(flowParam, planParam, collectiveSlug)
  if (!screen) notFound()

  return (
    <SiteShell>
      <section className="py-20 sm:py-24" style={{ background: '#FFFFFF' }}>
        <Container>
          <div className="mx-auto max-w-[720px]">
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
              Prototype preview
            </span>

            <p
              className="mt-6 text-[13px] uppercase"
              style={{ color: TEAL_DEEP, letterSpacing: '0.14em' }}
            >
              {screen.eyebrow}
            </p>
            <h1
              className="mt-3 font-serif leading-[1.06]"
              style={{
                fontSize: 'clamp(2rem, 4.4vw, 2.75rem)',
                letterSpacing: '-0.025em',
                color: NAVY,
              }}
            >
              {screen.heading}
            </h1>

            <div className="mt-8 grid gap-6 sm:grid-cols-2">
              <HoldingBlock
                title="What will happen in the live flow"
                body={screen.willHappen}
                tone="future"
              />
              <HoldingBlock
                title="What is happening in this prototype"
                body={screen.prototypeReality}
                tone="now"
              />
            </div>

            <div className="mt-10 flex flex-col items-start gap-4 sm:flex-row sm:items-center">
              <Link
                href={screen.primary.href}
                className="inline-flex items-center rounded-full px-7 py-3 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
                style={{
                  background: `linear-gradient(135deg, ${TEAL} 0%, #55B8B6 100%)`,
                  letterSpacing: '0.04em',
                  boxShadow: '0 6px 24px rgba(56, 160, 158, 0.30)',
                }}
              >
                {screen.primary.label}
              </Link>
              {screen.secondary && (
                <Link
                  href={screen.secondary.href}
                  className="text-[14px] font-semibold transition-opacity hover:opacity-80"
                  style={{ color: TEAL_DEEP }}
                >
                  {screen.secondary.label}
                </Link>
              )}
            </div>
          </div>
        </Container>
      </section>
    </SiteShell>
  )
}

// ---------------------------------------------------------------------
// Per-flow copy
// ---------------------------------------------------------------------

async function buildScreen(
  flow: Flow,
  planParam: string | undefined,
  collectiveSlug: string | undefined,
): Promise<Screen | null> {
  if (flow === 'creator' || flow === 'upgrade') {
    const plan = getPublicPlan(planParam)
    if (!plan) return null
    return flow === 'creator' ? creatorScreen(plan) : upgradeScreen(plan)
  }

  // Member flows need a real Collective. If the slug is missing or
  // unknown we render nothing — never fall back to a generic name.
  if (!collectiveSlug) return null
  const spaces = await getPublicSpaces().catch(() => [] as PublicSpaceCard[])
  const collective = spaces.find((s) => s.slug === collectiveSlug)
  if (!collective) return null

  return flow === 'member'
    ? memberScreen(collective)
    : memberUpgradeScreen(collective)
}

function creatorScreen(plan: PublicPlanDisplay): Screen {
  if (plan.slug === 'community') {
    return {
      eyebrow: 'Community Collective — new account',
      heading: 'Your Community Collective will be set up here',
      willHappen:
        'Once account creation and role activation are connected, this ' +
        'step will create your Fresh Collective account, add Creator ' +
        'capability to it, assign the Community plan, enrol you in ' +
        'World Builders, and route you into first-Collective onboarding.',
      prototypeReality:
        'A backend audit is complete and several of those steps are ' +
        'not yet supported end-to-end (see the audit findings shared ' +
        'with the team). In this prototype no account has been created, ' +
        'no Creator capability has been granted, no plan has been ' +
        'assigned, and no Collective has been set up.',
      primary: { label: 'Back to /for-creators', href: '/for-creators#plans' },
      secondary: { label: 'Return home', href: '/' },
    }
  }
  return {
    eyebrow: `${plan.displayName} — new account`,
    heading: `Your Fresh Collective account and ${plan.displayName} plan will be activated here`,
    willHappen:
      `Once Stripe and account creation are connected, this step will ` +
      `create your Fresh Collective account, activate your ${plan.displayName} ` +
      `plan, enrol you in the World Builders Collective, and open your ` +
      `Creator Studio.`,
    prototypeReality:
      'No payment has been taken, no account has been created, no ' +
      'Creator plan has been activated, no access has been granted, ' +
      'and you have not been enrolled in anything.',
    primary: { label: 'Back to /for-creators', href: '/for-creators#plans' },
    secondary: { label: 'Return home', href: '/' },
  }
}

function upgradeScreen(plan: PublicPlanDisplay): Screen {
  if (plan.slug === 'community') {
    return {
      eyebrow: 'Adding Community Collective to your account',
      heading: 'Your Community upgrade will be completed here',
      willHappen:
        'Once role and plan activation are connected, this step will ' +
        'add Creator capability to your existing Fresh Collective ' +
        'account, assign the Community plan, enrol you in World Builders, ' +
        'and route you into first-Collective onboarding. You will keep ' +
        'your current account, memberships and activity.',
      prototypeReality:
        'A backend audit is complete and several of those steps are ' +
        'not yet supported end-to-end. Nothing has changed on your ' +
        'account. No Creator capability has been added, no plan has ' +
        'been assigned, no enrolment has happened.',
      primary: { label: 'Back to /for-creators', href: '/for-creators#plans' },
      secondary: { label: 'Return home', href: '/' },
    }
  }
  return {
    eyebrow: `Adding ${plan.displayName} to your account`,
    heading: 'Your Creator upgrade will be completed here',
    willHappen:
      `Once Stripe is connected, this purchase will add Creator access ` +
      `to your existing Fresh Collective account and activate the ` +
      `${plan.displayName} plan. You will keep your current Member ` +
      `account, memberships and activity.`,
    prototypeReality:
      'No payment has been taken and no upgrade has been applied. Your ' +
      'account is unchanged. Nothing has been granted, enrolled or ' +
      'activated.',
    primary: { label: 'Back to /for-creators', href: '/for-creators#plans' },
    secondary: { label: 'Return home', href: '/' },
  }
}

function memberScreen(collective: PublicSpaceCard): Screen {
  return {
    eyebrow: `Joining ${collective.name}`,
    heading: 'Your account and access will be created here',
    willHappen:
      `Once payment is connected, this step will create your Fresh ` +
      `Collective account and unlock access to ${collective.name} ` +
      `through it.`,
    prototypeReality:
      `Nothing has been created. No account exists yet, no access to ` +
      `${collective.name} has been granted, and no payment has been ` +
      `processed.`,
    primary: {
      label: `Back to ${collective.name}`,
      href: `/spaces/${collective.slug}/about`,
    },
    secondary: { label: 'Return home', href: '/' },
  }
}

function memberUpgradeScreen(collective: PublicSpaceCard): Screen {
  return {
    eyebrow: `Adding access to ${collective.name}`,
    heading: 'Your access will be added here',
    willHappen:
      `Once payment is connected, this purchase will unlock access to ` +
      `${collective.name} through your existing Fresh Collective ` +
      `account.`,
    prototypeReality:
      `Nothing has been granted. Your account is unchanged and no ` +
      `access to ${collective.name} has been added.`,
    primary: {
      label: `Back to ${collective.name}`,
      href: `/spaces/${collective.slug}/about`,
    },
    secondary: { label: 'Return home', href: '/' },
  }
}

// ---------------------------------------------------------------------
// Small view helpers
// ---------------------------------------------------------------------

function HoldingBlock({
  title, body, tone,
}: {
  title: string
  body: string
  tone: 'future' | 'now'
}) {
  const isFuture = tone === 'future'
  return (
    <div
      className="rounded-2xl border p-6"
      style={{
        borderColor: isFuture
          ? 'rgba(12, 24, 38, 0.10)'
          : 'rgba(56, 160, 158, 0.32)',
        background: isFuture ? '#FFFFFF' : 'rgba(56, 160, 158, 0.06)',
        boxShadow: '0 4px 14px rgba(12, 24, 38, 0.05)',
      }}
    >
      <p
        className="text-[12px] uppercase"
        style={{
          color: isFuture ? INK_SOFT : TEAL_DEEP,
          letterSpacing: '0.14em',
          fontWeight: 600,
        }}
      >
        {title}
      </p>
      <p
        className="mt-3 text-[14.5px] leading-relaxed"
        style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
      >
        {body}
      </p>
    </div>
  )
}
