import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound, redirect } from 'next/navigation'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import ArtworkFeatureComposition from '@/components/marketing/ArtworkFeatureComposition'
import {
  buildPlatformArtLookup,
  getMe,
  getPublicPlatformArtwork,
  type PublicPlatformArtwork,
} from '@/lib/serverApi'
import { getPublicPlan } from '@/lib/plans'

/**
 * /checkout/creator?plan=creator|pro — payment placeholder for the
 * Creator + Creator Portfolio plans.
 *
 * PROTOTYPE ONLY. This page does not initiate a Stripe session, does
 * not create any purchase record, and does not grant any entitlement.
 * Its only job is to preview the future payment step and forward the
 * visitor to the next honest screen in the prototype.
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
const TEAL = '#38A09E'
const TEAL_DEEP = '#246B6A'
const INK_BODY = 'rgba(12, 24, 38, 0.80)'
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

  const [me, artwork] = await Promise.all([
    getMe().catch(() => null),
    getPublicPlatformArtwork().catch(() => [] as PublicPlatformArtwork[]),
  ])
  const isLoggedIn = Boolean(me?.id)
  const artUrl = buildPlatformArtLookup(artwork)(plan.artworkKey)

  // Where the "Preview the next step" button sends the visitor:
  //   - Logged out → the creator signup prototype
  //   - Logged in  → the honest holding screen for an upgrade flow
  //                  (they must not be sent through a second signup)
  const nextHref = isLoggedIn
    ? `/checkout/next?flow=upgrade&plan=${plan.slug}&preview=true`
    : `/signup/creator?plan=${plan.slug}&preview=true`

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
              <h1
                className="font-serif leading-[1.06]"
                style={{
                  fontSize: 'clamp(2rem, 4.4vw, 2.75rem)',
                  letterSpacing: '-0.025em',
                  color: NAVY,
                }}
              >
                Payment will happen here
              </h1>

              <PrototypePill className="mt-5" />

              <p
                className="mt-4 max-w-[520px] text-[15.5px] italic leading-relaxed"
                style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
              >
                When Stripe is connected, you&rsquo;ll review your
                purchase and complete payment securely before continuing.
                Nothing is charged in this prototype — no account is
                created, no Creator plan is activated, no access is
                granted.
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

              <div className="mt-8 flex flex-col items-start gap-4 sm:flex-row sm:items-center">
                <Link
                  href={nextHref}
                  className="inline-flex items-center rounded-full px-7 py-3 text-[14px] font-semibold text-white transition-opacity hover:opacity-90"
                  style={{
                    background: `linear-gradient(135deg, ${TEAL} 0%, #55B8B6 100%)`,
                    letterSpacing: '0.04em',
                    boxShadow: '0 6px 24px rgba(56, 160, 158, 0.30)',
                  }}
                >
                  Preview the next step →
                </Link>
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
