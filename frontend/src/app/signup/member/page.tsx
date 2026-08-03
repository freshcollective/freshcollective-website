import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound, redirect } from 'next/navigation'
import SiteShell from '@/components/layout/SiteShell'
import Container from '@/components/layout/Container'
import PrototypeSignupForm from '@/components/checkout/PrototypeSignupForm'
import { getMe, getPublicSpace } from '@/lib/serverApi'
import { resolveMediaUrl } from '@/lib/api'

/**
 * /signup/member?collective=<slug> — member signup prototype for
 * someone joining a specific Collective.
 *
 * PROTOTYPE ONLY. Visual-only form; no account is created, no
 * Collective access is granted. Missing/invalid slug → not-found;
 * we never render "Join undefined" or default to a generic Collective.
 *
 * Logged-in visitors do not need a second account and are forwarded
 * to the honest holding screen for a member-upgrade flow. The
 * existing /signup route is unaffected by this page.
 */

export const metadata: Metadata = {
  title: 'Join — Fresh Collective',
  robots: { index: false, follow: false },
}

const NAVY = '#0C1826'
const TEAL_DEEP = '#246B6A'
const INK_BODY = 'rgba(12, 24, 38, 0.80)'
const INK_SOFT = 'rgba(12, 24, 38, 0.66)'

export default async function SignupMemberPage({
  searchParams,
}: {
  searchParams: Promise<{ collective?: string; preview?: string }>
}) {
  const { collective: slug } = await searchParams
  if (!slug) notFound()

  const collective = await getPublicSpace(slug)
  if (!collective) notFound()

  const me = await getMe().catch(() => null)
  if (me?.id) {
    redirect(
      `/checkout/next?flow=member-upgrade&collective=${collective.slug}&preview=true`,
    )
  }

  const nextHref = `/checkout/next?flow=member&collective=${collective.slug}&preview=true`

  const artUrl =
    resolveMediaUrl(
      collective.location_thumbnail_artwork_url ??
        collective.location_hero_artwork_url ??
        collective.cover_image_url,
    ) ?? null

  return (
    <SiteShell>
      <section
        className="py-16 sm:py-20"
        style={{ background: 'linear-gradient(180deg, #F7F5F1 0%, #FFFFFF 100%)' }}
      >
        <Container>
          <div className="mx-auto grid max-w-[1080px] grid-cols-1 items-start gap-12 md:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)] md:gap-16">
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
                Prototype preview
              </span>

              <h1
                className="mt-6 font-serif leading-[1.06]"
                style={{
                  fontSize: 'clamp(2rem, 4.4vw, 2.75rem)',
                  letterSpacing: '-0.025em',
                  color: NAVY,
                }}
              >
                Join {collective.name}
              </h1>
              <p
                className="mt-4 max-w-[460px] text-[16px] italic leading-relaxed"
                style={{ color: INK_SOFT, fontFamily: 'Georgia, serif' }}
              >
                Create your Fresh Collective account to become part of
                this community.
              </p>

              <div
                className="mt-8 overflow-hidden rounded-2xl border"
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
                <div className="p-6 sm:p-7">
                  <h2
                    className="font-serif leading-[1.1]"
                    style={{
                      fontSize: '1.4rem',
                      letterSpacing: '-0.02em',
                      color: NAVY,
                    }}
                  >
                    {collective.name}
                  </h2>
                  {collective.tagline && (
                    <p
                      className="mt-1 font-serif italic"
                      style={{ color: TEAL_DEEP }}
                    >
                      {collective.tagline}
                    </p>
                  )}
                  {collective.description && (
                    <p
                      className="mt-3 text-[14.5px] leading-relaxed"
                      style={{ color: INK_BODY, fontFamily: 'Georgia, serif' }}
                    >
                      {collective.description}
                    </p>
                  )}
                </div>
              </div>

              <div className="mt-6">
                <Link
                  href={`/spaces/${collective.slug}/about`}
                  className="text-[14px] font-semibold transition-opacity hover:opacity-80"
                  style={{ color: TEAL_DEEP }}
                >
                  Back to {collective.name}
                </Link>
              </div>
            </div>

            <div className="flex justify-center md:justify-end">
              <PrototypeSignupForm
                nextHref={nextHref}
                heading={`Join ${collective.name}`}
                subheading="Create your Fresh Collective account to become part of this community."
              />
            </div>
          </div>
        </Container>
      </section>
    </SiteShell>
  )
}
