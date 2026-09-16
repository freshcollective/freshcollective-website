import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound, redirect } from 'next/navigation'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import ArtworkFeatureComposition from '@/components/marketing/ArtworkFeatureComposition'
import CreatorCheckoutButton from '@/components/checkout/CreatorCheckoutButton'
import {
  buildPlatformArtLookup,
  getMe,
  getPublicPlatformArtwork,
  type PublicPlatformArtwork,
} from '@/lib/serverApi'
import { getPublicPlan } from '@/lib/plans'

/**
 * /checkout/creator?plan=creator|pro — Review-your-plan screen for
 * the Creator + Creator Portfolio subscriptions.
 *
 * Stripe is live. Clicking the CTA below POSTs to
 * ``/api/purchases/creator-subscription`` which creates a Stripe
 * Checkout Session (card-only per the workstream invariant) and
 * redirects the browser to Stripe's hosted checkout. Activation of
 * the local ``CreatorSubscription`` row happens only after
 * ``invoice.paid`` — see ``webhooks/creator_billing_handlers.py``.
 *
 * Community skips this page entirely — a plan=community request is
 * server-redirected to /signup/creator?plan=community.
 *
 * Artwork is loaded from the same public Platform Artwork slots used
 * by /for-creators, via the shared `buildPlatformArtLookup` helper.
 * `ArtworkFeatureComposition` handles the atmospheric fallback when
 * no image has been uploaded for the plan's key.
 */

export const metadata: Metadata = {
  title: 'Payment — Fresh Collective',
  robots: { index: false, follow: false },
}

const NAVY = '#0C1826'
const TEAL_DEEP = '#246B6A'
const INK_SOFT = 'rgba(12, 24, 38, 0.66)'

export default async function CheckoutCreatorPage({
  searchParams,
}: {
  searchParams: Promise<{ plan?: string }>
}) {
  const { plan: planParam } = await searchParams
  const plan = getPublicPlan(planParam)

  if (!plan) {
    notFound()
  }

  // Community skips the payment placeholder — it is free.
  if (plan.slug === 'community') {
    redirect('/signup/creator?plan=community')
  }

  const [, artwork] = await Promise.all([
    getMe().catch(() => null),
    getPublicPlatformArtwork().catch(() => [] as PublicPlatformArtwork[]),
  ])
  const artUrl = buildPlatformArtLookup(artwork)(plan.artworkKey)

  return (
    <SiteShell>
      <section className="py-16 sm:py-20" style={{ background: '#FFFFFF' }}>
        <Container>
          <div className="mx-auto grid max-w-[1160px] grid-cols-1 items-center gap-12 md:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)] md:gap-20">
            <ArtworkFeatureComposition
              artworkUrl={artUrl}
              atmosphereSlug={plan.atmosphereSlug}
              artworkAlt={plan.artworkAlt}
              aspectRatio="4 / 3"
            />

            <div className="flex flex-col">
              <p
                className="text-[11px] font-semibold uppercase tracking-[0.28em]"
                style={{ color: TEAL_DEEP }}
              >
                Secure checkout
              </p>
              <h1
                className="mt-3 font-serif leading-[1.06]"
                style={{
                  fontSize: 'clamp(2rem, 4.4vw, 2.75rem)',
                  letterSpacing: '-0.025em',
                  color: NAVY,
                }}
              >
                Review your plan
              </h1>

              <p
                className="mt-4 max-w-[520px] text-[15.5px] italic leading-relaxed"
                style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
              >
                You&rsquo;ll complete payment securely with Stripe.
                Your plan will activate once payment is confirmed.
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
                    fontSize: 'clamp(1.5rem, 3vw, 2rem)',
                    letterSpacing: '-0.02em',
                    color: NAVY,
                  }}
                >
                  {plan.displayName}
                </h2>
                <p
                  className="mt-1 font-serif italic"
                  style={{ color: TEAL_DEEP, fontSize: '1.05rem' }}
                >
                  {plan.tagline}
                </p>
                <p
                  className="mt-4 text-[15px]"
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
                      <span aria-hidden="true" style={{ color: TEAL_DEEP }}>·</span>{' '}
                      {bullet}
                    </li>
                  ))}
                </ul>
              </div>

              <div className="mt-8 flex flex-col items-start gap-4">
                <CreatorCheckoutButton planSlug={plan.slug} />
                <Link
                  href="/for-creators#plans"
                  className="text-[14px] font-semibold transition-opacity hover:opacity-80"
                  style={{ color: TEAL_DEEP }}
                >
                  View the other plans
                </Link>
              </div>
            </div>
          </div>
        </Container>
      </section>
    </SiteShell>
  )
}
