import type { Metadata } from 'next'
import Link from 'next/link'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import ArtworkFeatureComposition from '@/components/marketing/ArtworkFeatureComposition'
import {
  buildPlatformArtLookup,
  getPublicPlatformArtwork,
  type PublicPlatformArtwork,
} from '@/lib/serverApi'

/**
 * /ecosystem-interest — public Coming Soon page for the Ecosystem plan.
 *
 * The /for-creators page marks Ecosystem as "Coming soon" and links
 * here. This page holds that promise honestly: it explains what
 * Ecosystem is intended to be, and offers two truthful actions —
 * "Back to creator plans" and "Return home". It does not present a
 * waitlist or interest form until a real capture mechanism exists.
 *
 * Uses the shared `for_creators_organisation` Platform Artwork slot
 * (same key already rendered on /for-creators). The atmospheric
 * fallback in `ArtworkFeatureComposition` covers the case where no
 * image has been uploaded yet.
 */

export const metadata: Metadata = {
  title: 'Ecosystem — Coming soon — Fresh Collective',
  description:
    'Ecosystem is coming soon — a way for organisations to bring many Creators and Collectives together within one connected world.',
  robots: { index: true, follow: true },
}

const NAVY = '#0C1826'
const TEAL_DEEP = '#246B6A'
const INK_SOFT = 'rgba(12, 24, 38, 0.66)'
const INK_BODY = 'rgba(12, 24, 38, 0.80)'

export default async function EcosystemInterestPage() {
  const artwork = await getPublicPlatformArtwork().catch(
    () => [] as PublicPlatformArtwork[],
  )
  const artUrl = buildPlatformArtLookup(artwork)('for_creators_organisation')

  return (
    <SiteShell>
      <section className="py-16 sm:py-24" style={{ background: '#FFFFFF' }}>
        <Container>
          <div className="mx-auto grid max-w-[1160px] grid-cols-1 items-center gap-12 md:grid-cols-[minmax(0,1.15fr)_minmax(0,0.9fr)] md:gap-20">
            <ArtworkFeatureComposition
              artworkUrl={artUrl}
              atmosphereSlug="for-creators-organisation"
              artworkAlt="A wider connected landscape — an ecosystem of interlinked Collectives"
              aspectRatio="4 / 3"
            />

            <div className="flex flex-col">
              <span
                className="inline-flex w-fit items-center rounded-full border px-3 py-1"
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
                Coming soon
              </span>

              <h1
                className="mt-6 font-serif leading-[1.06]"
                style={{
                  fontSize: 'clamp(2rem, 4.4vw, 2.75rem)',
                  letterSpacing: '-0.025em',
                  color: NAVY,
                }}
              >
                Ecosystem is coming soon.
              </h1>

              <p
                className="mt-6 max-w-[520px] text-[15.5px] leading-relaxed"
                style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
              >
                We&rsquo;re building a way for organisations to bring
                many Creators and Collectives together within one
                connected ecosystem.
              </p>
              <p
                className="mt-4 max-w-[520px] text-[15.5px] leading-relaxed"
                style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
              >
                Support distinct communities, shared administration and
                a wider world of experiences — while allowing each
                Collective to keep its own identity.
              </p>
              <p
                className="mt-6 max-w-[520px] text-[14px] italic leading-relaxed"
                style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
              >
                A way to register interest will appear here once it&rsquo;s
                genuinely working. Until then, we&rsquo;d rather wait
                than pretend.
              </p>

              <div className="mt-8 flex flex-col items-start gap-4 sm:flex-row sm:items-center">
                <Link
                  href="/for-creators#plans"
                  className="inline-flex items-center rounded-full border px-6 py-3 text-[14px] font-semibold transition-colors hover:bg-slate-50"
                  style={{
                    borderColor: 'rgba(36, 107, 106, 0.35)',
                    color: TEAL_DEEP,
                    letterSpacing: '0.04em',
                    background: '#FFFFFF',
                  }}
                >
                  Back to creator plans →
                </Link>
                <Link
                  href="/"
                  className="text-[14px] font-semibold transition-opacity hover:opacity-80"
                  style={{ color: TEAL_DEEP }}
                >
                  Return home
                </Link>
              </div>
            </div>
          </div>
        </Container>
      </section>
    </SiteShell>
  )
}
