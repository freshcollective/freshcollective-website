import Link from 'next/link'
import Container from '@/components/layout/Container'
import { HeroPrimaryCta, HeroSecondaryCta } from './heroCtaButtons'

/**
 * Shared closing-invitation card used by the homepage and /for-creators.
 *
 * Deep navy rounded card, teal atmospheric glow, gold hairline accent,
 * white serif heading (rendered as one or two lines), italic soft body,
 * teal-gradient primary CTA and a quiet secondary CTA. Optional
 * background artwork sits behind a dark gradient overlay so the copy
 * stays legible.
 *
 * Both consumer pages call this with different copy + CTAs; the
 * treatment is a constant so the two pages end the same way.
 */

const NAVY_DEEP = '#071824'
const TEAL = '#38A09E'

interface CTALink {
  label: string
  href: string
}

interface Props {
  /** Heading lines. Each entry is rendered as its own visible line
   *  via a `<span className="block">`. Pass one entry for a single
   *  line or two for a two-line heading. Entries may be plain strings
   *  or JSX nodes — passing a JSX span lets callers style a line
   *  differently (e.g. smaller / quieter secondary line). */
  headingLines: readonly React.ReactNode[]
  /** Short italic body sentence beneath the heading. */
  body: string
  primaryCta: CTALink
  /** Optional quiet secondary CTA. Omit for a single-CTA card. */
  secondaryCta?: CTALink
  /** Optional background artwork rendered behind a dark overlay. */
  artUrl?: string | null
  /** Button visual variant. `'pill'` (default) uses compact rounded
   *  pills — the /for-creators closing card uses this. `'hero'`
   *  matches the taller, less-rounded buttons in HomeHero so the
   *  homepage closing card reads as a direct continuation of the
   *  hero. */
  buttonVariant?: 'pill' | 'hero'
}

export default function ClosingInvitation({
  headingLines, body, primaryCta, secondaryCta, artUrl = null,
  buttonVariant = 'pill',
}: Props) {
  const isHero = buttonVariant === 'hero'
  return (
    <section className="py-16 sm:py-20" style={{ background: '#FFFFFF' }}>
      <Container>
        <div
          className="relative mx-auto max-w-[1080px] overflow-hidden rounded-3xl"
          style={{ background: NAVY_DEEP, boxShadow: '0 24px 60px rgba(7, 24, 36, 0.24)' }}
        >
          {/* Optional artwork — sits behind the dark overlay so it
              never overpowers the heading. */}
          {artUrl && (
            <>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={artUrl}
                alt=""
                aria-hidden="true"
                className="absolute inset-0 h-full w-full object-cover object-center"
                style={{ opacity: 0.28 }}
              />
              <div
                aria-hidden="true"
                className="absolute inset-0"
                style={{
                  background:
                    'linear-gradient(180deg, rgba(7, 24, 36, 0.35) 0%, rgba(7, 24, 36, 0.72) 60%, rgba(7, 24, 36, 0.88) 100%)',
                }}
              />
            </>
          )}

          {/* Teal atmospheric glow (always present). */}
          <div
            aria-hidden="true"
            className="absolute inset-0"
            style={{
              background:
                'radial-gradient(ellipse 80% 50% at 50% 0%, rgba(56, 160, 158, 0.20) 0%, transparent 65%)',
            }}
          />

          <div className="relative px-8 py-20 text-center sm:px-14 sm:py-28">
            <div
              className="mx-auto h-[2px] w-14 rounded-full"
              style={{ background: 'linear-gradient(90deg, rgba(212, 176, 72, 0.85) 0%, rgba(212, 176, 72, 0.30) 100%)' }}
              aria-hidden="true"
            />
            <h2
              className="mx-auto mt-10 max-w-[560px] font-serif leading-[1.1]"
              style={{
                fontSize: 'clamp(2rem, 5vw, 3.25rem)',
                letterSpacing: '-0.03em',
                color: '#FFFFFF',
              }}
            >
              {headingLines.map((line, i) => (
                <span key={i} className="block">{line}</span>
              ))}
            </h2>
            <p
              className="mx-auto mt-6 max-w-[480px] text-[15.5px] italic leading-relaxed"
              style={{ color: 'rgba(255, 255, 255, 0.76)', fontFamily: 'Georgia, serif' }}
            >
              {body}
            </p>
            <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
              {isHero ? (
                <HeroPrimaryCta href={primaryCta.href}>{primaryCta.label}</HeroPrimaryCta>
              ) : (
                <Link
                  href={primaryCta.href}
                  className="inline-flex w-full items-center justify-center rounded-full px-7 py-3 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 sm:w-auto"
                  style={{
                    background: `linear-gradient(135deg, ${TEAL} 0%, #55B8B6 100%)`,
                    letterSpacing: '0.04em',
                    boxShadow: '0 6px 24px rgba(56, 160, 158, 0.35)',
                  }}
                >
                  {primaryCta.label}
                </Link>
              )}
              {secondaryCta && (
                isHero ? (
                  <HeroSecondaryCta href={secondaryCta.href}>{secondaryCta.label}</HeroSecondaryCta>
                ) : (
                  <Link
                    href={secondaryCta.href}
                    className="inline-flex w-full items-center justify-center rounded-full px-7 py-3 text-[14px] font-semibold transition-colors sm:w-auto"
                    style={{
                      background: 'transparent',
                      border: '1px solid rgba(255, 255, 255, 0.22)',
                      color: '#FFFFFF',
                      letterSpacing: '0.04em',
                    }}
                  >
                    {secondaryCta.label}
                  </Link>
                )
              )}
            </div>
          </div>
        </div>
      </Container>
    </section>
  )
}
