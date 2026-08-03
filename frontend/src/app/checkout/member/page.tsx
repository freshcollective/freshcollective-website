import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import { getMe, getPublicSpace } from '@/lib/serverApi'
import { resolveMediaUrl } from '@/lib/api'

/**
 * /checkout/member?collective=<slug> — payment placeholder for someone
 * joining a paid Collective.
 *
 * PROTOTYPE ONLY. No Stripe session is created, no purchase is
 * recorded, no access is granted. Forwards to the next honest screen
 * in the prototype flow.
 *
 * If the slug is missing or does not match a real public Collective,
 * we render a not-found — we never fall back to a generic Collective
 * or display "Join undefined".
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

export default async function CheckoutMemberPage({
  searchParams,
}: {
  searchParams: Promise<{ collective?: string }>
}) {
  const { collective: slug } = await searchParams
  if (!slug) notFound()

  // Fetch the single public Collective directly. Returns null for
  // unknown, private, draft or auto-grant Collectives — all rendered
  // as 404 rather than a "Join undefined" fallback.
  const collective = await getPublicSpace(slug)
  if (!collective) notFound()

  const me = await getMe().catch(() => null)
  const isLoggedIn = Boolean(me?.id)

  // Logged in → skip signup; forward to the honest holding screen
  // that describes an access-upgrade (never a new-account) flow.
  // Logged out → contextual member signup prototype.
  const nextHref = isLoggedIn
    ? `/checkout/next?flow=member-upgrade&collective=${collective.slug}&preview=true`
    : `/signup/member?collective=${collective.slug}&preview=true`

  const artUrl =
    resolveMediaUrl(
      collective.location_thumbnail_artwork_url ??
        collective.location_hero_artwork_url ??
        collective.cover_image_url,
    ) ?? null

  return (
    <SiteShell>
      <section className="py-20 sm:py-24" style={{ background: '#FFFFFF' }}>
        <Container>
          <div className="mx-auto max-w-[760px]">
            <PrototypeBadge />

            <h1
              className="mt-6 font-serif leading-[1.08]"
              style={{
                fontSize: 'clamp(2rem, 4.4vw, 2.75rem)',
                letterSpacing: '-0.025em',
                color: NAVY,
              }}
            >
              Payment will happen here
            </h1>
            <p
              className="mt-5 max-w-[560px] text-[15.5px] italic leading-relaxed"
              style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
            >
              When Stripe is connected, you&rsquo;ll review your purchase
              and complete payment securely before continuing. Nothing
              is charged in this prototype — no access to{' '}
              {collective.name} is granted.
            </p>

            <div
              className="mt-10 overflow-hidden rounded-2xl border"
              style={{
                borderColor: 'rgba(12, 24, 38, 0.10)',
                background: '#FFFFFF',
                boxShadow: '0 8px 24px rgba(12, 24, 38, 0.06)',
              }}
            >
              {artUrl && (
                <div
                  className="relative w-full overflow-hidden"
                  style={{ aspectRatio: '16 / 9' }}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={artUrl}
                    alt=""
                    aria-hidden="true"
                    className="absolute inset-0 h-full w-full object-cover object-center"
                  />
                </div>
              )}
              <div className="p-6 sm:p-8">
                <p
                  className="text-[13px] uppercase"
                  style={{ color: TEAL_DEEP, letterSpacing: '0.14em' }}
                >
                  You&rsquo;re joining
                </p>
                <h2
                  className="mt-2 font-serif leading-[1.1]"
                  style={{
                    fontSize: 'clamp(1.5rem, 3vw, 2rem)',
                    letterSpacing: '-0.02em',
                    color: NAVY,
                  }}
                >
                  {collective.name}
                </h2>
                {collective.tagline && (
                  <p
                    className="mt-1 font-serif italic"
                    style={{ color: TEAL_DEEP, fontSize: '1.05rem' }}
                  >
                    {collective.tagline}
                  </p>
                )}
                {collective.description && (
                  <p
                    className="mt-4 text-[15px] leading-relaxed"
                    style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
                  >
                    {collective.description}
                  </p>
                )}
              </div>
            </div>

            <div className="mt-10 flex flex-col items-start gap-4 sm:flex-row sm:items-center">
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
                href={`/spaces/${collective.slug}/about`}
                className="text-[14px] font-semibold transition-opacity hover:opacity-80"
                style={{ color: TEAL_DEEP }}
              >
                Back to {collective.name}
              </Link>
            </div>
          </div>
        </Container>
      </section>
    </SiteShell>
  )
}

function PrototypeBadge() {
  return (
    <span
      className="inline-flex items-center rounded-full border px-3 py-1"
      style={{
        borderColor: 'rgba(56, 160, 158, 0.32)',
        color: TEAL_DEEP,
        fontSize: '11px',
        letterSpacing: '0.16em',
        textTransform: 'uppercase',
        fontWeight: 600,
        fontFamily: 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
      }}
    >
      Prototype preview
    </span>
  )
}
