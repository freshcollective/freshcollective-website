import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound, redirect } from 'next/navigation'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import PrototypeSignupForm from '@/components/checkout/PrototypeSignupForm'
import ArtworkFeatureComposition from '@/components/marketing/ArtworkFeatureComposition'
import {
  buildPlatformArtLookup,
  getMe,
  getPublicPlatformArtwork,
  type PublicPlatformArtwork,
} from '@/lib/serverApi'
import { getPublicPlan } from '@/lib/plans'

/**
 * /signup/creator?plan=creator|pro|community — creator signup prototype.
 *
 * PROTOTYPE ONLY. Renders the selected plan and a visual-only signup
 * form. Submitting the form does not create an account, does not
 * grant Creator capability, does not assign a plan, does not enrol
 * anyone in World Builders, and does not open Creator Studio.
 *
 * Logged-in visitors do not see a second form — they are forwarded
 * to the honest holding screen for the upgrade flow. The existing
 * /signup route and SignupForm.tsx are unaffected by this page.
 *
 * Left-column order (per the approved journey design):
 *   1. Selected plan artwork
 *   2. "You're choosing …" heading
 *   3. Plan tagline
 *   4. Prototype pill + short live-flow / prototype explanation
 *   5. Plan summary card
 *   6. "View the other plans" link
 * Right column is the signup form card, kept visually focused on
 * account creation (no plan artwork inside it).
 */

export const metadata: Metadata = {
  title: 'Create your account — Fresh Collective',
  robots: { index: false, follow: false },
}

const NAVY = '#0C1826'
const TEAL_DEEP = '#246B6A'
const INK_SOFT = 'rgba(12, 24, 38, 0.66)'

export default async function SignupCreatorPage({
  searchParams,
}: {
  searchParams: Promise<{ plan?: string; preview?: string }>
}) {
  const { plan: planParam } = await searchParams
  const plan = getPublicPlan(planParam)
  if (!plan) notFound()

  const [me, artwork] = await Promise.all([
    getMe().catch(() => null),
    getPublicPlatformArtwork().catch(() => [] as PublicPlatformArtwork[]),
  ])
  if (me?.id) {
    // Already have an account — never create a second one.
    redirect(`/checkout/next?flow=upgrade&plan=${plan.slug}&preview=true`)
  }
  const artUrl = buildPlatformArtLookup(artwork)(plan.artworkKey)

  // Form submit navigates to the honest holding screen.
  const nextHref = `/checkout/next?flow=creator&plan=${plan.slug}&preview=true`

  return (
    <SiteShell>
      <section
        className="py-16 sm:py-20"
        style={{ background: 'linear-gradient(180deg, #F7F5F1 0%, #FFFFFF 100%)' }}
      >
        <Container>
          <div className="mx-auto grid max-w-[1160px] grid-cols-1 items-start gap-12 md:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)] md:gap-16">
            <div className="flex flex-col">
              <ArtworkFeatureComposition
                artworkUrl={artUrl}
                atmosphereSlug={plan.atmosphereSlug}
                artworkAlt={plan.artworkAlt}
                aspectRatio="4 / 3"
              />

              <h1
                className="mt-8 font-serif leading-[1.06]"
                style={{
                  fontSize: 'clamp(2rem, 4.4vw, 2.75rem)',
                  letterSpacing: '-0.025em',
                  color: NAVY,
                }}
              >
                You&rsquo;re choosing {plan.displayName}
              </h1>
              <p
                className="mt-2 font-serif italic"
                style={{ color: TEAL_DEEP, fontSize: '1.15rem' }}
              >
                {plan.tagline}
              </p>

              <PrototypePill className="mt-6" />
              <p
                className="mt-3 max-w-[520px] text-[15.5px] italic leading-relaxed"
                style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
              >
                {plan.slug === 'community'
                  ? 'In the live flow, this step will create your Fresh Collective account, add Creator capability, assign the Community plan, and open the first-Collective onboarding. Nothing is created in this prototype — no account, no Creator capability, no Collective access.'
                  : 'In the live flow, account creation follows the payment step. Nothing is created in this prototype — no account, no Creator plan, no access.'}
              </p>

              <div
                className="mt-8 rounded-2xl border p-6 sm:p-7"
                style={{
                  borderColor: 'rgba(12, 24, 38, 0.10)',
                  background: '#FFFFFF',
                  boxShadow: '0 8px 24px rgba(12, 24, 38, 0.06)',
                }}
              >
                <h2
                  className="font-serif leading-[1.1]"
                  style={{
                    fontSize: '1.5rem',
                    letterSpacing: '-0.02em',
                    color: NAVY,
                  }}
                >
                  {plan.displayName}
                </h2>
                <p
                  className="mt-1 text-[15px]"
                  style={{ color: NAVY, fontFamily: 'Georgia, serif' }}
                >
                  <span className="font-semibold">{plan.priceLabel}</span>
                </p>
                <ul className="mt-4 flex flex-col gap-1.5">
                  {plan.summaryBullets.map((bullet) => (
                    <li
                      key={bullet}
                      className="text-[14px] leading-relaxed"
                      style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
                    >
                      <span aria-hidden="true" style={{ color: TEAL_DEEP }}>
                        ✓
                      </span>{' '}
                      {bullet}
                    </li>
                  ))}
                </ul>
              </div>

              <div className="mt-6">
                <Link
                  href="/for-creators#plans"
                  className="text-[14px] font-semibold transition-opacity hover:opacity-80"
                  style={{ color: TEAL_DEEP }}
                >
                  View the other plans
                </Link>
              </div>
            </div>

            <div className="flex justify-center md:justify-end">
              <PrototypeSignupForm
                nextHref={nextHref}
                heading="Create your Fresh Collective account"
                subheading="A single account carries your membership, your Creator work, and everything you build."
              />
            </div>
          </div>
        </Container>
      </section>
    </SiteShell>
  )
}

function PrototypePill({ className }: { className?: string }) {
  return (
    <span
      className={`inline-flex w-fit items-center rounded-full border px-3 py-1 ${className ?? ''}`}
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
  )
}
