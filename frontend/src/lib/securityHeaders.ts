/**
 * SEC-011 Stage A — browser security-header definitions.
 *
 * Exported so both ``next.config.ts`` (which serves them) and
 * ``src/lib/csp.test.ts`` (which pins them against drift) can share
 * one source of truth. Keeping the CSP string here also means the
 * frame-src directive is built once from the ``EMBED_PROVIDERS``
 * allowlist and every consumer sees the same value.
 *
 * Stage C — CSP now ships as enforcing ``Content-Security-Policy``.
 * Flipped from Report-Only after a clean production browser
 * walkthrough (Mother World / admin, Your World, Explore Collectives,
 * Natural Leader Hub member surfaces, public homepage including
 * next/image blur-up, /verify-email) surfaced zero legitimate CSP
 * violations. Residual unexercised directives (``img-src blob:`` —
 * no production image picker with existing data; ``frame-src`` embed
 * providers — no active production embed content; Stripe
 * ``form-action``/``frame-src`` — checkout intentionally disabled)
 * are accepted coverage gaps: the derived allowlists are drift-
 * pinned by ``csp.test.ts`` against ``EMBED_PROVIDERS``, and the
 * defensive Stripe origin is included so the payments flag can flip
 * on without a follow-up header change. See SEC-011 investigation
 * §5 / §12 for the enforcement gate policy.
 */

import { EMBED_PROVIDERS } from './embedAllowlist.ts'

// Media host — ``<img src="{NEXT_PUBLIC_API_URL}/api/uploads/…">``
// on every uploaded asset. Baked in at build time.
const MEDIA_ORIGIN = (
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
).replace(/\/+$/, '')

// Turn a provider's host list into ``https://<host>`` entries.
// Every allowlisted embed provider is HTTPS-only (validated at
// ``checkEmbed`` in embedAllowlist.ts), so hardcoding the scheme
// matches the runtime constraint.
const EMBED_ORIGINS: readonly string[] = Array.from(
  new Set(EMBED_PROVIDERS.flatMap((p) => p.hosts.map((h) => `https://${h}`))),
)

// Stripe Checkout is redirect-only today (window.location.href = …).
// Listing the origin under form-action + frame-src future-proofs the
// day the FINITE_PLAN_MEMBER_CHECKOUT_ENABLED flag flips on without
// requiring another CSP change.
const STRIPE_CHECKOUT_ORIGIN = 'https://checkout.stripe.com'

const CSP_DIRECTIVES: Record<string, readonly string[]> = {
  'default-src': ["'self'"],
  // Next.js 16 hydration injects inline <script> tags. 'unsafe-inline'
  // is accepted for Stage A per policy — nonce/hash strategy is
  // deferred until after SEC-016 lands, since SEC-001 sanitisation
  // already closes the primary XSS surface.
  'script-src': ["'self'", "'unsafe-inline'"],
  // Same reasoning as script-src, plus pervasive React inline
  // ``style={…}`` attributes that would require every value to be
  // nonced/hashed. Not tractable without a large refactor.
  'style-src': ["'self'", "'unsafe-inline'"],
  // ``self`` for Next optimised images + static assets.
  // MEDIA_ORIGIN for <img src="{NEXT_PUBLIC_API_URL}/api/uploads/…">.
  // ``data:`` for Next's built-in image blur-up placeholders.
  // ``blob:`` for local file previews (URL.createObjectURL).
  'img-src': ["'self'", MEDIA_ORIGIN, 'data:', 'blob:'],
  'font-src': ["'self'"],
  // Browser code only talks to same-origin /api/* (SEC-002). If we
  // ever add browser telemetry, extend this directive.
  'connect-src': ["'self'"],
  // Embed providers + Stripe Checkout (defensive; not currently used
  // as an iframe but the redirect target is Stripe).
  'frame-src': [...EMBED_ORIGINS, STRIPE_CHECKOUT_ORIGIN],
  // Same-origin form posts + Stripe Checkout redirect target.
  'form-action': ["'self'", STRIPE_CHECKOUT_ORIGIN],
  // No page in Fresh Collective is intentionally embeddable.
  'frame-ancestors': ["'none'"],
  // Prevent <base href="//evil"> from repointing all relative URLs.
  'base-uri': ["'self'"],
  // No <object>, <embed>, Flash.
  'object-src': ["'none'"],
}

function serializeCsp(directives: Record<string, readonly string[]>): string {
  return Object.entries(directives)
    .map(([name, values]) => `${name} ${values.join(' ')}`)
    .join('; ')
}

export const CSP_REPORT_ONLY = serializeCsp(CSP_DIRECTIVES)

// Permissions-Policy — deny most; allow embed providers only where
// necessary (fullscreen for video, picture-in-picture for video,
// encrypted-media for DRM'd video). ``payment=(self)`` future-proofs
// the day Stripe Payment Request buttons ship; today the redirect
// flow doesn't require it.
const PERMISSIONS_POLICY = [
  'accelerometer=()',
  'autoplay=(self "https://youtube.com" "https://www.youtube.com" "https://player.vimeo.com" "https://fast.wistia.net")',
  'camera=()',
  'display-capture=()',
  'encrypted-media=(self "https://youtube.com" "https://www.youtube.com" "https://player.vimeo.com" "https://fast.wistia.net")',
  'fullscreen=(self "https://youtube.com" "https://www.youtube.com" "https://player.vimeo.com" "https://fast.wistia.net" "https://loom.com" "https://www.loom.com")',
  'geolocation=()',
  'gyroscope=()',
  'magnetometer=()',
  'microphone=()',
  'midi=()',
  'payment=(self)',
  'picture-in-picture=(self "https://youtube.com" "https://www.youtube.com" "https://player.vimeo.com")',
  'publickey-credentials-get=()',
  'sync-xhr=()',
  'usb=()',
  'xr-spatial-tracking=()',
].join(', ')

// Global security headers applied to every fc-web response.
// HSTS is deliberately without ``includeSubDomains`` / ``preload`` for
// Stage A — see SEC-011 investigation §6 / amendment 1. Revisit both
// after Fresh Collective migrates to its real production apex domain.
export const SECURITY_HEADERS: readonly { key: string; value: string }[] = [
  { key: 'Strict-Transport-Security', value: 'max-age=31536000' },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'Permissions-Policy', value: PERMISSIONS_POLICY },
  { key: 'X-Frame-Options', value: 'DENY' },
  // SEC-011 Stage C — enforcing. Value is unchanged from Stage A;
  // the ``CSP_REPORT_ONLY`` constant name is retained for source-
  // stability (grep-ability, existing test import path) even though
  // the header key is now the enforcing form.
  { key: 'Content-Security-Policy', value: CSP_REPORT_ONLY },
]
