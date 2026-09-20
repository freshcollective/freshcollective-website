'use client'

import Link from 'next/link'

import {
  FULL_LOGO_INTRINSIC,
  CHROME_MARK_PX,
  compactRoleFor,
  resolveBrandUrl,
  type BrandRole,
  type BrandTone,
} from '@/lib/brand'
import { useBrandOverrides } from './BrandProvider'

/**
 * The two ways Fresh Collective shows itself, and the only two.
 *
 * ``FreshCollectiveLogo`` is the full approved lockup — dragonfly and
 * wordmark — for surfaces with room to read it. ``BrandLockup`` is the
 * chrome treatment: a compact mark beside the name, in a header,
 * footer or sidebar.
 *
 * Both take a semantic role, never a filename, and both resolve
 * through the shared resolver so an admin upload in World Management
 * reaches every surface at once.
 *
 * What neither will ever do is improvise. The rounded teal square that
 * used to stand in for the brand in ten places is not reachable from
 * this module, and there is no code path that shrinks a full lockup
 * into a 28px box or crops one down to its dragonfly. When a compact
 * role has no approved artwork — all of them, today — the lockup
 * renders the name as live text and nothing else. That is a real
 * design, not a degraded one: clean type at 15px reads better than any
 * placeholder, and the day the artwork lands the mark appears here
 * with no further edit.
 */

// ---------------------------------------------------------------------------
// Full lockup
// ---------------------------------------------------------------------------

/**
 * Rendered sizes for the full lockup.
 *
 * The wordmark is 3% of the canvas height, so a 44px lockup — what
 * every auth card used before this — printed it at 1.3px. These sizes
 * are chosen against the artwork rather than against the layout:
 * ``hero`` gives a 7.7px cap height and is genuinely readable;
 * ``heroCompact`` gives 6.0px and is the smallest we will go on a
 * phone. Anything below that should be asking for a compact mark.
 */
export const FULL_LOGO_SIZES = {
  heroCompact: 200,
  hero: 256,
} as const

export function FreshCollectiveLogo({
  role = 'primary_light_logo',
  href,
  className = '',
  alt = 'Fresh Collective',
}: {
  role?: BrandRole
  /** Wrap the logo in a link. On the auth pages this is what carries
   *  the visitor home, which is why the header above them no longer
   *  needs a second brand element to do it. */
  href?: string
  className?: string
  alt?: string
}) {
  const url = resolveBrandUrl(role, useBrandOverrides())
  if (!url) return null

  const img = (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={url}
      alt={alt}
      width={FULL_LOGO_INTRINSIC}
      height={FULL_LOGO_INTRINSIC}
      className={`block h-[200px] w-auto sm:h-[256px] ${className}`}
    />
  )

  if (!href) return img
  return (
    <Link href={href} className="inline-block transition-opacity hover:opacity-80">
      {img}
    </Link>
  )
}

// ---------------------------------------------------------------------------
// Chrome lockup
// ---------------------------------------------------------------------------

const TEXT_BY_TONE: Record<BrandTone, string> = {
  light: 'text-[color:#0C1826]',
  dark: 'text-white',
}

export function BrandLockup({
  tone = 'light',
  href,
  label = 'Fresh Collective',
  sublabel,
  markSize = CHROME_MARK_PX,
  className = '',
}: {
  tone?: BrandTone
  href?: string
  label?: string
  /** Second line under the name — "Creator Studio", "World
   *  Management". Present in the two sidebars and the admin login. */
  sublabel?: string
  markSize?: number
  className?: string
}) {
  const markUrl = resolveBrandUrl(compactRoleFor(tone), useBrandOverrides())

  const body = (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      {markUrl && (
        // The mark is decorative: the name sits beside it as live text,
        // so announcing the image too would read the brand twice.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={markUrl}
          alt=""
          aria-hidden="true"
          width={markSize}
          height={markSize}
          className="block shrink-0"
          style={{ width: markSize, height: markSize }}
        />
      )}
      <span className="min-w-0">
        <span
          className={`block truncate text-[15px] font-semibold tracking-[-0.02em] ${TEXT_BY_TONE[tone]}`}
        >
          {label}
        </span>
        {sublabel && (
          <span
            className="mt-1 block text-[10px] font-semibold uppercase tracking-[0.16em]"
            style={{ color: tone === 'dark' ? 'rgba(255,255,255,0.55)' : '#64748B' }}
          >
            {sublabel}
          </span>
        )}
      </span>
    </span>
  )

  if (!href) return body
  return (
    <Link
      href={href}
      className="group inline-flex shrink-0 items-center transition-opacity hover:opacity-70"
    >
      {body}
    </Link>
  )
}
