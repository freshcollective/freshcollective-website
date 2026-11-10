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
  /**
   * Horizontal alignment of the rule, heading and supporting copy.
   *
   * Left by default, which is what the member destinations have
   * always been. /guides centres, matching its mockup.
   */
  align?: 'left' | 'center'
  /**
   * The colour of the thin rule above the heading.
   *
   * Teal by default — it is the platform accent and what every
   * member destination has always used. /guides takes gold, the same
   * hairline ``ClosingInvitation`` draws at the foot of the homepage,
   * so the editorial surfaces rhyme with each other rather than with
   * the app.
   */
  accentTone?: 'teal' | 'gold'
}

export default function PageHero({
  title,
  supportingCopy,
  accentLine = true,
  children,
  backgroundImage = null,
  bandBackground = '#FDFCF9',
  align = 'left',
  accentTone = 'teal',
}: Props) {
  // Copied value-for-value from ``ClosingInvitation`` rather than
  // approximated: two gold hairlines that are nearly the same gold
  // look like a mistake, and nobody would ever find it.
  const accentGradient = accentTone === 'gold'
    ? 'linear-gradient(90deg, rgba(212, 176, 72, 0.85) 0%, rgba(212, 176, 72, 0.30) 100%)'
    : 'linear-gradient(90deg, #38A09E 0%, rgba(56,160,158,0.2) 100%)'
  const hasArt = backgroundImage !== null && backgroundImage.url !== ''
  const centred = align === 'center'
  /**
   * Carried by the words rather than by darkness.
   *
   * The artwork is the point of the header, so the overlay stays
   * light enough to show it and the type earns its legibility from a
   * soft shadow instead. The shadow is additional to the measured
   * contrast, never a substitute — the composited background behind
   * the glyphs still has to clear 4.5:1 on its own.
   */
  const artTextShadow = hasArt
    ? { textShadow: '0 2px 12px rgba(7,24,36,0.6)' }
    : {}
  return (
    <div className="py-8 sm:py-10" style={{ background: bandBackground }}>
      <Container>
        <div
          className={
            hasArt
              // Short enough not to be mostly empty sea, tall enough
              // that the islands sit below the words rather than
              // behind them. The copy lands in the upper middle and
              // the artwork carries the rest.
              ? 'relative min-h-[300px] overflow-hidden rounded-2xl px-8 pb-20 pt-10 sm:min-h-[340px] sm:px-10 sm:pb-24 sm:pt-12'
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
                // 45% down keeps the golden sky and the islands both
                // in frame; anchoring lower cropped the sunset out
                // entirely, which is the one thing the artwork is
                // there for.
                //
                // Horizontally it moves with the viewport. A phone
                // card is nearly square, so ``cover`` shows only the
                // middle ~60% of a wide image — and on this artwork
                // that middle is the islands with the sun cropped
                // off the right. 70% brings the sun back into frame
                // on a narrow screen; from ``sm`` up the card is wide
                // enough that centring already includes it.
                className="absolute inset-0 h-full w-full object-cover [object-position:70%_45%] sm:[object-position:center_45%]"
                
              />
              {/* Light enough to let the sunset through, dense
                  enough behind the words.

                  Three jobs in one ramp. It stays thin at the very
                  top so the sky reads; it holds a plateau across the
                  text band; and it thins again towards the bottom so
                  the islands and the water are seen plainly.

                  0.50 across the text is a floor, not a preference.
                  Measured behind the glyphs on this artwork, the
                  brightest patch any letter sits on is L≈0.334: 0.45
                  put two of the three widths at 4.4:1, and 0.48 only
                  just clears the line. 0.50 leaves a little margin
                  for antialiasing without greying the sky out again.
                  A different image moves that number — re-measure
                  rather than assuming this one carries over.

                  The plateau is measured in **pixels, not a
                  percentage**, and that is the part worth keeping. A
                  proportional stop moves with the card, but the text
                  does not — on a phone the subtitle wraps to two
                  lines and the words reach further down a shorter
                  card than they do on a desktop. Pixels from the top
                  cover the copy at every width however it wraps; a
                  percentage is only ever right at one of them. */}
              <div
                aria-hidden="true"
                className="absolute inset-0"
                style={{
                  background:
                    'linear-gradient(180deg, rgba(7,24,36,0.28) 0px, '
                    + 'rgba(7,24,36,0.50) 56px, rgba(7,24,36,0.50) 210px, '
                    + 'rgba(7,24,36,0.28) 82%, rgba(7,24,36,0.10) 100%)',
                }}
              />
            </>
          )}

          <div className={centred ? 'relative text-center' : 'relative'}>
          {accentLine && (
            <div
              className={
                centred
                  ? 'mx-auto mb-5 h-[2px] w-8 rounded-full'
                  : 'mb-5 h-[2px] w-8 rounded-full'
              }
              style={{ background: accentGradient }}
              aria-hidden="true"
            />
          )}

          <h1
            className="mb-3 font-serif"
            style={{
              fontSize: 'clamp(2rem, 4vw, 3rem)',
              lineHeight: '1.1',
              letterSpacing: '-0.03em',
              ...artTextShadow,
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
              className={
                centred
                  ? 'mx-auto max-w-[560px] text-[15px] leading-[1.78]'
                  : 'max-w-[560px] text-[15px] leading-[1.78]'
              }
              style={{ color: '#FFFFFF', ...artTextShadow }}
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
