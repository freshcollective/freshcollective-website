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

const BASE_CLASS =
  'inline-flex w-full items-center justify-center rounded-xl px-7 py-3.5 text-[15px] font-semibold transition-all hover:-translate-y-px sm:w-auto'

export function HeroPrimaryCta({ href, children, className, style }: CtaProps) {
  return (
    <Link
      href={href}
      className={`${BASE_CLASS} text-white hover:opacity-90 ${className ?? ''}`}
      style={{
        background: `linear-gradient(135deg, ${TEAL} 0%, ${TEAL_STRONG} 100%)`,
        boxShadow: '0 2px 20px rgba(56,160,158,0.40)',
        ...style,
      }}
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
