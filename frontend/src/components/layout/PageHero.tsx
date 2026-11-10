import type { ReactNode } from 'react'
import Container from './Container'

/**
 * PageHero — shared contained navy hero for member-facing
 * discovery destinations.
 *
 * Used by:
 *   /spaces           (Explore Collectives)
 *   /discover-places  (Discover Places)
 *   /ways-to-connect  (Ways to Connect)
 *
 * Deliberately NOT used by:
 *   /dashboard        — Your World's full-bleed personal welcome
 *                        band lives in the dashboard page itself.
 *   /spaces/[slug]/*  — the per-Collective identity header carries
 *                        location artwork and belongs to that
 *                        Collective's chrome.
 *
 * Three variants — enough for the whole set today without
 * introducing over-configuration.
 *
 *   title             — the heading text, always rendered in the
 *                        teal→white gradient.
 *   supportingCopy    — the white paragraph below the heading.
 *   accentLine        — the small teal→transparent line above the
 *                        heading. Defaults on; pass ``false`` to
 *                        omit if a page wants a starker feel later.
 *   children          — optional slot rendered inside the card,
 *                        below the supporting copy (for pages that
 *                        want to compose a small strip of content
 *                        inside the hero).
 *   backgroundImage   — optional artwork behind the card's content,
 *                        under a navy gradient. See the contrast
 *                        note on the prop.
 *   bandBackground    — the colour of the band the card sits in.
 *                        Defaults to the warm off-white the member
 *                        destinations use; /guides passes white
 *                        because that page is white throughout.
 *
 * The card sits inside a Container and a page-background band so
 * the hero has room to breathe both above and below. Consumers
 * don't need to wrap it themselves.
 */

interface BackgroundImage {
  url: string
  /** Describes the artwork. Empty marks it decorative. */
  alt: string
}

interface Props {
  title: string
  supportingCopy?: ReactNode
  accentLine?: boolean
  children?: ReactNode
  /**
   * Artwork behind the card's content.
   *
   * **The heading loses its gradient when this is set, deliberately.**
   * The teal end of the teal-to-white gradient is `#38A09E`, which
   * measures 5.74:1 on solid navy — fine — but to hold 4.5:1 against
   * an arbitrary image the navy overlay would need ~98% opacity,
   * which is solid navy with extra steps and no visible artwork.
   * White text needs ~82%, which leaves the image readable as
   * atmosphere. So artwork and the gradient are mutually exclusive,
   * and the choice here is artwork plus a heading that is legible
   * over it.
   *
   * The overlay is never lighter than that 82% anywhere the text
   * sits, which is what makes the contrast a guarantee rather than a
   * property of whichever image was uploaded.
   */
  backgroundImage?: BackgroundImage | null
  /** The band behind the card. Defaults to the warm off-white. */
  bandBackground?: string
}

export default function PageHero({
  title,
  supportingCopy,
  accentLine = true,
  children,
  backgroundImage = null,
  bandBackground = '#FDFCF9',
}: Props) {
  const hasArt = backgroundImage !== null && backgroundImage.url !== ''
  return (
    <div className="py-8 sm:py-10" style={{ background: bandBackground }}>
      <Container>
        <div
          className={
            hasArt
              ? 'relative overflow-hidden rounded-2xl px-8 pb-10 pt-16 sm:px-10 sm:pb-12 sm:pt-24'
              : 'relative overflow-hidden rounded-2xl px-8 py-10 sm:px-10 sm:py-12'
          }
          style={{
            background: '#071824',
            border: '1px solid rgba(56,160,158,0.22)',
            boxShadow:
              '0 0 0 1px rgba(56,160,158,0.08), 0 8px 32px rgba(7,24,36,0.18), 0 0 48px rgba(56,160,158,0.06)',
          }}
        >
          {hasArt && (
            <>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={backgroundImage!.url}
                alt={backgroundImage!.alt}
                {...(backgroundImage!.alt ? {} : { 'aria-hidden': true })}
                className="absolute inset-0 h-full w-full object-cover object-center"
              />
              {/* Lighter at the top so the artwork reads, settling to
                  near-solid navy where the words are. Never below
                  0.84 at the heading, which is the measured floor for
                  white at 4.5:1 over a worst-case white image —
                  see the prop's note. */}
              <div
                aria-hidden="true"
                className="absolute inset-0"
                style={{
                  background:
                    'linear-gradient(180deg, rgba(7,24,36,0.55) 0%, '
                    + 'rgba(7,24,36,0.84) 28%, rgba(7,24,36,0.92) 60%, '
                    + 'rgba(7,24,36,0.97) 100%)',
                }}
              />
            </>
          )}

          <div className="relative">
          {accentLine && (
            <div
              className="mb-5 h-[2px] w-8 rounded-full"
              style={{
                background:
                  'linear-gradient(90deg, #38A09E 0%, rgba(56,160,158,0.2) 100%)',
              }}
              aria-hidden="true"
            />
          )}

          <h1
            className="mb-3 font-serif"
            style={{
              fontSize: 'clamp(2rem, 4vw, 3rem)',
              lineHeight: '1.1',
              letterSpacing: '-0.03em',
            }}
          >
            {/* The gradient only on plain navy. Over artwork it is
                replaced by solid white — see the prop's note for the
                measured reason. */}
            <span
              style={
                hasArt
                  ? { display: 'inline-block', color: '#FFFFFF' }
                  : {
                      display: 'inline-block',
                      background: 'linear-gradient(90deg, #38A09E 0%, #FFFFFF 55%)',
                      WebkitBackgroundClip: 'text',
                      WebkitTextFillColor: 'transparent',
                      backgroundClip: 'text',
                    }
              }
            >
              {title}
            </span>
          </h1>

          {supportingCopy && (
            <p
              className="max-w-[560px] text-[15px] leading-[1.78]"
              style={{ color: '#FFFFFF' }}
            >
              {supportingCopy}
            </p>
          )}

          {children && <div className="mt-6">{children}</div>}
          </div>
        </div>
      </Container>
    </div>
  )
}
