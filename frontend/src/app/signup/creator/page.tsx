import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound, redirect } from 'next/navigation'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import PrototypeSignupForm from '@/components/checkout/PrototypeSignupForm'
import CommunityCollectiveSignup, {
  type CommunityStage,
} from '@/components/checkout/CommunityCollectiveSignup'
import ArtworkFeatureComposition from '@/components/marketing/ArtworkFeatureComposition'
import {
  buildPlatformArtLookup,
  getMe,
  getPublicPlatformArtwork,
  type PublicPlatformArtwork,
} from '@/lib/serverApi'
import { getPublicPlan } from '@/lib/plans'

/**
 * /signup/creator?plan=creator|pro|community — the creator account step.
 *
 * Community (free) is LIVE. Choosing it creates a real Fresh Collective
 * account, grants Creator capability on the free Community plan, enrols
 * the account in World Builders (via the auto-role reconciler behind
 * `promote_to_creator`), and forwards into the existing
 * /creator-onboarding → /build-your-collective flow. The limits shown
 * in the summary card are enforced server-side by
 * `backend/app/creator/plan_guards.py`, not merely displayed here.
 *
 * The paid plans (Creator, Pro) remain a prototype at this step: they
 * reach their account creation through Stripe checkout, which is a
 * separate flow, so they keep PrototypeSignupForm and the honest
 * holding screen at /checkout/next. Nothing about the paid path is
 * changed by the Community work.
 *
 * Left-column order (per the approved journey design):
 *   1. Selected plan artwork
 *   2. "You're choosing …" heading
 *   3. Plan tagline
 *   4. What this step does (prototype notice for paid plans only)
 *   5. Plan summary card
 *   6. "View the other plans" link
 * Right column is the account card.
 */

const NAVY = '#0C1826'
const TEAL_DEEP = '#246B6A'
const INK_SOFT = 'rgba(12, 24, 38, 0.66)'

export async function generateMetadata({
  searchParams,
}: {
  searchParams: Promise<{ plan?: string }>
}): Promise<Metadata> {
  const { plan: planParam } = await searchParams
  const plan = getPublicPlan(planParam)
  const isLive = plan?.slug === 'community'
  return {
    title: isLive
      ? 'Start a free Community Collective — Fresh Collective'
      : 'Create your account — Fresh Collective',
    // The free Community path is a real, completable signup, so it is
    // indexable. The paid plans' account step is still a prototype and
    // stays out of search until it is live.
    robots: isLive ? undefined : { index: false, follow: false },
  }
}

/** Which step of the live Community flow this visitor is actually at. */
function communityStage(me: { role?: string; email_verified_at?: string | null } | null): CommunityStage {
  if (!me) return 'signed_out'
  if (me.role && me.role !== 'user') return 'already_creator'
  if (!me.email_verified_at) return 'unverified'
  return 'ready'
}

export default async function SignupCreatorPage({
  searchParams,
}: {
  searchParams: Promise<{ plan?: string; preview?: string }>
}) {
  const { plan: planParam } = await searchParams
  const plan = getPublicPlan(planParam)
  if (!plan) notFound()

  const isCommunity = plan.slug === 'community'

  const [me, artwork] = await Promise.all([
    getMe().catch(() => null),
    getPublicPlatformArtwork().catch(() => [] as PublicPlatformArtwork[]),
  ])

  // Paid plans: a signed-in visitor is upgrading, not signing up, so they
  // never see a second account form. Unchanged behaviour.
  if (!isCommunity && me?.id) {
    redirect(`/checkout/next?flow=upgrade&plan=${plan.slug}&preview=true`)
  }

  const artUrl = buildPlatformArtLookup(artwork)(plan.artworkKey)
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

              {isCommunity ? (
                <p
                  className="mt-6 max-w-[520px] text-[15.5px] italic leading-relaxed"
                  style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
                >
                  This step creates your Fresh Collective account, adds
                  Creator capability on the free Community plan, includes
                  you in the World Builders Collective, and opens the
                  first-Collective onboarding. You can start building
                  straight away.
                </p>
              ) : (
                <>
                  <PrototypePill className="mt-6" />
                  <p
                    className="mt-3 max-w-[520px] text-[15.5px] italic leading-relaxed"
                    style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
                  >
                    In the live flow, account creation follows the payment
                    step. Nothing is created in this prototype — no
                    account, no Creator plan, no access.
                  </p>
                </>
              )}

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
              {isCommunity ? (
                <CommunityCollectiveSignup stage={communityStage(me)} />
              ) : (
                <PrototypeSignupForm
                  nextHref={nextHref}
                  heading="Create your Fresh Collective account"
                  subheading="A single account carries your membership, your Creator work, and everything you build."
                />
              )}
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
