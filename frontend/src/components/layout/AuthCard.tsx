/**
 * AuthCard — the white auth surface used by every auth page's form
 * card: /login, /signup, /forgot-password, /reset-password.
 *
 * Owns three visual concerns so callers cannot drift from each other:
 *
 *   1. The white surface itself — rounded-2xl, max-w-[440px], generous
 *      padding, and the login-page shadow language (a deep drop for
 *      the dark auth background, plus a subtle secondary highlight).
 *   2. The centred Fresh Collective wordmark at the top.
 *   3. An optional centred heading + subtitle block, so the three
 *      "welcome / reset / set new password" cards read the same way.
 *
 * Callers own their form content and any inline error/success banners.
 *
 * If a caller needs a fully custom heading (e.g. /login's
 * checkout-context-aware copy), it can pass ``title={null}`` and render
 * its own heading inside ``children``.
 */

import Link from 'next/link'

const CARD_SHADOW =
  '0 24px 60px rgba(5, 11, 20, 0.35), 0 2px 8px rgba(5, 11, 20, 0.20)'

interface Props {
  /** Centred heading below the wordmark. Omit to render only the
   *  wordmark and let ``children`` provide its own heading. */
  title?: React.ReactNode
  /** Small subtitle under the heading. Ignored when ``title`` is
   *  ``null``. */
  subtitle?: React.ReactNode
  /** Inline error banner, rendered above ``children``. */
  error?: React.ReactNode
  /** Form contents + any additional inline banners. */
  children: React.ReactNode
  /** Link rendered under the form (e.g. "Back to log in"). */
  footerLink?: { href: string; label: string }
}

export default function AuthCard({
  title,
  subtitle,
  error,
  children,
  footerLink,
}: Props) {
  return (
    <div
      className="w-full max-w-[440px] rounded-2xl bg-white p-8 md:p-10"
      style={{ boxShadow: CARD_SHADOW }}
    >
      {/* Brand mark — full wordmark, centered and given room to breathe. */}
      <div className="mb-7 flex justify-center">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/brand/fresh-collective-logo-navy-gold-white.png"
          alt="Fresh Collective"
          style={{ height: '44px', width: 'auto' }}
        />
      </div>

      {title != null && (
        <div className="mb-7 text-center">
          <h1 className="mb-2 font-serif text-[26px] leading-tight text-navy-900">
            {title}
          </h1>
          {subtitle && (
            <p
              className="text-[14px] italic leading-relaxed"
              style={{ color: '#5A6B7D', fontFamily: 'Georgia, serif' }}
            >
              {subtitle}
            </p>
          )}
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="mb-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {error}
        </div>
      )}

      {children}

      {footerLink && (
        <p className="mt-6 text-center text-sm" style={{ color: '#5A6B7D' }}>
          <Link
            href={footerLink.href}
            className="font-medium text-teal-600 underline-offset-4 transition-colors hover:text-teal-700 hover:underline"
          >
            {footerLink.label}
          </Link>
        </p>
      )}
    </div>
  )
}
