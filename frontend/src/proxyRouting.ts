/**
 * Pure routing logic for the proxy (middleware).
 *
 * Extracted from ``proxy.ts`` so it can be unit-tested without pulling
 * in ``next/server``. The proxy's runtime shim in ``proxy.ts`` composes
 * these helpers with the request cookie and issues the redirect.
 *
 * The single most important invariant enforced here:
 *
 *   ``/admin/login`` is a PUBLIC auth page, even though it sits under
 *   the ``/admin`` protected prefix. Auth-route matching happens BEFORE
 *   protected-prefix matching so the admin door is always reachable.
 */

/**
 * Collective routes are no longer gated here.
 *
 * The proxy sees only the shape of a URL. Since migration 137 the
 * answer depends on the Collective: one may publish its Gatherings to
 * everyone while another keeps them for members holding active
 * access, and ``/spaces/x/events`` looks identical in both. A
 * path-shape allowlist cannot express that, and while it tried, it
 * was wrong in both directions at once — it sent signed-out visitors
 * to /login for Gatherings the API served anonymously, and let
 * ``/pathways`` through for Collectives that wanted it closed.
 *
 * Two authorities deciding one question is the failure mode this
 * codebase keeps rediscovering, so there is now one: every Collective
 * page resolves its own area access server-side via
 * ``SpaceResponse.area_access`` and calls ``notFound()``, and every
 * API endpoint behind it refuses independently. Both answer 404
 * rather than redirecting, so a refusal never confirms that an area
 * exists — and nothing paints before disappearing.
 *
 * Unconditionally-private roots (/dashboard, /admin, /creator*,
 * /settings, /profile, /onboarding) keep their proxy protection,
 * where a URL's shape really is the whole answer.
 */
function isSpacesRouteProtected(_pathname: string): boolean {
  return false
}

/**
 * Public authentication routes — reachable while signed out. Match is
 * exact-path (with optional trailing slash), never prefix, so an
 * accidentally-named descendant route can never leak past the auth
 * guard.
 */
const AUTH_ROUTES: ReadonlySet<string> = new Set([
  '/login',
  '/signup',
  '/forgot-password',
  '/reset-password',
  '/admin/login',
])

/**
 * Protected top-level roots. Matched with a segment-boundary check
 * (``pathname === prefix`` or ``pathname.startsWith(prefix + '/')``) so
 * we never treat ``/creatorstudio`` as a member of ``/creator``.
 *
 * ``/creator`` and ``/creator-studio`` are separate top-level roots and
 * both appear here explicitly.
 */
const PROTECTED_PREFIXES: readonly string[] = [
  '/dashboard',
  '/admin',
  '/creator',
  '/creator-studio',
  '/profile',
  '/settings',
  '/onboarding',
]

function normalize(pathname: string): string {
  return pathname !== '/' && pathname.endsWith('/') ? pathname.slice(0, -1) : pathname
}

export function isAuthRoute(pathname: string): boolean {
  return AUTH_ROUTES.has(normalize(pathname))
}

export function isProtectedRoute(pathname: string): boolean {
  const p = normalize(pathname)
  // Auth pages are never protected, even when they sit under a
  // protected prefix (e.g. /admin/login lives under /admin).
  if (AUTH_ROUTES.has(p)) return false
  if (p === '/spaces' || p.startsWith('/spaces/')) {
    return isSpacesRouteProtected(p)
  }
  return PROTECTED_PREFIXES.some((prefix) => p === prefix || p.startsWith(prefix + '/'))
}

/** Login destination for a given protected pathname. */
export function loginPathFor(pathname: string): string {
  const p = normalize(pathname)
  return p === '/admin' || p.startsWith('/admin/') ? '/admin/login' : '/login'
}

/**
 * Restrict the ``next`` parameter so the admin door cannot bounce a
 * caller into a non-admin URL. Non-admin ``next`` values pass through
 * unchanged; the target auth page validates them again.
 */
export function safeNextFor(loginPath: string, pathname: string): string {
  if (loginPath !== '/admin/login') return pathname
  return pathname === '/admin' || pathname.startsWith('/admin/') ? pathname : '/admin'
}

/**
 * If ``pathname`` is a legacy Creator Studio URL of the form
 * ``/creator/spaces/[slug]/…``, return the slug so the proxy can sync
 * the active-collective cookie to match. Otherwise ``null``.
 *
 * The URL is authoritative on these routes — the page renders content
 * for the slug in ``params``, so the sidebar (which reads the cookie)
 * MUST agree. Without this sync, opening a bookmarked link, following
 * a link from Your World that targets a non-active collective, or
 * arriving from Build Your Collective all leave the sidebar showing
 * a different collective from the page.
 */
const CREATOR_SPACE_URL = /^\/creator\/spaces\/([^/?#]+)(?:\/|$)/

export function extractCreatorSpaceSlug(pathname: string): string | null {
  const match = pathname.match(CREATOR_SPACE_URL)
  return match ? match[1] : null
}

/**
 * Pure routing decision for a given (pathname, authenticated) pair.
 * Exported for unit testing.
 */
export type ProxyDecision =
  | { action: 'next' }
  | { action: 'redirect'; to: string; next?: string }

export function decide(pathname: string, authenticated: boolean): ProxyDecision {
  const protectedRoute = isProtectedRoute(pathname)

  if (protectedRoute && !authenticated) {
    const to = loginPathFor(pathname)
    return { action: 'redirect', to, next: safeNextFor(to, pathname) }
  }

  // Auth routes (``/login``, ``/signup``, ``/admin/login``, …) are ALWAYS
  // allowed through. The "already-signed-in → forward" redirect was
  // previously done here on the strength of a valid JWT signature alone,
  // which is unsafe: a JWT signed for a user that no longer exists (test
  // rollback, deleted account) would be bounced to ``/dashboard``, where
  // the layout's authoritative ``requireAuthenticatedUser`` check fails
  // and sends the caller back to ``/login`` — a loop the browser stops
  // with "The page isn't redirecting properly."
  //
  // Instead, the auth pages themselves call ``getMe()`` (authoritative)
  // and forward only when a live user actually exists. ``/admin/login``
  // has done this since it shipped; ``/login`` and ``/signup`` now do
  // the same.
  return { action: 'next' }
}
