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
   * property of whichever image was uploaded. Below the text it
   * fades away entirely, so the lower part of the card shows the
   * artwork — which is the part the image is framed for.
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
              // Text at the top, generous room beneath it: the
              // bottom of the card is where the artwork is meant to
              // be seen, so it needs space that nothing sits on. The
              // min-height is what reserves that space when the copy
              // is short.
              ? 'relative min-h-[400px] overflow-hidden rounded-2xl px-8 pb-24 pt-10 sm:min-h-[440px] sm:px-10 sm:pb-32 sm:pt-12'
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
                className="absolute inset-0 h-full w-full object-cover"
                // Anchored low: the part of the artwork on show is
                // the bottom of the card, so that is the part worth
                // framing.
                style={{ objectPosition: 'center 75%' }}
              />
              {/* Darkest behind the words, fading out towards the
                  bottom so the artwork is seen where nothing sits on
                  it.

                  The second stop is in **pixels, not a percentage**,
                  and that is the whole trick. A straight ramp from
                  0.88 to 0.62 over the top 40% of the card crosses
                  the 0.823 that white needs for 4.5:1 at about 8.8%
                  of the height — long before the heading ends — so
                  the dark value has to be *held* across the text
                  rather than ramped through it. 200px covers the
                  heading and a two-line subtitle at every width,
                  however the copy wraps, which a percentage cannot
                  promise. The fade below it is proportional, so the
                  curve still scales with the card. */}
              <div
                aria-hidden="true"
                className="absolute inset-0"
                style={{
                  background:
                    'linear-gradient(180deg, rgba(7,24,36,0.88) 0px, '
                    + 'rgba(7,24,36,0.86) 200px, rgba(7,24,36,0.62) 58%, '
                    + 'rgba(7,24,36,0.15) 78%, rgba(7,24,36,0.00) 100%)',
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
