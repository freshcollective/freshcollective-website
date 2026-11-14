import Link from 'next/link'
import type { CSSProperties } from 'react'

/**
 * Shared hero CTA button treatment.
 *
 * The homepage hero and the shared `ClosingInvitation` (rendered in
 * its `hero` variant on the homepage) previously duplicated these
 * exact styles inline. Any future adjustment had to be made in two
 * places and stayed in sync only by luck. This module is the single
 * source of truth for both.
 *
 * Two variants:
 *
 *   * `<HeroPrimaryCta>` — teal gradient pill with warm glow, white
 *     type. The "primary" action on the hero + closing card.
 *
 *   * `<HeroSecondaryCta>` — white pill with teal type. The "quiet"
 *     alternative. Sits comfortably next to the primary without
 *     competing.
 *
 * Shape: same 15px semibold text, same 28px × 14px padding, same
 * ``rounded-xl`` corner radius, same 1px hover-lift transition.
 */

const TEAL = '#38A09E'
const TEAL_STRONG = '#55B8B6'
const TEAL_TEXT = '#0f766e'

interface CtaProps {
  href: string
  children: React.ReactNode
  /** Optional additional classes; appended to the shared base. */
  className?: string
  /** Optional additional style; merged over the shared base. */
  style?: CSSProperties
}

/**
 * Shape alone — no width, no type size.
 *
 * Split out of ``BASE_CLASS`` so a consumer that is not a hero link
 * can wear the same button without copying its padding and radius.
 * The /starter-kit submit button is the first: it must stay full
 * width at every size and it must keep MailerLite's own ``primary``
 * class, neither of which a hero link wants.
 */
export const HERO_PRIMARY_SHAPE_CLASS =
  'inline-flex items-center justify-center rounded-xl px-7 py-3.5 font-semibold transition-all hover:-translate-y-px'

/** The white type and hover fade that go with the gradient below. */
export const HERO_PRIMARY_SKIN_CLASS = 'text-white hover:opacity-90'

/**
 * The teal gradient and its warm glow.
 *
 * **White on this gradient measures 3.14:1 at the teal end and
 * 2.35:1 at the light end** — below 4.5:1, and below the 3:1 that
 * large bold type would need. It is what the homepage hero has
 * always used, and it is reused rather than re-mixed so the two
 * surfaces cannot drift; the measurement is recorded here so the
 * next person to reach for it knows what they are taking on.
 */
export const HERO_PRIMARY_STYLE: CSSProperties = {
  background: `linear-gradient(135deg, ${TEAL} 0%, ${TEAL_STRONG} 100%)`,
  boxShadow: '0 2px 20px rgba(56,160,158,0.40)',
}

/**
 * The same button, deep enough for white type to clear AA.
 *
 * ``#126E6C → #17807E``: the same 135° direction, the same glow,
 * the same shape — only darker. Measured from rendered pixels,
 * white on it is 6.05:1 at the dark end and 4.75:1 at the light
 * end, so every part of the label clears 4.5:1, where
 * ``HERO_PRIMARY_STYLE`` manages 3.06:1 at best.
 *
 * Used by the /starter-kit submit button, which is the only control
 * on that page. The homepage hero deliberately still uses the
 * lighter gradient: changing it is a decision about the homepage,
 * not a side effect of this one. If that is ever revisited, the two
 * constants should collapse back into one — this exists to be
 * temporary.
 */
export const HERO_PRIMARY_STYLE_AA: CSSProperties = {
  background: 'linear-gradient(135deg, #126E6C 0%, #17807E 100%)',
  boxShadow: '0 2px 20px rgba(56,160,158,0.40)',
}

const BASE_CLASS = `${HERO_PRIMARY_SHAPE_CLASS} w-full text-[15px] sm:w-auto`

export function HeroPrimaryCta({ href, children, className, style }: CtaProps) {
  return (
    <Link
      href={href}
      className={`${BASE_CLASS} ${HERO_PRIMARY_SKIN_CLASS} ${className ?? ''}`}
      style={{ ...HERO_PRIMARY_STYLE, ...style }}
    >
      {children}
    </Link>
  )
}

export function HeroSecondaryCta({ href, children, className, style }: CtaProps) {
  return (
    <Link
      href={href}
      className={`${BASE_CLASS} bg-white hover:bg-[#F6F6F6] ${className ?? ''}`}
      style={{
        border: '1px solid rgba(255,255,255,0.12)',
        color: TEAL_TEXT,
        boxShadow: '0 4px 24px rgba(0,0,0,0.30)',
        ...style,
      }}
    >
      {children}
    </Link>
  )
}
