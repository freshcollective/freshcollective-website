import type { Metadata } from 'next'
import { redirect } from 'next/navigation'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import { requireAuthenticatedUser } from '@/lib/requireAuthenticatedUser'
import { getPublicPlatformArtwork, buildPlatformArtLookup } from '@/lib/serverApi'
import CreatorOnboardingCTA from '@/components/onboarding/CreatorOnboardingCTA'
import OnboardingHero from '@/components/onboarding/OnboardingHero'

/**
 * /creator-onboarding — the short, Creator-specific welcome shown
 * once after plan activation and before Build Your Collective.
 *
 * Deliberately lives *outside* /creator-studio. Creator Studio is
 * somewhere you arrive after onboarding, not where onboarding
 * happens.
 *
 * Access rules:
 *   * not signed in            → /login?next=/creator-onboarding
 *   * signed in, not a Creator → /dashboard (nothing to onboard into)
 *   * signed in, already
 *     completed this welcome   → /creator-studio (idempotent no-op)
 *   * signed in, active
 *     Creator, first visit     → render this page
 *
 * Ends with a single CTA — "Build your first Collective" — which
 * POSTs to /api/auth/me/complete-creator-onboarding and forwards to
 * /build-your-collective. No skip option; the welcome is intentionally
 * short enough that reading it once is the price of entry.
 */

export const metadata: Metadata = {
  title: 'Welcome, Creator — Fresh Collective',
  robots: { index: false, follow: false },
}

const NAVY = '#0C1826'
const TEAL_DEEP = '#246B6A'
const INK_BODY = 'rgba(12, 24, 38, 0.80)'
const INK_SOFT = 'rgba(12, 24, 38, 0.66)'

export default async function CreatorOnboardingPage() {
  // Shared guard — mirrors the pattern used by every protected
  // layout. Handles missing cookie, invalid signature, and stale
  // signature-for-gone-user in one call; ``next`` is preserved.
  const profile = await requireAuthenticatedUser({ fallbackNext: '/creator-onboarding' })

  // Non-Creators have nothing to onboard into. Rather than 403 them,
  // send them somewhere sensible — this route is only reachable
  // deliberately (via the claim endpoint's next_url) and by URL
  // guessing.
  if (profile.role !== 'creator' && profile.role !== 'admin') {
    redirect('/dashboard')
  }

  if (profile.has_completed_creator_onboarding) {
    redirect('/creator-studio')
  }

  const firstName = (profile.name ?? '').split(' ')[0] || null
  const artwork = await getPublicPlatformArtwork()
  const artFor = buildPlatformArtLookup(artwork)
  const heroUrl = artFor('creator_onboarding_welcome')

  return (
    <SiteShell>
      <section className="py-16 sm:py-24" style={{ background: '#FFFFFF' }}>
        <Container>
          <div className="mx-auto max-w-[720px]">
            <OnboardingHero
              imageUrl={heroUrl}
              alt=""
              fallback={<CreatorWelcomeMark />}
            />
          </div>
          <div className="mx-auto mt-10 max-w-[640px]">
            <p
              className="text-[13px] uppercase"
              style={{ color: TEAL_DEEP, letterSpacing: '0.16em', fontWeight: 600 }}
            >
              Welcome, Creator
            </p>
            <h1
              className="mt-4 font-serif leading-[1.06]"
              style={{
                fontSize: 'clamp(2.25rem, 5vw, 3rem)',
                letterSpacing: '-0.025em',
                color: NAVY,
              }}
            >
              {firstName ? `Welcome to Fresh Collective, ${firstName}.` : 'Welcome to Fresh Collective.'}
            </h1>
            <p
              className="mt-6 max-w-[520px] text-[16px] leading-relaxed"
              style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
            >
              Your Creator plan is active. A few things worth knowing
              before you begin.
            </p>

            <ul className="mt-8 flex flex-col gap-5">
              <WelcomePoint
                title="You&rsquo;re both a Member and a Creator."
                body={
                  <>Nothing about your Member account changes. Your
                  memberships, activity and messages stay exactly as
                  they are — Creator capability sits alongside them.</>
                }
              />
              <WelcomePoint
                title="World Builders is included."
                body={
                  <>Every Creator is automatically part of the World
                  Builders Collective — the room where Creators ask
                  questions, compare notes and see how others are
                  building. It&rsquo;s already showing on Your World.</>
                }
              />
              <WelcomePoint
                title="Help is nearby when you need it."
                body={
                  <>Post in World Builders any time. For account or
                  billing questions, reach the Fresh Collective team
                  from Creator Studio.</>
                }
              />
            </ul>

            <p
              className="mt-10 max-w-[520px] text-[15.5px] italic"
              style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
            >
              Ready to begin? Your first Collective is next.
            </p>

            <div className="mt-8">
              <CreatorOnboardingCTA />
            </div>
          </div>
        </Container>
      </section>
    </SiteShell>
  )
}


function CreatorWelcomeMark() {
  return (
    <svg viewBox="0 0 200 200" className="h-full w-full" aria-hidden="true">
      <defs>
        <radialGradient id="creatorSun" cx="0.5" cy="0.5" r="0.55">
          <stop offset="0%" stopColor="#D4B048" stopOpacity="0.85" />
          <stop offset="100%" stopColor="#D4B048" stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="100" cy="80" r="60" fill="url(#creatorSun)" />
      <circle cx="100" cy="80" r="16" fill="#D4B048" opacity="0.85" />
      <path d="M 10 145 Q 100 135 190 145" stroke="#246B6A" strokeWidth="1.3" fill="none" opacity="0.55" />
      <path d="M 30 165 Q 100 158 170 165" stroke="#246B6A" strokeWidth="1" fill="none" opacity="0.35" />
    </svg>
  )
}


function WelcomePoint({ title, body }: { title: React.ReactNode; body: React.ReactNode }) {
  return (
    <li className="flex gap-4">
      <span
        aria-hidden="true"
        className="mt-2 h-[6px] w-[6px] flex-shrink-0 rounded-full"
        style={{ background: TEAL_DEEP }}
      />
      <div>
        <p
          className="font-serif"
          style={{ fontSize: '1.15rem', color: NAVY, letterSpacing: '-0.01em' }}
        >
          {title}
        </p>
        <p
          className="mt-1 text-[15px] leading-relaxed"
          style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
        >
          {body}
        </p>
      </div>
    </li>
  )
}
